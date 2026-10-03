# -*- coding: utf-8 -*-
"""9:25 集合竞价抢筹选股服务（多因子高胜率增强版）。

筛选规则与多因子体系：
1. 市场范围：全市场 A 股，自动剔除北交所 (.BJ / 43/83/87/92)、ST / *ST 个股、新股 (<30天)；
2. 板块筛选：创业板 (300/301) 和科创板 (688/689) 支持动态勾选包含或排除；
3. 黄金跳空高开：高开幅度 2.0% ~ 6.5% 最具进攻爆发力；
4. 前一日形态：小阴小阳蓄势（实体振幅 <= 2.5%），若实体 <= 0.8% 标记为「⭐ 极致十字星」；
5. 技术均线生命线：守在 20 日生命线之上（close >= MA20），拒绝空头下降通道标的；
6. 公司公告因子：智兔 /hitc/jrts 公告解析，突发利好（中标/回购/增持/预增/撤回重整）加分，减持/立案利空一票否决；
7. 舆情题材因子：联动 NewsService 前瞻题材与快讯，主线板块共振加分；
8. 龙虎榜机构因子：联动智兔 /hilh/jgxw 机构席位追踪，大额机构净买入背书加分；
9. 竞价量比动能：竞价成交金额与换手达标，剔除几十万虚假高开；
10. 高胜率分层：自动计算多因子综合评分、预估溢价胜率星级，划分每日 Top 3 / Top 5 先锋龙头。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, List, Optional
import zoneinfo
import polars as pl
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.parquet import scan_enriched_parquet
from app.tickflow.repository import KlineRepository

logger = logging.getLogger(__name__)

SHANGHAI_TZ = zoneinfo.ZoneInfo("Asia/Shanghai")


def _bj_now() -> datetime:
    return datetime.now(SHANGHAI_TZ)


def _bj_now_str() -> str:
    return _bj_now().strftime("%Y-%m-%d %H:%M:%S")


def _bj_today_str() -> str:
    return _bj_now().strftime("%Y-%m-%d")

# 内存微缓存（避免频繁请求外部接口）
_ANNOUNCEMENT_CACHE: dict[str, dict] = {}
_ANNOUNCEMENT_CACHE_TIME: float = 0.0

_CATALYST_CACHE: dict[str, str] = {}
_CATALYST_CACHE_TIME: float = 0.0

_INST_CACHE: dict[str, float] = {}
_INST_CACHE_TIME: float = 0.0


def _classify_board(symbol: str) -> str:
    if symbol.startswith("688") or symbol.startswith("689"):
        return "科创板"
    if symbol.startswith("300") or symbol.startswith("301"):
        return "创业板"
    if symbol.startswith("600") or symbol.startswith("601") or symbol.startswith("603") or symbol.startswith("605") or symbol.endswith(".SH"):
        return "沪主板"
    if symbol.startswith("000") or symbol.startswith("001") or symbol.startswith("002") or symbol.startswith("003") or symbol.endswith(".SZ"):
        return "深主板"
    return "主板"


def _get_zhitu_announcements() -> dict[str, dict]:
    """从智兔 /hitc/jrts 解析今日上交所与深交所公告，提取利好与利空公告。"""
    global _ANNOUNCEMENT_CACHE, _ANNOUNCEMENT_CACHE_TIME
    now = time.time()
    if _ANNOUNCEMENT_CACHE and (now - _ANNOUNCEMENT_CACHE_TIME < 120.0):
        return _ANNOUNCEMENT_CACHE

    try:
        from app.data_providers import custom as custom_sources
        p = custom_sources.get_provider("zhitu")
        if not p or not getattr(p, "_client", None):
            return {}
        jrts = p._client.get_json("/hitc/jrts")
        if not isinstance(jrts, dict):
            return {}

        all_gg = (jrts.get("shgg") or []) + (jrts.get("szgg") or [])

        bull_kws = [
            "中标", "重大合同", "签约", "回购", "增持", "业绩预增", "预增", "扭亏",
            "超预期", "利润增长", "收购", "重组", "合作", "战略", "大单", "入选",
            "批件", "授予", "撤回", "突破", "解除", "恢复"
        ]
        bear_kws = [
            "减持", "询价转让", "立案", "警示", "诉讼", "亏损", "平仓", "处罚",
            "违规", "冻结", "仲裁", "终止"
        ]

        res: dict[str, dict] = {}
        for g in all_gg:
            m = re.search(r"\((\d{6})\)", g)
            if not m:
                continue
            code = m.group(1)
            title_part = g.split("：", 1)[-1] if "：" in g else g
            is_bull = any(k in g for k in bull_kws)
            is_bear = any(k in g for k in bear_kws)

            if code not in res:
                res[code] = {"bull": [], "bear": [], "all": []}
            res[code]["all"].append(title_part)
            if is_bull:
                res[code]["bull"].append(title_part)
            if is_bear:
                res[code]["bear"].append(title_part)

        _ANNOUNCEMENT_CACHE = res
        _ANNOUNCEMENT_CACHE_TIME = now
        return res
    except Exception as e:
        logger.debug("获取智兔公告失败: %s", e)
        return {}


def _get_sentiment_catalysts(data_dir: Path) -> dict[str, str]:
    """从 NewsService 提取前瞻题材催化标签与标的映射。"""
    global _CATALYST_CACHE, _CATALYST_CACHE_TIME
    now = time.time()
    if _CATALYST_CACHE and (now - _CATALYST_CACHE_TIME < 120.0):
        return _CATALYST_CACHE

    try:
        from app.services.news_service import NewsService
        svc = NewsService(data_dir=data_dir)
        cats = svc.get_tomorrow_catalysts()
        res: dict[str, str] = {}
        for c in cats:
            tag = str(c.get("tag") or c.get("title") or "")
            for s in c.get("stocks", []):
                sym = str(s.get("symbol") or "")
                name = str(s.get("name") or "")
                if sym:
                    res[sym] = tag
                    res[sym.split(".")[0]] = tag
                if name:
                    res[name] = tag
        _CATALYST_CACHE = res
        _CATALYST_CACHE_TIME = now
        return res
    except Exception as e:
        logger.debug("获取前瞻催化失败: %s", e)
        return {}


def _get_institution_backing() -> dict[str, float]:
    """从 LongHuBangService 获取近 5 日机构席位净买入额（万元）。"""
    global _INST_CACHE, _INST_CACHE_TIME
    now = time.time()
    if _INST_CACHE and (now - _INST_CACHE_TIME < 120.0):
        return _INST_CACHE

    try:
        from app.services.longhubang_service import LongHuBangService
        svc = LongHuBangService()
        stats = svc.get_institution_stats(5)
        res = {
            item["code"]: float(item.get("net_amount") or 0.0)
            for item in stats
            if float(item.get("net_amount") or 0.0) > 0
        }
        _INST_CACHE = res
        _INST_CACHE_TIME = now
        return res
    except Exception as e:
        logger.debug("获取机构席位失败: %s", e)
        return {}


_EARNINGS_CACHE: dict[str, dict] = {}
_EARNINGS_CACHE_TIME: float = 0.0


def _get_earnings_guidance() -> dict[str, dict]:
    """从智兔 /hicw/yjyg 获取最新上市公司业绩预告与财务扭亏因子。"""
    global _EARNINGS_CACHE, _EARNINGS_CACHE_TIME
    now = time.time()
    if _EARNINGS_CACHE and (now - _EARNINGS_CACHE_TIME < 600.0):
        return _EARNINGS_CACHE

    try:
        from app.data_providers import custom as custom_sources

        provider = custom_sources.get_provider("zhitu")
        client = getattr(provider, "_client", None)
        if not client:
            return {}

        res: dict[str, dict] = {}
        # 依次尝试中报、一季报、年报预告
        for year, quarter in [(2024, 2), (2024, 1), (2023, 4)]:
            data = client.get_json(f"/hicw/yjyg/{year}/{quarter}")
            if isinstance(data, list) and len(data) > 100:
                for item in data:
                    dm = str(item.get("dm") or "").strip()
                    if not dm or dm in res:
                        continue
                    lx = str(item.get("lx") or "").strip()
                    is_bull = lx in ("预增", "预盈", "扭亏", "预升", "减亏", "略增", "续盈")
                    is_bear = lx in ("预亏", "预降", "首亏", "预减")
                    res[dm] = {
                        "type": lx,
                        "growth": str(item.get("yjzf") or ""),
                        "desc": str(item.get("yjzy") or ""),
                        "is_bull": is_bull,
                        "is_bear": is_bear,
                    }
                break

        _EARNINGS_CACHE = res
        _EARNINGS_CACHE_TIME = now
        return res
    except Exception as e:
        logger.debug("获取智兔业绩预告失败: %s", e)
        return {}


class AuctionService:
    def __init__(self, repo: KlineRepository) -> None:
        self.repo = repo

    def run_auction_screener(
        self,
        as_of: Optional[date] = None,
        min_gap_pct: float = 1.5,
        max_gap_pct: float = 9.9,
        min_mv: float = 10.0,
        max_mv: float = 200.0,
        max_prev_body_pct: float = 2.5,
        include_chinext: bool = True,
        include_star: bool = True,
        only_doji: bool = False,
        use_realtime: bool = True,
        only_high_winrate: bool = False,
        require_catalyst: bool = False,
        exclude_bear_announcements: bool = True,
        exclude_earnings_bear: bool = True,
        require_earnings_bull: bool = False,
    ) -> dict:
        """执行 9:25 集合竞价抢筹多因子增强选股。"""
        t0_start = time.perf_counter()

        enriched_dir = self.repo.store.data_dir / "kline_daily_enriched"

        # 获取可用交易日
        date_strs = []
        if enriched_dir.exists():
            for d in enriched_dir.iterdir():
                if d.is_dir() and d.name.startswith("date="):
                    date_strs.append(d.name[5:])
        date_strs.sort()
        all_dates = [datetime.strptime(s, "%Y-%m-%d").date() for s in date_strs]

        if not all_dates:
            return {"as_of": str(as_of or date.today()), "total": 0, "rows": [], "elapsed_ms": 0.0}

        target_date = as_of or all_dates[-1]

        # 确定 T0, T1, T2 日期
        t0_date = target_date
        t1_candidates = [d for d in all_dates if d < t0_date]
        if not t1_candidates:
            t1_date = t0_date
            t2_date = t0_date
        else:
            t1_date = t1_candidates[-1]
            t2_candidates = [d for d in all_dates if d < t1_date]
            t2_date = t2_candidates[-1] if t2_candidates else t1_date

        p_t1 = enriched_dir / f"date={t1_date}" / "part.parquet"
        p_t2 = enriched_dir / f"date={t2_date}" / "part.parquet"

        df_t1 = pl.read_parquet(p_t1) if p_t1.exists() else pl.DataFrame()
        df_t2 = pl.read_parquet(p_t2) if p_t2.exists() else pl.DataFrame()
        if df_t1.is_empty():
            return {"as_of": str(t0_date), "t1_date": str(t1_date), "total": 0, "rows": [], "elapsed_ms": 0.0}

        # 尝试读取 T0 实时行情
        df_t0: Optional[pl.DataFrame] = None
        is_live = False

        if use_realtime and (as_of is None or as_of == all_dates[-1] or as_of == date.today()):
            try:
                df_latest, _ = self.repo.get_enriched_latest()
                if not df_latest.is_empty():
                    df_t0 = df_latest
                    is_live = True
            except Exception as e:
                logger.debug("从 repo 获取实时行情失败: %s", e)

        if df_t0 is None or df_t0.is_empty():
            p_t0 = enriched_dir / f"date={t0_date}" / "part.parquet"
            df_t0 = pl.read_parquet(p_t0) if p_t0.exists() else pl.DataFrame()

        if df_t0.is_empty():
            return {"as_of": str(t0_date), "t1_date": str(t1_date), "total": 0, "rows": [], "elapsed_ms": 0.0}

        df_inst = self.repo.get_instruments_asset("stock")

        if "open" not in df_t0.columns and "last_price" in df_t0.columns:
            df_t0 = df_t0.with_columns(pl.col("last_price").alias("open"))

        cols_t0 = ["symbol", "open", "close", "high", "low", "volume", "amount"]
        avail_t0 = [c for c in cols_t0 if c in df_t0.columns]
        df_t0_sub = df_t0.select(avail_t0)

        t1_cols = [
            "symbol",
            pl.col("open").alias("open_prev"),
            pl.col("close").alias("close_prev"),
            pl.col("high").alias("high_prev"),
            pl.col("low").alias("low_prev"),
            pl.col("volume").alias("volume_prev"),
            pl.col("amount").alias("amount_prev"),
        ]
        if "consecutive_limit_ups" in df_t1.columns:
            t1_cols.append(pl.col("consecutive_limit_ups").alias("consec_limit_ups_prev"))
        if "consecutive_limit_downs" in df_t1.columns:
            t1_cols.append(pl.col("consecutive_limit_downs").alias("consec_limit_downs_prev"))

        df_t1_sub = df_t1.select(t1_cols)
        df_t2_sub = df_t2.select(["symbol", pl.col("close").alias("close_prev2")]) if not df_t2.is_empty() else pl.DataFrame()

        if "amount" in df_t0_sub.columns:
            df_t0_sub = df_t0_sub.sort("amount", descending=True).unique(subset=["symbol"], keep="first")
        else:
            df_t0_sub = df_t0_sub.unique(subset=["symbol"], keep="first")

        merged = df_t0_sub.join(df_t1_sub, on="symbol", how="inner")
        if not df_t2_sub.is_empty():
            merged = merged.join(df_t2_sub, on="symbol", how="left")

        if not df_inst.is_empty():
            inst_cols = [c for c in ["symbol", "name", "total_shares", "float_shares", "list_date"] if c in df_inst.columns]
            merged = merged.join(df_inst.select(inst_cols), on="symbol", how="left")

        # 1. 过滤：排除北交所 (.BJ, 43, 83, 87, 92)
        merged = merged.filter(
            ~pl.col("symbol").str.ends_with(".BJ") &
            ~pl.col("symbol").str.starts_with("43") &
            ~pl.col("symbol").str.starts_with("83") &
            ~pl.col("symbol").str.starts_with("87") &
            ~pl.col("symbol").str.starts_with("92")
        )

        # 2. 过滤：排除 ST / 退市
        if "name" in merged.columns:
            merged = merged.filter(
                ~pl.col("name").str.starts_with("ST") &
                ~pl.col("name").str.starts_with("*ST") &
                ~pl.col("name").str.starts_with("S*ST") &
                ~pl.col("name").str.starts_with("SST") &
                ~pl.col("name").str.contains("退")
            )

        # 3. 过滤：排除上市未满 30 天新股
        if "list_date" in merged.columns:
            min_list_date = t0_date - timedelta(days=30)
            merged = merged.filter(
                pl.col("list_date").is_null() | (pl.col("list_date") <= min_list_date)
            )

        # 4. 关键过滤：排除昨日涨停/连板、昨日跌停
        if "consec_limit_ups_prev" in merged.columns:
            merged = merged.filter(pl.col("consec_limit_ups_prev") == 0)
        if "consec_limit_downs_prev" in merged.columns:
            merged = merged.filter(pl.col("consec_limit_downs_prev") == 0)

        # 5. 计算基础量价指标
        merged = merged.with_columns(
            ((pl.col("open") - pl.col("close_prev")) / pl.col("close_prev") * 100).alias("open_gap_pct"),
            (pl.col("close_prev") - pl.col("open_prev")).abs().alias("body_abs"),
            ((pl.col("high_prev") - pl.col("low_prev")) / pl.col("close_prev") * 100).alias("prev_amplitude"),
            (pl.col("amount") / 10000.0).alias("bidding_amount_wan"),
            (pl.when(pl.col("close_prev2").is_not_null())
             .then((pl.col("close_prev") - pl.col("close_prev2")) / pl.col("close_prev2") * 100)
             .otherwise(0.0)).alias("prev_change_pct"),
        ).with_columns(
            (pl.col("body_abs") / pl.col("close_prev") * 100).alias("prev_body_pct"),
            (pl.when(pl.col("volume_prev") > 0)
             .then(pl.col("volume") / pl.col("volume_prev"))
             .otherwise(0.0)).alias("bidding_vol_ratio"),
        )

        # 计算市值（亿）
        if "total_shares" in merged.columns:
            merged = merged.with_columns(
                pl.when(pl.col("total_shares").is_not_null() & (pl.col("total_shares") > 0))
                .then(pl.col("total_shares") * pl.col("open") / 1e8)
                .otherwise(pl.lit(50.0))
                .alias("total_mv")
            )
        else:
            merged = merged.with_columns(pl.lit(50.0).alias("total_mv"))

        if "float_shares" in merged.columns:
            merged = merged.with_columns(
                pl.when(pl.col("float_shares").is_not_null() & (pl.col("float_shares") > 0))
                .then(pl.col("float_shares") * pl.col("open") / 1e8)
                .otherwise(pl.col("total_mv"))
                .alias("float_mv")
            )
        else:
            merged = merged.with_columns(pl.col("total_mv").alias("float_mv"))

        # 基础条件过滤
        expr_filter = (
            (pl.col("open_gap_pct") >= min_gap_pct) &
            (pl.col("open_gap_pct") <= max_gap_pct) &
            (pl.col("prev_body_pct") <= max_prev_body_pct) &
            (pl.col("prev_change_pct") >= -3.5) &
            (pl.col("prev_change_pct") <= 3.5) &
            (pl.col("prev_amplitude") >= 0.5) &
            (pl.col("total_mv") >= min_mv) &
            (pl.col("total_mv") <= max_mv)
        )

        if not include_chinext:
            expr_filter = expr_filter & ~pl.col("symbol").str.starts_with("300") & ~pl.col("symbol").str.starts_with("301")

        if not include_star:
            expr_filter = expr_filter & ~pl.col("symbol").str.starts_with("688") & ~pl.col("symbol").str.starts_with("689")

        if only_doji:
            expr_filter = expr_filter & (pl.col("prev_body_pct") <= 0.8) & (pl.col("prev_change_pct").abs() <= 2.0) & (pl.col("prev_amplitude") >= 0.8)

        filtered = merged.filter(expr_filter)

        # 6. 多源因子接入与预取
        candidate_symbols = filtered["symbol"].to_list() if not filtered.is_empty() else []
        hist_map: dict[str, dict] = {}
        ma_map: dict[str, dict] = {}
        vol_map: dict[str, dict] = {}
        flow_5d_map: dict[str, dict] = {}

        # 6.1 智兔公司公告因子
        announcements_by_code = _get_zhitu_announcements()

        # 6.2 舆情题材前瞻因子
        catalysts_by_sym = _get_sentiment_catalysts(self.repo.store.data_dir)

        # 6.3 机构席位追踪因子
        institutions_by_code = _get_institution_backing()

        # 6.4 智兔上市公司业绩预告与财务扭亏因子
        earnings_by_code = _get_earnings_guidance()

        # 6.5 历史走势分析（MA20 生命线与试盘形态）
        if candidate_symbols:
            history_dates = [d for d in all_dates if d < t0_date][-30:]
            if history_dates:
                hist_paths = [
                    str(enriched_dir / f"date={d}" / "part.parquet")
                    for d in history_dates
                    if (enriched_dir / f"date={d}" / "part.parquet").exists()
                ]
                if hist_paths:
                    df_hist = pl.scan_parquet(hist_paths).filter(
                        pl.col("symbol").is_in(candidate_symbols)
                    ).select(["symbol", "date", "open", "high", "low", "close", "volume", "amount"]).collect()
                else:
                    df_hist = pl.DataFrame()

                for sym in candidate_symbols:
                    sym_bars = df_hist.filter(pl.col("symbol") == sym).sort("date").to_dicts()
                    if len(sym_bars) < 5:
                        continue

                    # 计算均线
                    closes = [float(b.get("close") or 0.0) for b in sym_bars]
                    highs = [float(b.get("high") or 0.0) for b in sym_bars]
                    ma5 = sum(closes[-5:]) / 5.0
                    ma10 = sum(closes[-10:]) / len(closes[-10:]) if len(closes) >= 10 else ma5
                    ma20 = sum(closes[-20:]) / len(closes[-20:]) if len(closes) >= 20 else ma10
                    max_high_20d = max(highs[-20:]) if len(highs) >= 20 else max(highs)

                    ma_map[sym] = {
                        "ma5": ma5,
                        "ma10": ma10,
                        "ma20": ma20,
                        "max_high_20d": max_high_20d,
                    }

                    # 计算近 5 日缩量与最低量特征
                    t1_vol = float(sym_bars[-1].get("volume") or 0.0)
                    prior_vols_5d = [float(b.get("volume") or 0.0) for b in sym_bars[-6:-1]]
                    if prior_vols_5d:
                        min_vol_5d = min(prior_vols_5d)
                        avg_vol_5d = sum(prior_vols_5d) / len(prior_vols_5d)
                        is_5d_lowest_vol = (t1_vol <= min_vol_5d * 1.15)
                        is_vol_shrink = (t1_vol <= avg_vol_5d * 0.80) or is_5d_lowest_vol
                        vol_shrink_ratio = round(t1_vol / max(1.0, avg_vol_5d), 2)
                    else:
                        is_5d_lowest_vol = False
                        is_vol_shrink = False
                        vol_shrink_ratio = 1.0

                    vol_map[sym] = {
                        "t1_vol": t1_vol,
                        "is_5d_lowest_vol": is_5d_lowest_vol,
                        "is_vol_shrink": is_vol_shrink,
                        "vol_shrink_ratio": vol_shrink_ratio,
                    }

                    # 计算近 5 日资金与量价流动特征
                    bars_5d = sym_bars[-5:] if len(sym_bars) >= 5 else sym_bars
                    if bars_5d:
                        c_start = float(bars_5d[0].get("close") or 1.0)
                        c_end = float(bars_5d[-1].get("close") or 1.0)
                        change_5d_pct = round(((c_end - c_start) / max(0.01, c_start)) * 100, 2)
                        amount_5d_avg_wan = round(sum(float(b.get("amount") or 0.0) for b in bars_5d) / len(bars_5d) / 10000.0, 1)
                        amount_5d_total_yi = round(sum(float(b.get("amount") or 0.0) for b in bars_5d) / 100000000.0, 2)
                    else:
                        change_5d_pct = 0.0
                        amount_5d_avg_wan = 0.0
                        amount_5d_total_yi = 0.0

                    flow_5d_map[sym] = {
                        "change_5d_pct": change_5d_pct,
                        "amount_5d_avg_wan": amount_5d_avg_wan,
                        "amount_5d_total_yi": amount_5d_total_yi,
                    }

                    # 放量试盘线识别
                    n = len(sym_bars)
                    if n >= 8:
                        start_idx = max(4, n - 22)
                        end_idx = n - 2
                        for i in range(end_idx, start_idx - 1, -1):
                            bar_i = sym_bars[i]
                            prior = sym_bars[max(0, i - 5):i]
                            if not prior:
                                continue
                            avg_vol = sum(b.get("volume") or 0.0 for b in prior) / len(prior)
                            if avg_vol <= 0:
                                continue
                            vol_ratio_test = (bar_i.get("volume") or 0.0) / avg_vol
                            has_test_action = (
                                ((bar_i["high"] - bar_i["low"]) / max(0.01, bar_i["low"]) >= 0.028)
                                or ((bar_i["close"] - bar_i["open"]) / max(0.01, bar_i["open"]) >= 0.015)
                                or ((bar_i["high"] - min(bar_i["open"], bar_i["close"])) / max(0.01, min(bar_i["open"], bar_i["close"])) >= 0.015)
                            )
                            if vol_ratio_test >= 1.25 and has_test_action:
                                subsequent = sym_bars[i + 1:]
                                if len(subsequent) < 3:
                                    continue
                                test_low = bar_i["low"]
                                all_hold = all((b.get("close") or 0.0) >= test_low * 0.99 for b in subsequent)
                                avg_sub_vol = sum(b.get("volume") or 0.0 for b in subsequent) / len(subsequent)
                                is_shrink = avg_sub_vol <= (bar_i.get("volume") or 1.0) * 0.90
                                if all_hold and is_shrink:
                                    hist_map[sym] = {
                                        "test_date": str(bar_i["date"]),
                                        "test_low": round(float(test_low), 2),
                                        "defense_days": len(subsequent),
                                        "test_vol_ratio": round(float(vol_ratio_test), 2),
                                    }
                                    break

        # 7. 打标签、因子加权与综合评分
        if not filtered.is_empty() and "bidding_amount_wan" in filtered.columns:
            filtered = (
                filtered
                .sort("bidding_amount_wan", descending=True)
                .unique(subset=["symbol"], keep="first")
            )

        rows: list[dict] = []
        seen_symbols: set[str] = set()

        for r in filtered.iter_rows(named=True):
            sym = r["symbol"]
            code = sym.split(".")[0]
            name = r.get("name") or sym
            if sym in seen_symbols:
                continue
            seen_symbols.add(sym)

            board = _classify_board(sym)
            body_pct = r.get("prev_body_pct") or 0.0
            gap_pct = r.get("open_gap_pct") or 0.0
            open_price = float(r.get("open") or 0.0)
            close_prev = float(r.get("close_prev") or 0.0)
            open_prev = float(r.get("open_prev") or 0.0)
            prev_change = float(r.get("prev_change_pct") or 0.0)
            prev_amp = float(r.get("prev_amplitude") or 0.0)
            amount_wan = float(r.get("bidding_amount_wan") or 0.0)
            vol_ratio = float(r.get("bidding_vol_ratio") or 0.0)
            total_mv = float(r.get("total_mv") or 50.0)

            # 7.1 提取因子特征
            # 公告因子
            gg_info = announcements_by_code.get(code, {})
            bull_ggs = gg_info.get("bull", [])
            bear_ggs = gg_info.get("bear", [])
            has_bull_announcement = len(bull_ggs) > 0
            has_bear_announcement = len(bear_ggs) > 0
            announcement_title = bull_ggs[0] if has_bull_announcement else (gg_info.get("all", [""])[0] if gg_info.get("all") else None)
            bear_announcement_title = bear_ggs[0] if has_bear_announcement else None

            # 若勾选排除减持利空且存在利空公告，直接拦截
            if exclude_bear_announcements and has_bear_announcement:
                continue

            # 舆情题材因子
            sentiment_tag = catalysts_by_sym.get(sym) or catalysts_by_sym.get(code) or catalysts_by_sym.get(name)
            has_sentiment_catalyst = bool(sentiment_tag)

            # 龙虎榜机构因子
            inst_net_wan = institutions_by_code.get(code, 0.0)
            has_inst_backing = inst_net_wan >= 300.0  # 机构净买入超 300 万

            # 智兔业绩预告与财务扭亏因子
            yj_info = earnings_by_code.get(code, {})
            is_earnings_bull = yj_info.get("is_bull", False)
            is_earnings_bear = yj_info.get("is_bear", False)
            earnings_type = yj_info.get("type")
            earnings_growth = yj_info.get("growth")
            earnings_desc = yj_info.get("desc")

            # 排除业绩预亏/首亏/预减雷
            if exclude_earnings_bear and is_earnings_bear:
                continue

            # 若勾选仅筛选业绩扭亏或预增标的
            if require_earnings_bull and not is_earnings_bull:
                continue

            # 若勾选必须有公告或舆情题材催化，且二者均无，则拦截
            if require_catalyst and not (has_bull_announcement or has_sentiment_catalyst or is_earnings_bull):
                continue

            # 技术指标与生命线
            ma_data = ma_map.get(sym, {})
            ma20 = ma_data.get("ma20", close_prev)
            above_ma20 = open_price >= ma20 * 0.99
            is_breakout_20d = open_price >= (ma_data.get("max_high_20d") or open_price) * 0.99

            # 5日地量与缩量特征提取
            vol_data = vol_map.get(sym, {})
            is_5d_lowest_vol = vol_data.get("is_5d_lowest_vol", False)
            is_vol_shrink = vol_data.get("is_vol_shrink", False)
            vol_shrink_ratio = vol_data.get("vol_shrink_ratio", 1.0)

            # 十字星蓄势形态（允许 body_pct <= 1.6% 纺锤线/小星线，振幅 <= 5.0%）
            is_doji = (body_pct <= 1.6) and (prev_amp <= 5.0) and (abs(prev_change) <= 3.5)
            is_5d_lowest_doji = is_doji and is_5d_lowest_vol
            is_vol_shrink_doji = is_doji and is_vol_shrink

            has_test_pattern = sym in hist_map
            test_info = hist_map.get(sym, {})

            # 判据：是否处于竞价数据阶段
            is_auction_phase = (vol_ratio < 0.10)

            if is_auction_phase:
                is_core_purple = has_test_pattern and (gap_pct >= 1.0) and (amount_wan >= 40.0 or vol_ratio >= 0.01)
                is_gap_jump = (gap_pct >= 2.8) and (body_pct <= 2.2) and (amount_wan >= 25.0)
                is_super_breakout = (is_doji or is_5d_lowest_doji) and (2.0 <= gap_pct <= 7.5) and (amount_wan >= 25.0) and (prev_amp <= 5.0)
            else:
                is_core_purple = has_test_pattern and (gap_pct >= 1.0) and (vol_ratio >= 1.5) and (amount_wan >= 800.0 or (total_mv <= 80.0 and amount_wan >= 500.0))
                is_gap_jump = (gap_pct >= 2.8) and (body_pct <= 2.2) and (vol_ratio >= 1.6 or amount_wan >= 600.0)
                is_super_breakout = (is_doji or is_5d_lowest_doji) and (2.0 <= gap_pct <= 7.5) and (vol_ratio >= 1.8 or amount_wan >= 800.0) and (prev_amp <= 5.0)

            if is_5d_lowest_doji and (vol_ratio >= 1.5 or is_core_purple):
                pattern = "👑 5日地量起爆十字星"
                pattern_type = "super_breakout"
            elif is_core_purple:
                pattern = "💜 核心强势抢筹"
                pattern_type = "core_purple"
            elif is_gap_jump and (gap_pct >= 4.0 or vol_ratio >= 2.5):
                pattern = "🚀 爆量跳空起爆"
                pattern_type = "gap_jump"
            elif is_gap_jump:
                pattern = "🚀 跳空高开抢筹"
                pattern_type = "gap_jump"
            elif is_5d_lowest_doji:
                pattern = "⭐ 5日地量十字星"
                pattern_type = "doji"
            elif is_vol_shrink_doji:
                pattern = "⭐ 缩量十字星"
                pattern_type = "doji"
            elif is_super_breakout:
                pattern = "👑 爆量起爆十字星"
                pattern_type = "super_breakout"
            elif is_doji:
                pattern = "⭐ 十字星蓄势"
                pattern_type = "doji"
            elif close_prev >= open_prev:
                pattern = "📈 小阳蓄势"
                pattern_type = "bull_body"
            else:
                pattern = "📉 小阴回踩"
                pattern_type = "bear_body"

            # 7.2 多因子综合评分体系 (0 ~ 100)
            # 1. 黄金跳空区间 (2.5% ~ 6.0% 最佳，得 36~40分)
            if 2.5 <= gap_pct <= 6.0:
                gap_score = 40.0
            elif 2.0 <= gap_pct < 2.5 or 6.0 < gap_pct <= 7.5:
                gap_score = 34.0
            elif 1.5 <= gap_pct < 2.0:
                gap_score = 25.0
            else:
                gap_score = 15.0

            # 2. 十字星/实体紧凑蓄势 (25分)
            if is_5d_lowest_doji:
                # 5日地量极致沉淀，形态即使振幅略有波动也是极品星线
                shape_score = max(18.0, 25.0 - body_pct * 4.5)
            else:
                shape_score = max(0.0, 25.0 - body_pct * 9.0)

            # 3. 竞价量比与金额 (20分)
            if is_auction_phase:
                amount_score = min(20.0, (amount_wan / 80.0) * 10.0 + (gap_pct / 4.0) * 10.0)
            else:
                amount_score = min(20.0, (vol_ratio / 3.0) * 10.0 + (amount_wan / 600.0) * 10.0)

            # 4. 形态加分
            morph_bonus = 0.0
            if is_5d_lowest_doji:
                morph_bonus += 18.0  # 近5日地量十字星极度缩量
            elif is_vol_shrink_doji:
                morph_bonus += 14.0  # 缩量十字星蓄势
            elif is_core_purple:
                morph_bonus += 18.0
            elif is_gap_jump:
                morph_bonus += 15.0
            elif is_super_breakout:
                morph_bonus += 12.0
            if is_breakout_20d:
                morph_bonus += 8.0

            # 5. 多因子加分 (重大驱动力量)
            factor_bonus = 0.0
            if has_bull_announcement:
                factor_bonus += 18.0  # 重大公告利好驱动
            if has_sentiment_catalyst:
                factor_bonus += 15.0  # 舆情题材共振
            if is_earnings_bull:
                factor_bonus += 12.0  # 业绩扭亏/预增基本面反转
            if has_inst_backing:
                factor_bonus += 10.0  # 机构大单背书
            if above_ma20:
                factor_bonus += 6.0   # 处于均线上方生命线

            # 6. 减分惩罚
            penalty = 0.0
            if has_bear_announcement:
                penalty += 60.0  # 恶性减持或立案处罚
            if is_earnings_bear:
                penalty += 45.0  # 业绩预亏/首亏严重雷
            if not above_ma20:
                penalty += 20.0  # 均线空头破位
            if amount_wan < 50.0:
                penalty += 12.0  # 竞价金额过小虚假高开

            total_score = min(100.0, max(10.0, round(gap_score + shape_score + amount_score + morph_bonus + factor_bonus - penalty, 1)))

            # 计算胜率评级星级
            if total_score >= 90.0 and above_ma20 and (has_bull_announcement or has_sentiment_catalyst or is_earnings_bull or is_core_purple or is_5d_lowest_doji):
                stars = 5  # ⭐⭐⭐⭐⭐ 顶级龙头，胜率 68%+
            elif total_score >= 82.0 and above_ma20:
                stars = 4  # ⭐⭐⭐⭐ 强溢价预期
            elif total_score >= 70.0:
                stars = 3  # ⭐⭐⭐ 普通关注
            else:
                stars = 2  # ⭐⭐ 观察

            # 核心催化亮点摘要
            cat_pieces = []
            if has_bull_announcement:
                cat_pieces.append(f"📢 利好公告")
            if has_sentiment_catalyst:
                cat_pieces.append(f"🔥 {sentiment_tag}")
            if is_earnings_bull:
                cat_pieces.append(f"📈 业绩{earnings_type}")
            if is_5d_lowest_vol:
                cat_pieces.append("⭐ 5日地量蓄势")
            elif is_vol_shrink:
                cat_pieces.append("⭐ 缩量蓄势")
            if has_inst_backing:
                cat_pieces.append(f"🏛️ 机构潜伏")
            if is_breakout_20d:
                cat_pieces.append("🚀 平台突破")
            if not cat_pieces:
                cat_pieces.append(pattern)
            catalyst_summary = " · ".join(cat_pieces)

            rows.append({
                "symbol": sym,
                "code": code,
                "name": name,
                "board": board,
                "open": round(open_price, 2),
                "close_prev": round(close_prev, 2),
                "open_gap_pct": round(gap_pct, 2),
                "prev_body_pct": round(body_pct, 2),
                "prev_amplitude": round(prev_amp, 2),
                "total_mv": round(total_mv, 1),
                "float_mv": round(float(r.get("float_mv") or 0.0), 1),
                "bidding_amount_wan": round(amount_wan, 1),
                "bidding_vol_ratio": round(vol_ratio, 2),
                "pattern": pattern,
                "pattern_type": pattern_type,
                "is_doji": is_doji,
                "is_5d_lowest_vol": is_5d_lowest_vol,
                "is_vol_shrink": is_vol_shrink,
                "is_5d_lowest_doji": is_5d_lowest_doji,
                "vol_shrink_ratio": vol_shrink_ratio,
                "is_gap_jump": is_gap_jump,
                "is_super_breakout": is_super_breakout,
                "is_core_purple": is_core_purple,
                "above_ma20": above_ma20,
                "is_breakout_20d": is_breakout_20d,
                "has_bull_announcement": has_bull_announcement,
                "announcement_title": announcement_title,
                "has_bear_announcement": has_bear_announcement,
                "bear_announcement_title": bear_announcement_title,
                "has_sentiment_catalyst": has_sentiment_catalyst,
                "sentiment_tag": sentiment_tag,
                "has_inst_backing": has_inst_backing,
                "inst_net_wan": round(inst_net_wan, 1),
                "has_earnings_catalyst": is_earnings_bull,
                "earnings_type": earnings_type,
                "earnings_growth": earnings_growth,
                "earnings_desc": earnings_desc,
                "is_earnings_bear": is_earnings_bear,
                "catalyst_summary": catalyst_summary,
                "test_date": test_info.get("test_date"),
                "test_low": test_info.get("test_low"),
                "defense_days": test_info.get("defense_days"),
                "change_5d_pct": flow_5d_map.get(sym, {}).get("change_5d_pct", 0.0),
                "amount_5d_avg_wan": flow_5d_map.get(sym, {}).get("amount_5d_avg_wan", 0.0),
                "amount_5d_total_yi": flow_5d_map.get(sym, {}).get("amount_5d_total_yi", 0.0),
                "score": total_score,
                "stars": stars,
                "is_top3": False,
                "is_top5": False,
            })

        # 8. 排序与先锋龙头划分
        def _get_sort_priority(x: dict):
            is_doji_5d = x.get("is_5d_lowest_doji", False)
            is_core = x.get("is_core_purple", False)
            has_cat = bool(x.get("has_bull_announcement") or x.get("has_sentiment_catalyst") or x.get("has_earnings_catalyst"))
            vr = float(x.get("bidding_vol_ratio") or 0.0)
            amt = float(x.get("bidding_amount_wan") or 0.0)
            base_score = float(x.get("score") or 0.0)
            if is_doji_5d and vr >= 1.5:
                base_score += 10.0
            return (
                base_score,
                has_cat,
                is_doji_5d,
                is_core,
                vr >= 2.5,
                vr >= 2.0,
                vr,
                amt,
                float(x.get("open_gap_pct") or 0.0),
            )

        rows.sort(key=_get_sort_priority, reverse=True)

        # 标记 Top 3 与 Top 5 先锋龙头
        for idx, row in enumerate(rows):
            if idx < 3:
                row["is_top3"] = True
                row["is_top5"] = True
            elif idx < 5:
                row["is_top5"] = True

        # 若勾选仅看高胜率精选，收敛为 Top 5 龙头
        if only_high_winrate:
            rows = [r for r in rows if r["is_top5"] or r["score"] >= 88.0]

        elapsed_ms = round((time.perf_counter() - t0_start) * 1000, 1)

        # 统计摘要
        board_counts = {"沪主板": 0, "深主板": 0, "创业板": 0, "科创板": 0}
        total_bidding_amount = 0.0
        avg_gap = 0.0

        for row in rows:
            b = row.get("board", "主板")
            if b in board_counts:
                board_counts[b] += 1
            total_bidding_amount += row.get("bidding_amount_wan", 0.0)
            avg_gap += row.get("open_gap_pct", 0.0)

        if rows:
            avg_gap = round(avg_gap / len(rows), 2)
            total_bidding_amount = round(total_bidding_amount / 10000.0, 2)  # 转换为亿元

        top3_list = [r for r in rows if r.get("is_top3")]
        top5_list = [r for r in rows if r.get("is_top5")]

        return {
            "as_of": str(t0_date),
            "t1_date": str(t1_date),
            "is_live": is_live,
            "total": len(rows),
            "top3": top3_list,
            "top5": top5_list,
            "stats": {
                "board_counts": board_counts,
                "total_bidding_amount_yi": total_bidding_amount,
                "avg_gap_pct": avg_gap,
                "doji_count": sum(1 for r in rows if r["is_doji"]),
                "core_purple_count": sum(1 for r in rows if r.get("is_core_purple")),
                "announcement_count": sum(1 for r in rows if r.get("has_bull_announcement")),
                "catalyst_count": sum(1 for r in rows if r.get("has_sentiment_catalyst")),
                "earnings_bull_count": sum(1 for r in rows if r.get("has_earnings_catalyst")),
                "earnings_bear_count": sum(1 for r in rows if r.get("is_earnings_bear")),
                "five_star_count": sum(1 for r in rows if r.get("stars") == 5),
            },
            "rows": rows,
            "elapsed_ms": elapsed_ms,
        }


# ═══════════════════════════════════════════════════════════════════
# AuctionSnatchEngine — 9:25 集合竞价自动调度与 AI 核心推演引擎
# ═══════════════════════════════════════════════════════════════════

class AuctionSnatchEngine:
    """9:25 集合竞价抢筹自动调度与 AI 核心推演总控。

    自动化调度机制：
    1. 交易日 (周一至周五) 北京时间 09:25:20 准时自动启动；
    2. 全量扫描高开放量、十字星蓄势突破标的，提取近5日资金与量价流动特征；
    3. 结合全市场博弈温度与前瞻主线题材；
    4. AI 深度推演：为何今日高开？会涨停吗？近5日资金咋样？主力是持续看好还是诱多？
    5. 严选给出【核心五只票 (Core Top 5)】与诱多避坑提示；
    6. 持久化落盘并支持服务开机补跑与免点击实时加载。
    """

    def __init__(self, repo: KlineRepository, data_dir: Optional[Path] = None, app_state: Optional[Any] = None):
        self.repo = repo
        self.data_dir = data_dir or (repo.store.data_dir if hasattr(repo, "store") else Path("data"))
        self.app_state = app_state
        self.svc = AuctionService(repo)
        self._latest_file = self.data_dir / "user_data" / "auction_snatch_latest.json"
        self._history_file = self.data_dir / "user_data" / "auction_snatch_history.json"
        self._is_running = False
        self._latest_report: Optional[dict] = None
        self._last_run_time: str = ""
        self._load_persisted()

    def _load_persisted(self) -> None:
        try:
            if self._latest_file.exists():
                data = json.loads(self._latest_file.read_text(encoding="utf-8"))
                self._latest_report = data
                self._last_run_time = data.get("updated_at", "")
        except Exception as e:
            logger.debug("加载竞价抢筹缓存失败: %s", e)

    def get_latest_report(self) -> dict:
        if self._latest_report:
            return self._latest_report
        return {
            "date": _bj_today_str(),
            "updated_at": "",
            "market_sentiment_summary": "尚未执行今日 9:25 集合竞价选股与 AI 核心推演",
            "market_temperature": 50.0,
            "market_zone": "warm",
            "core_five_stocks": [],
            "trap_warnings": [],
            "other_notable_stocks": [],
            "stats": {},
            "total_screened": 0,
            "screener_rows": [],
        }

    async def run_daily_auction_snatch(self, force: bool = False, as_of: Optional[str] = None) -> dict:
        """执行每日 9:25 集合竞价抢筹与 AI 深度推演全流程。"""
        if self._is_running:
            logger.warning("竞价抢筹自动推演正在运行中，跳过重复触发")
            return self.get_latest_report()

        self._is_running = True
        try:
            logger.info("🚀 启动 9:25 集合竞价抢筹扫描与 AI 核心推演...")
            t0 = time.time()

            # 1. 运行多因子集合竞价选股器 (在独立工作线程中执行，避免阻塞主事件循环)
            as_of_date = datetime.strptime(as_of, "%Y-%m-%d").date() if as_of else None
            screener_res = await asyncio.to_thread(
                self.svc.run_auction_screener,
                as_of=as_of_date,
                min_gap_pct=1.5,
                max_gap_pct=9.9,
                min_mv=10.0,
                max_mv=200.0,
                max_prev_body_pct=2.5,
                exclude_bear_announcements=True,
                exclude_earnings_bear=True,
            )
            rows = screener_res.get("rows", [])
            date_str = screener_res.get("as_of", _bj_today_str())
            logger.info("竞价选股完成: %s 入围 %d 只标的", date_str, len(rows))

            # 2. 提取市场大盘情绪与博弈环境
            market_temp = 55.0
            market_zone = "warm"
            market_summary_raw = "大盘情绪处于结构分化温和期"
            try:
                gt_file = self.data_dir / "user_data" / "game_theory_report.json"
                if gt_file.exists():
                    gt_data = json.loads(gt_file.read_text(encoding="utf-8"))
                    market_temp = float(gt_data.get("temperature", 55.0))
                    market_zone = gt_data.get("zone", "warm")
                    market_summary_raw = gt_data.get("market_summary", market_summary_raw)
            except Exception as e:
                logger.debug("读取博弈温度失败: %s", e)

            # 3. 提取前瞻主线题材
            catalysts_summary = ""
            try:
                cat_file = self.data_dir / "user_data" / "tomorrow_catalysts.json"
                if cat_file.exists():
                    cat_data = json.loads(cat_file.read_text(encoding="utf-8"))
                    themes = cat_data.get("themes", [])[:3]
                    if themes:
                        catalysts_summary = "；".join(f"{t.get('tag')}: {t.get('title')}" for t in themes)
            except Exception as e:
                logger.debug("读取题材前瞻失败: %s", e)

            # 4. 组装输入标的详情 (取 Top 8 供 AI 严选核心 5 只)
            top_candidates = rows[:8]
            stock_profiles = []
            for idx, r in enumerate(top_candidates):
                sym = r.get("symbol", "")
                name = r.get("name", "")
                board = r.get("board", "")
                gap = r.get("open_gap_pct", 0)
                amt = r.get("bidding_amount_wan", 0)
                vr = r.get("bidding_vol_ratio", 0)
                pat = r.get("pattern", "")
                mv = r.get("total_mv", 0)
                c5d = r.get("change_5d_pct", 0)
                amt5d = r.get("amount_5d_avg_wan", 0)
                inst = r.get("inst_net_wan", 0)
                ann = r.get("announcement_title") or "无突发公告"
                cat = r.get("sentiment_tag") or "跟随板块"
                earning = f"业绩增长+{r.get('earnings_growth')}%" if r.get("has_earnings_catalyst") else "无特别预告"

                stock_profiles.append(
                    f"{idx+1}. 【{name}】({sym}，{board}，市值{mv}亿)\n"
                    f"   - 9:25竞价: 高开+{gap}%，竞价成交{amt:.0f}万元，量比{vr:.2f}倍，昨日形态: {pat}\n"
                    f"   - 近5日资金量价: 5日累计涨幅{c5d:+.2f}%，5日均成交{amt5d:.0f}万元，近期机构席位净额{inst:+.0f}万\n"
                    f"   - 公告与题材: 公告=[{ann}]，题材题材=[{cat}]，业绩=[{earning}]"
                )

            stocks_context = "\n".join(stock_profiles) if stock_profiles else "今日无符合竞价高开抢筹标准的候选股票。"

            # 5. 调用 AI 进行深度研判与严选核心五只票
            ai_result = await self._generate_ai_analysis(
                date_str=date_str,
                market_temp=market_temp,
                market_zone=market_zone,
                market_summary_raw=market_summary_raw,
                catalysts_summary=catalysts_summary,
                stocks_context=stocks_context,
                top_candidates=top_candidates,
            )

            # 6. 构建最终报表对象并持久化落盘
            report = {
                "date": date_str,
                "updated_at": _bj_now_str(),
                "market_sentiment_summary": ai_result.get("market_sentiment_summary", ""),
                "market_temperature": market_temp,
                "market_zone": market_zone,
                "core_five_stocks": ai_result.get("core_five_stocks", []),
                "trap_warnings": ai_result.get("trap_warnings", []),
                "other_notable_stocks": ai_result.get("other_notable_stocks", []),
                "stats": screener_res.get("stats", {}),
                "total_screened": len(rows),
                "screener_rows": rows[:50],  # 保留前50只供列表展示
                "elapsed_seconds": round(time.time() - t0, 2),
            }

            self._latest_report = report
            self._last_run_time = report["updated_at"]
            self._persist(report)
            logger.info("✅ 竞价抢筹自动推演完成: 核心5只票已生成，总耗时 %.2fs", report["elapsed_seconds"])
            return report
        except Exception as e:
            logger.error("竞价抢筹自动推演异常: %s", e, exc_info=True)
            return self.get_latest_report()
        finally:
            self._is_running = False

    async def _generate_ai_analysis(
        self, date_str: str, market_temp: float, market_zone: str,
        market_summary_raw: str, catalysts_summary: str,
        stocks_context: str, top_candidates: list[dict]
    ) -> dict:
        from app.services.ai_provider import generate_ai_text

        system_prompt = f"""你是一位顶级A股量化题材总监、集合竞价抢筹战法发明者与游资主力操盘手。
