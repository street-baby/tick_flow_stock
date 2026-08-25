# -*- coding: utf-8 -*-
"""智兔数服 (Zhitu API) Provider 实现。

将智兔 API 的 JSON 响应规范化为系统内部 Polars DataFrame 与结构契约。
支持日K (daily)、除权因子 (adj_factor)、分钟K (minute)、全市场实时行情 (realtime)、财务报表 (financial) 与标的维表 (instruments)。
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable, List, Optional

import polars as pl

from app.data_providers.base import AssetType
from app.data_providers.normalizer import normalize_adj_factors, normalize_daily
from app.plugins.zhitu.client import (
    ZhituClient,
    get_token,
    is_index,
    to_standard_code,
)
from app.tickflow.rate_limits import chunked

logger = logging.getLogger(__name__)

_DATASETS = ("daily", "adj_factor", "minute", "realtime", "financial")
_BATCH = 20
_CONCURRENCY = 8
_MINUTE_CANONICAL = ["symbol", "datetime", "open", "high", "low", "close", "volume", "amount"]


def _clean_num(val: Any) -> Optional[float]:
    if val is None or val == "-" or val == "":
        return None
    try:
        return float(val)
    except Exception:
        return None


def _clean_date_str(val: Any) -> Optional[str]:
    if not val or val == "-":
        return None
    s = str(val).strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s


@dataclass
class _ZhituConfig:
    name: str = "zhitu"
    display_name: str = "智兔数服（Zhitu API）"
    datasets: dict = field(default_factory=lambda: dict.fromkeys(_DATASETS))
    path: None = None
    builtin: bool = True


def availability() -> tuple[bool, str]:
    """自检函数：检查 Token 是否已配置。"""
    token = get_token()
    if not token:
        return False, "未配置 ZHITU_API_TOKEN 密钥证书"
    return True, "ok"


class ZhituProvider:
    """智兔数服数据源 Provider。"""

    name = "zhitu"
    builtin = True

    def __init__(self) -> None:
        self.config = _ZhituConfig()
        self._client = ZhituClient()

    def close(self) -> None:
        self._client.close()

    # ---- daily ----
    def get_daily(
        self,
        symbols: list[str],
        start_time: datetime | None,
        end_time: datetime | None,
        asset_type: str = "stock",  # noqa: ARG002
        on_chunk_done: Callable[[int, int], None] | None = None,
    ) -> pl.DataFrame:
        if not symbols:
            return pl.DataFrame()

        start_str = start_time.strftime("%Y-%m-%d") if start_time else None
        end_str = end_time.strftime("%Y-%m-%d") if end_time else None

        logger.info("智兔 daily 拉取开始 (%d symbols, %s ~ %s)", len(symbols), start_str, end_str)
        frames: list[pl.DataFrame] = []
        chunks = list(chunked(symbols, _BATCH))

        def _fetch_single(sym: str) -> Optional[pl.DataFrame]:
            rows = self._client.fetch_daily_klines(sym, adj="n")
            if not rows:
                return None
            clean_rows = []
            for r in rows:
                d_str = r.get("t")
                if not d_str:
                    continue
                if start_str and d_str < start_str:
                    continue
                if end_str and d_str > end_str:
                    continue
                clean_rows.append({
                    "date": d_str,
                    "open": r.get("o"),
                    "high": r.get("h"),
                    "low": r.get("l"),
                    "close": r.get("c"),
                    "volume": r.get("v"),
                    "amount": r.get("a"),
                    "symbol": sym,
                })
            if not clean_rows:
                return None
            return normalize_daily(clean_rows, default_symbol=sym, source=self.name)

        for i, chunk in enumerate(chunks):
            with ThreadPoolExecutor(max_workers=_CONCURRENCY) as executor:
                futures = [executor.submit(_fetch_single, sym) for sym in chunk]
                for fut in as_completed(futures):
                    try:
                        df = fut.result()
                        if df is not None and not df.is_empty():
                            frames.append(df)
                    except Exception as e:
                        logger.warning("智兔 daily 单股拉取异常: %s", e)
            if on_chunk_done:
                on_chunk_done(i + 1, len(chunks))

        return pl.concat(frames, how="diagonal_relaxed") if frames else pl.DataFrame()

    # ---- adj_factor ----
    def get_adj_factors(
        self,
        symbols: list[str],
        start_time: datetime | None,
        end_time: datetime | None,
        asset_type: str = "stock",  # noqa: ARG002
        on_chunk_done: Callable[[int, int], None] | None = None,
    ) -> pl.DataFrame:
        if not symbols:
            return pl.DataFrame()

        start_str = start_time.strftime("%Y-%m-%d") if start_time else None
        end_str = end_time.strftime("%Y-%m-%d") if end_time else None

        frames: list[pl.DataFrame] = []
        chunks = list(chunked(symbols, _BATCH))

        def _fetch_adj_single(sym: str) -> Optional[pl.DataFrame]:
            if is_index(sym):
                return None
            rows_n = {r["t"]: r["c"] for r in self._client.fetch_daily_klines(sym, adj="n") if "t" in r and "c" in r}
            rows_f = {r["t"]: r["c"] for r in self._client.fetch_daily_klines(sym, adj="f") if "t" in r and "c" in r}
            adj_rows = []
            for t_date, c_n in rows_n.items():
                if start_str and t_date < start_str:
                    continue
                if end_str and t_date > end_str:
                    continue
                c_f = rows_f.get(t_date)
                if c_f is not None and c_n and float(c_n) != 0.0:
                    factor = round(float(c_f) / float(c_n), 6)
                else:
                    factor = 1.0
                adj_rows.append({
                    "symbol": sym,
                    "trade_date": t_date,
                    "ex_factor": factor,
                })
            if not adj_rows:
                return None
            return normalize_adj_factors(adj_rows, source=self.name)

        for i, chunk in enumerate(chunks):
            with ThreadPoolExecutor(max_workers=_CONCURRENCY) as executor:
                futures = [executor.submit(_fetch_adj_single, sym) for sym in chunk]
                for fut in as_completed(futures):
                    try:
                        df = fut.result()
                        if df is not None and not df.is_empty():
                            frames.append(df)
                    except Exception as e:
                        logger.warning("智兔 adj_factor 单股计算异常: %s", e)
            if on_chunk_done:
                on_chunk_done(i + 1, len(chunks))

        return pl.concat(frames, how="diagonal_relaxed") if frames else pl.DataFrame()

    # ---- minute ----
    def get_minute(
        self,
        symbols: list[str],
        start_time: datetime | None,
        end_time: datetime | None,
        asset_type: AssetType = "stock",  # noqa: ARG002
        freq: str = "5m",
        on_chunk_done: Callable[[int, int], None] | None = None,
    ) -> pl.DataFrame:
        if not symbols:
            return pl.DataFrame()

        period = "".join(ch for ch in str(freq) if ch.isdigit()) or "5"
        if period not in ("5", "15", "30", "60"):
            period = "5"

        start_str = start_time.strftime("%Y-%m-%d %H:%M") if start_time else None
        end_str = end_time.strftime("%Y-%m-%d %H:%M") if end_time else None

        logger.info("智兔 minute 拉取开始 (%d symbols, period=%sm)", len(symbols), period)
        frames: list[pl.DataFrame] = []
        chunks = list(chunked(symbols, _BATCH))

        def _fetch_minute_single(sym: str) -> Optional[pl.DataFrame]:
            is_idx = (asset_type == "index") or is_index(sym)
            rows = self._client.fetch_minute_klines(sym, period=period, adj="n", is_idx=is_idx)
            if not rows:
                return None
            clean_rows = []
            for r in rows:
                d_str = r.get("t")
                if not d_str:
                    continue
                if start_str and d_str < start_str:
                    continue
                if end_str and d_str > end_str:
                    continue
                clean_rows.append({
                    "datetime": d_str,
                    "open": r.get("o"),
                    "high": r.get("h"),
                    "low": r.get("l"),
                    "close": r.get("c"),
                    "volume": r.get("v"),
                    "amount": r.get("a"),
                    "symbol": sym,
                })
            if not clean_rows:
                return None
            df = pl.DataFrame(clean_rows)
            df = df.with_columns(
                pl.col("datetime").str.to_datetime("%Y-%m-%d %H:%M:%S", strict=False).alias("datetime")
            )
            for col in ("open", "high", "low", "close", "volume", "amount"):
                if col in df.columns:
                    df = df.with_columns(pl.col(col).cast(pl.Float64, strict=False))
            keep = [c for c in _MINUTE_CANONICAL if c in df.columns]
            return df.select(keep) if "datetime" in keep else None

        for i, chunk in enumerate(chunks):
            with ThreadPoolExecutor(max_workers=_CONCURRENCY) as executor:
                futures = [executor.submit(_fetch_minute_single, sym) for sym in chunk]
                for fut in as_completed(futures):
                    try:
                        df = fut.result()
                        if df is not None and not df.is_empty():
                            frames.append(df)
                    except Exception as e:
                        logger.warning("智兔 minute 单股拉取异常: %s", e)
            if on_chunk_done:
                on_chunk_done(i + 1, len(chunks))

        return pl.concat(frames, how="diagonal_relaxed") if frames else pl.DataFrame()

    # ---- realtime (全市场快照) ----
    def get_realtime(self) -> list[dict]:
        logger.info("智兔 realtime 拉取开始 (全市场快照)")
        raw_list = self._client.fetch_realtime_quotes()
        if not raw_list:
            return []

        out: list[dict] = []
        for r in raw_list:
            dm = r.get("dm")
            if not dm:
                continue
            symbol = to_standard_code(str(dm))
            t_str = r.get("t")
            ts_val = None
            if t_str:
                try:
                    ts_val = int(datetime.strptime(t_str, "%Y-%m-%d %H:%M:%S").timestamp() * 1000)
                except Exception:
                    pass

            last_p = float(r.get("p") or 0.0)
            yc = float(r.get("yc") or 0.0)
            o = float(r.get("o") or 0.0)
            h = float(r.get("h") or 0.0)
            l_val = float(r.get("l") or 0.0)
            v = float(r.get("v") or 0.0)
            cje = float(r.get("cje") or 0.0)
            pc = float(r.get("pc") or 0.0)
            ud = float(r.get("ud") or 0.0)
            zf = float(r.get("zf") or 0.0)
            hs = float(r.get("hs") or r.get("tr") or 0.0)

            out.append({
                "symbol": symbol,
                "name": r.get("mc") or r.get("name") or "",
                "last_price": last_p,
                "prev_close": yc,
                "open": o,
                "high": h,
                "low": l_val,
                "volume": v,
                "amount": cje,
                "change_pct": pc,
                "change_amount": ud,
                "amplitude": zf,
                "turnover_rate": hs,
                "timestamp": ts_val,
                "session": "trade",
            })
        logger.info("智兔 realtime 解析完成: %d 条快照", len(out))
        return out

    # ---- index_quotes (指数实时行情) ----
    def get_index_quotes(self, symbols: list[str]) -> list[dict]:
        logger.debug("智兔 index_quotes 拉取: %s", symbols)
        return self._client.fetch_index_quotes(symbols)

    # ---- financials (财务数据) ----
    def get_financials(
        self,
        table: str,
        symbols: list[str],
        latest_only: bool = True,
    ) -> pl.DataFrame:
        if not symbols:
            return pl.DataFrame()

        logger.info("智兔 financials 拉取开始: table=%s (%d symbols, latest_only=%s)", table, len(symbols), latest_only)
        all_rows: list[dict] = []

        def _fetch_stock_fin(sym: str) -> list[dict]:
            raw = self._client.fetch_financials(sym, table)
            if not raw:
                return []
            items = raw if not latest_only else raw[:1]
            rows: list[dict] = []
            for it in items:
                period_end = _clean_date_str(it.get("jzrq") or it.get("bdrq"))
                publish_date = _clean_date_str(it.get("plrq"))
                if not period_end:
                    continue

                if table == "metrics":
                    rows.append({
                        "symbol": sym,
                        "period_end": period_end,
                        "publish_date": publish_date,
                        "eps_basic": _clean_num(it.get("jbmgsy")),
                        "eps_diluted": _clean_num(it.get("xsmgsy")),
                        "bps": _clean_num(it.get("mgjzc")),
                        "ocfps": _clean_num(it.get("mgjyhdxjl")),
                        "roe": _clean_num(it.get("jzcsyl")),
                        "gross_margin": _clean_num(it.get("xsmlv")),
                        "net_margin": _clean_num(it.get("xsjll")),
                        "debt_to_asset_ratio": _clean_num(it.get("zcfzl")),
                        "revenue_yoy": _clean_num(it.get("zyyrsrzz")),
                        "net_income_yoy": _clean_num(it.get("jlrzz")),
                    })
                elif table == "income":
                    rows.append({
                        "symbol": sym,
                        "period_end": period_end,
                        "publish_date": publish_date,
                        "revenue": _clean_num(it.get("yysr")),
                        "operating_cost": _clean_num(it.get("yycb") or it.get("yyzcb")),
                        "operating_profit": _clean_num(it.get("yylr")),
                        "selling_expense": _clean_num(it.get("xsfy")),
                        "admin_expense": _clean_num(it.get("glfy")),
                        "rd_expense": _clean_num(it.get("yffy")),
                        "financial_expense": _clean_num(it.get("cwfy")),
                        "total_profit": _clean_num(it.get("lrze")),
                        "income_tax": _clean_num(it.get("sdsfy")),
                        "net_income": _clean_num(it.get("jlr")),
                        "net_income_attributable": _clean_num(it.get("gsmgsyzzdjlr") or it.get("jlr")),
                        "net_income_deducted": _clean_num(it.get("kfjlr")),
                        "basic_eps": _clean_num(it.get("jbmgsy")),
                        "diluted_eps": _clean_num(it.get("xsmgsy")),
                    })
                elif table == "balance_sheet":
                    rows.append({
                        "symbol": sym,
                        "period_end": period_end,
                        "publish_date": publish_date,
                        "total_assets": _clean_num(it.get("zczj") or it.get("zchj")),
                        "total_current_assets": _clean_num(it.get("ldzchj")),
                        "total_non_current_assets": _clean_num(it.get("fldzchj")),
                        "cash_and_equivalents": _clean_num(it.get("hbzj")),
                        "accounts_receivable": _clean_num(it.get("yszk")),
                        "inventory": _clean_num(it.get("ch")),
                        "fixed_assets": _clean_num(it.get("gdzc") or it.get("gdzchj")),
                        "intangible_assets": _clean_num(it.get("wxzc")),
                        "goodwill": _clean_num(it.get("sy")),
                        "total_liabilities": _clean_num(it.get("fzhj")),
                        "total_current_liabilities": _clean_num(it.get("ldfzhj")),
                        "total_non_current_liabilities": _clean_num(it.get("fldfzhj")),
                        "short_term_borrowing": _clean_num(it.get("dqjk")),
                        "long_term_borrowing": _clean_num(it.get("cqjk")),
                        "accounts_payable": _clean_num(it.get("yfzk")),
                        "total_equity": _clean_num(it.get("syzqyhj")),
                        "equity_attributable": _clean_num(it.get("gsmgdqsyhj") or it.get("syzqyhj")),
                        "retained_earnings": _clean_num(it.get("wfplr")),
                        "minority_interest": _clean_num(it.get("ssgdqy") or it.get("ssgdsy")),
                    })
                elif table == "cash_flow":
                    rows.append({
                        "symbol": sym,
                        "period_end": period_end,
                        "publish_date": publish_date,
                        "net_operating_cash_flow": _clean_num(it.get("jyhdxjlrxj") or it.get("jyhdyxjcje")),
                        "net_investing_cash_flow": _clean_num(it.get("tzhdxjlrxj") or it.get("tzhdyxjcje")),
                        "net_financing_cash_flow": _clean_num(it.get("czhdxjlrxj") or it.get("czhdyxjcje")),
                        "capex": _clean_num(it.get("gjgdzcwxzhqtqctzzfdxj")),
                        "net_cash_change": _clean_num(it.get("xjxjdhwjzje")),
                    })
                elif table == "shares":
                    rows.append({
                        "symbol": sym,
                        "period_end": period_end,
                        "publish_date": publish_date,
                        "total_shares": _clean_num(it.get("zgb")),
                        "float_shares": _clean_num(it.get("ysltag") or it.get("xsltgf")),
                    })
            return rows

        with ThreadPoolExecutor(max_workers=_CONCURRENCY) as executor:
            futures = [executor.submit(_fetch_stock_fin, sym) for sym in symbols]
            for fut in as_completed(futures):
                try:
                    res = fut.result()
                    if res:
                        all_rows.extend(res)
                except Exception as e:
                    logger.warning("智兔 financials 单股拉取异常: %s", e)

        if not all_rows:
            return pl.DataFrame()

        df = pl.DataFrame(all_rows)
        return df if not df.is_empty() and "symbol" in df.columns else pl.DataFrame()

    # ---- instruments (标的维表) ----
    def get_instruments(self, asset_type: str = "stock") -> list[dict]:
        """返回标的元数据。"""
        if asset_type == "index":
            items = self._client.fetch_index_list()
        else:
            items = self._client.fetch_stock_list()

        if not items:
            return []

        out: list[dict] = []
        for it in items:
            dm = it.get("dm")
            if not dm:
                continue
            symbol = to_standard_code(str(dm))
            parts = symbol.split(".")
            code = parts[0]
            ex = parts[1] if len(parts) > 1 else it.get("jys", "")
            out.append({
                "symbol": symbol,
                "name": it.get("mc") or symbol,
                "code": code,
                "exchange": ex,
                "region": "CN",
                "type": asset_type,
                "ext": {
                    "listing_date": None,
                    "total_shares": None,
                    "float_shares": None,
                    "tick_size": 0.01,
                    "limit_up": None,
                    "limit_down": None,
                },
            })
        return out

    # ---- 测试(设置页试拉) ----
    def test_dataset(self, dataset: str, symbols: list[str] | None = None) -> dict:
        symbols = symbols or ["600519.SH"]
        if dataset == "daily":
            df = self.get_daily(symbols, None, None)
            return _preview("daily", df)
        if dataset == "adj_factor":
            df = self.get_adj_factors(symbols, None, None)
            return _preview("adj_factor", df)
        if dataset == "minute":
            df = self.get_minute(symbols, None, None)
            return _preview("minute", df)
        if dataset == "financial":
            df = self.get_financials("metrics", symbols, latest_only=True)
            return _preview("financial", df)
        if dataset == "realtime":
            rows = self.get_realtime()
            head = rows[:5]
            return {
                "provider": self.name,
                "dataset": "realtime",
                "rows": len(rows),
                "columns": list(head[0].keys()) if head else [],
                "preview": head,
            }
        raise ValueError(f"智兔数服不支持数据集: {dataset}")


def _preview(dataset: str, df: pl.DataFrame) -> dict:
    return {
        "provider": "zhitu",
        "dataset": dataset,
        "rows": df.height,
        "columns": df.columns,
        "preview": df.head(5).to_dicts() if not df.is_empty() else [],
    }