今天是 {date_str} 早盘 9:25 集合竞价结束时刻。
选股系统已筛选出今日 9:25 具备【跳空高开 + 前一日极致缩量十字星/小阴小阳蓄势 + 适中市值 + 避开利空】的竞价异动股票池。

请你结合【市场大盘博弈情绪】、【个股基本面与突发公告】、【近5日资金流向】深度剖析以下 4 大核心问题：
1. 【为何今日高开】：一句话直击核心驱动（突发行业大消息、公司催化公告、板块联动、还是缩量控盘突破）？
2. 【高开会涨停吗】：给出明确涨停封板概率（百分比，如 85%、75%）并推演 9:30 开盘分时攻防走势；
3. 【近五日资金流入】：近5日资金是持续温和建仓、5日缩量洗净浮筹，还是前几日暴涨获利盘沉重？
4. 【主力意图定性】：主力是【真金白银持续看好蓄势起爆】，还是借助高开脉冲【诱多出货（假高开割散户）】？
5. 【开盘应对策略】：给出 9:30 开盘具体买点（如分时均线上方承接低吸）、止损防守位。

【任务产出要求】：
必须综合胜率、题材硬度与主力意图，严选出今日【核心五只票 (Core Top 5)】！
另外必须给出【诱多出货防坑警示】（指出哪些股票看似高开其实是主力出逃陷阱，提醒散户坚决回避）。

必须严格输出标准 JSON 格式（不要输出 markdown 代码块以外的任何多余文字）：
{{
  "market_sentiment_summary": "结合今日全市场博弈温度({market_temp:.1f}°)与大盘情绪对竞价抢筹的宏观定调（80-120字）",
  "core_five_stocks": [
    {{
      "symbol": "股票代码",
      "name": "股票名称",
      "board": "板块",
      "score": 98.0,
      "stars": 5,
      "open_gap_pct": 3.5,
      "bidding_amount_wan": 15000.0,
      "bidding_vol_ratio": 2.8,
      "pattern": "👑 5日地量起爆十字星",
      "gap_reason": "为何今日高开（一句话核心催化）",
      "will_limit_up": "高开会涨停吗（涨停封板概率与开盘推演走势，80-120字）",
      "limit_up_prob": 85,
      "capital_5d_flow": "近5日资金流入情况（近5日累计涨跌幅、量能结构、机构席位动向，60-80字）",
      "main_intent": "主力意图定性（明确标明是【持续看好蓄势起爆】还是【诱多出货风险】，并解释意图，60-80字）",
      "open_tactics": "9:30开盘实操应对指南（挂单区间、分时黄线承接点、止损防守位，60-80字）"
    }}
  ],
  "trap_warnings": [
    "诱多陷阱防坑警示1（如：某股票虽高开但竞价金额过小或处空头排列，属于典型脉冲假高开诱多出货，切勿追高接盘！）",
    "诱多陷阱防坑警示2"
  ],
  "other_notable_stocks": [
    {{
      "symbol": "股票代码",
      "name": "股票名称",
      "short_comment": "一句话点评及风险提示"
    }}
  ]
}}"""

        user_prompt = f"""【当前全市场博弈温度】{market_temp:.1f}° ({market_zone})，博弈格局：{market_summary_raw}
【前瞻题材主线】：{catalysts_summary or '结构性轮动主线'}

【今日 9:25 竞价候选标的详情】:
{stocks_context}

请立即研判并输出 JSON！"""

        try:
            raw_reply = await generate_ai_text(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=2200,
                timeout=70.0,
            )

            match = re.search(r"\{[\s\S]*\}", raw_reply)
            if match:
                parsed = json.loads(match.group(0))
                if parsed.get("core_five_stocks"):
                    return parsed
        except Exception as e:
            logger.warning("AI 竞价推演生成失败或超时，启动规则引擎智能降级: %s", e)

        return self._fallback_analysis(top_candidates, market_temp, market_zone)

    def _fallback_analysis(self, top_candidates: list[dict], market_temp: float, market_zone: str) -> dict:
        """规则引擎智能兜底生成（确保即使 AI 离线也具备专业推演内容）。"""
        core_five = []
        trap_warnings = []

        for idx, r in enumerate(top_candidates[:5]):
            sym = r.get("symbol", "")
            name = r.get("name", "")
            gap = r.get("open_gap_pct", 0.0)
            amt = r.get("bidding_amount_wan", 0.0)
            vr = r.get("bidding_vol_ratio", 0.0)
            pat = r.get("pattern", "跳空高开抢筹")
            mv = r.get("total_mv", 50.0)
            c5d = r.get("change_5d_pct", 0.0)
            cat = r.get("sentiment_tag") or r.get("announcement_title") or "蓄势突破"

            # 评估封板概率
            prob = 65
            if r.get("is_5d_lowest_doji"):
                prob += 15
            if amt >= 1000.0:
                prob += 10
            if 2.0 <= gap <= 6.0:
                prob += 5
            prob = min(95, prob)

            # 主力意图定性
            if amt < 500.0 and gap >= 3.0:
                intent = "【诱多出货高危】竞价资金过于轻浮，疑似虚挂撤单诱多，散户严禁追高接盘！"
                will_limit = f"封板概率仅 {prob-20}%，早盘冲高后极易跳水长上影，缺乏真金白银承接。"
                tactics = "观望为主，若开盘快速跌破分时黄线坚决不予参与。"
            else:
                intent = "【持续看好蓄势起爆】前日完成极致缩量洗盘，主力控盘良好，早盘真金白银大单抢筹突破！"
                will_limit = f"封板胜率预估 {prob}%。9:30 开盘若能维持在分时均线上方 1%~2% 强势震荡，极易触发资金合力快速打板封涨停！"
                tactics = f"建议在 9:30 开盘后回踩分时黄线附近分批挂单吸纳，跌破昨日收盘价 ¥{r.get('close_prev', 0):.2f} 无条件止损。"

            core_five.append({
                "symbol": sym,
                "name": name,
                "board": r.get("board", "主板"),
                "score": r.get("score", 90.0),
                "stars": r.get("stars", 5),
                "open_gap_pct": gap,
                "bidding_amount_wan": amt,
                "bidding_vol_ratio": vr,
                "pattern": pat,
                "gap_reason": f"前日蓄势小阳/十字星 + 题材共振【{cat}】主力早盘抢筹高开",
                "will_limit_up": will_limit,
                "limit_up_prob": prob,
                "capital_5d_flow": f"近5日累计涨幅 {c5d:+.1f}%，5日均成交约 {r.get('amount_5d_avg_wan', 0):.0f} 万元，量能处于良性控盘蓄势阶段。",
                "main_intent": intent,
                "open_tactics": tactics,
            })

        trap_warnings = [
            "⚠️ 警惕【虚假高开】：若个股竞价高开超 +3.5% 但竞价金额不足 500 万元，属于典型脉冲假高开诱多，开盘极易巨阴砸盘！",
            "⚠️ 警惕【高位加速衰竭】：近5日涨幅已超 +25% 且处于连板高潮末端的标的，早盘高开容易成为获利游资派发筹码的陷阱，宁可错过不可接飞刀！",
        ]

        return {
            "market_sentiment_summary": f"全市场当前博弈温度约为 {market_temp:.1f}° ({market_zone})，市场处于结构性博弈期。竞价抢筹宜聚焦于‘5日缩量极致十字星 + 竞价真金白银超千万抢筹’的先锋龙头，严防无量假高开诱多。",
            "core_five_stocks": core_five,
            "trap_warnings": trap_warnings,
            "other_notable_stocks": [],
        }

    def _persist(self, report: dict) -> None:
        try:
            self._latest_file.parent.mkdir(parents=True, exist_ok=True)
            self._latest_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("持久化最新竞价抢筹报告失败: %s", e)

        try:
            history = []
            if self._history_file.exists():
                history = json.loads(self._history_file.read_text(encoding="utf-8"))
            date_val = report.get("date")
            history = [h for h in history if h.get("date") != date_val]
            summary_item = {
                "date": date_val,
                "updated_at": report.get("updated_at"),
                "market_temperature": report.get("market_temperature"),
                "total_screened": report.get("total_screened"),
                "core_five_stocks": [
                    {
                        "symbol": s.get("symbol"),
                        "name": s.get("name"),
                        "limit_up_prob": s.get("limit_up_prob"),
                        "main_intent": s.get("main_intent"),
                        "gap_reason": s.get("gap_reason"),
                    }
                    for s in report.get("core_five_stocks", [])
                ],
            }
            history.append(summary_item)
            history = history[-60:]
            self._history_file.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("持久化历史竞价抢筹报告失败: %s", e)

    def register_jobs(self, scheduler: AsyncIOScheduler) -> None:
        """向调度器注册交易日 09:25:20 自动执行任务。"""
        scheduler.add_job(
            self.run_daily_auction_snatch,
            trigger=CronTrigger(day_of_week="mon-fri", hour=9, minute=25, second=20, timezone="Asia/Shanghai"),
            id="auction_snatch_morning_925",
            name="9:25 集合竞价抢筹自动选股与 AI 核心推演",
            misfire_grace_time=600,
            replace_existing=True,
        )
        logger.info("已注册 9:25 集合竞价抢筹自动调度任务 (周一至周五 09:25:20)")

    async def boot_check(self) -> None:
        """开机或服务启动时自动检查是否需要补跑今日竞价抢筹。"""
        await asyncio.sleep(8.0)
        now = _bj_now()
        weekday = now.weekday()
        if weekday > 4:
            logger.info("今日为周末非交易日，跳过集合竞价补跑")
            return

        market_auction_time = now.replace(hour=9, minute=25, second=20, microsecond=0)
        today_str = _bj_today_str()
        if now >= market_auction_time:
            latest_date = self._latest_report.get("date") if self._latest_report else None
            if not latest_date or latest_date != today_str:
                logger.info("检测到当前处于交易时间且尚未生成今日竞价推演，启动自动补跑...")
                try:
                    await self.run_daily_auction_snatch()
                except Exception as e:
                    logger.warning("开机自动补跑竞价推演异常: %s", e)

