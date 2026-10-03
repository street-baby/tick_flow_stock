# -*- coding: utf-8 -*-
"""智兔数服 (Zhitu API) HTTP 客户端封装。"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, List, Optional
import httpx

logger = logging.getLogger(__name__)

DEFAULT_TOKEN = "B9B718D3-3FDD-461B-B4C2-A261A3B01702"
DEFAULT_BASE_URL = "https://api.zhituapi.com"


def get_token() -> str:
    token = os.environ.get("ZHITU_API_TOKEN") or os.environ.get("YZX_ZHITU_API_TOKEN")
    if not token:
        try:
            from app.config import settings
            token = getattr(settings, "zhitu_api_token", "")
        except Exception:
            pass
    return token or DEFAULT_TOKEN


def get_base_url() -> str:
    url = os.environ.get("ZHITU_BASE_URL") or os.environ.get("YZX_ZHITU_BASE_URL")
    if not url:
        try:
            from app.config import settings
            url = getattr(settings, "zhitu_base_url", "")
        except Exception:
            pass
    return (url or DEFAULT_BASE_URL).rstrip("/")


def to_standard_code(code: str) -> str:
    """标准化代码：统一为 '600519.SH' / '000001.SZ' / '430047.BJ' / '000001.SH'"""
    s = str(code).strip().upper()
    if s.startswith("SH.") or s.startswith("SZ.") or s.startswith("BJ."):
        prefix, num = s.split(".", 1)
        return f"{num}.{prefix}"
    if "." in s:
        num, ext = s.split(".", 1)
        if ext in ("SH", "SZ", "BJ"):
            return f"{num:0>6}.{ext}"
    if len(s) == 6 and s.isdigit():
        if s.startswith(("60", "68", "90")):
            return f"{s}.SH"
        elif s.startswith(("00", "30", "20")):
            return f"{s}.SZ"
        elif s.startswith(("43", "83", "87", "92")):
            return f"{s}.BJ"
        elif s.startswith("000") and s in ("000300", "000001", "000905", "000852"):
            return f"{s}.SH"
    return s


def is_index(symbol: str) -> bool:
    std = to_standard_code(symbol)
    if std.startswith("399") or (std.endswith(".SZ") and std.startswith("399")):
        return True
    if std.endswith(".SH") and (std.startswith("000") or std.startswith("0000")):
        return True
    return std in {
        "000001.SH", "000300.SH", "000905.SH", "000852.SH",
        "399001.SZ", "399006.SZ", "000688.SH", "000016.SH",
        "000002.SH", "000003.SH", "000004.SH", "000005.SH",
        "000006.SH", "000007.SH", "000008.SH", "000009.SH",
        "000010.SH", "000011.SH", "000012.SH", "000013.SH",
    }


class ZhituClient:
    """智兔数服 API 请求封装（线程安全 + 防死锁超时 + 429 自适应避让）"""

    _rate_limited_until: float = 0.0
    _last_429_logged: float = 0.0

    def __init__(self, token: Optional[str] = None, base_url: Optional[str] = None, timeout: float = 10.0):
        self.token = token or get_token()
        self.base_url = (base_url or get_base_url()).rstrip("/")
        self.timeout = timeout
        self._local = threading.local()
        self._clients: list[httpx.Client] = []
        self._clients_lock = threading.Lock()

    @property
    def client(self) -> httpx.Client:
        c = getattr(self._local, "client", None)
        if c is None or c.is_closed:
            c = httpx.Client(
                base_url=self.base_url,
                timeout=httpx.Timeout(
                    timeout=self.timeout,
                    connect=5.0,
                    read=8.0,
                    write=5.0,
                    pool=5.0,
                ),
                headers={"User-Agent": "Mozilla/5.0 (compatible; TickFlowStockPanel/1.0)"},
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            )
            self._local.client = c
            with self._clients_lock:
                self._clients.append(c)
        return c

    def close(self) -> None:
        with self._clients_lock:
            for c in self._clients:
                if not c.is_closed:
                    try:
                        c.close()
                    except Exception:
                        pass
            self._clients.clear()
        if hasattr(self._local, "client"):
            try:
                del self._local.client
            except Exception:
                pass

    def get_json(self, path: str, params: Optional[dict] = None, timeout: Optional[float] = None) -> Any:
        now = time.time()
        if now < ZhituClient._rate_limited_until:
            if now - ZhituClient._last_429_logged > 5.0:
                logger.warning("智兔 API 处于 429 限流冷静期，剩余 %.1f 秒，跳过请求 [%s]", ZhituClient._rate_limited_until - now, path)
                ZhituClient._last_429_logged = now
            return None

        q_params = {"token": self.token}
        if params:
            q_params.update(params)
        try:
            req_timeout = timeout if timeout is not None else self.timeout
            resp = self.client.get(path, params=q_params, timeout=req_timeout)
            if resp.status_code == 429:
                ZhituClient._rate_limited_until = time.time() + 25.0
                logger.warning("智兔 API 触发 429 限流 [%s]，进入 25 秒避让冷静期", path)
                return None
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict) and "error" in data:
                logger.warning("智兔 API 响应错误 [%s]: %s", path, data["error"])
                return None
            return data
        except Exception as e:
            logger.warning("智兔 API 请求失败 [%s]: %s", path, e)
            return None

    def fetch_stock_list(self) -> List[dict]:
        """获取全市场 A 股列表"""
        data = self.get_json("/hs/list/all")
        return data if isinstance(data, list) else []

    def fetch_index_list(self) -> List[dict]:
        """获取沪深指数列表"""
        data = self.get_json("/hz/list/hszs")
        return data if isinstance(data, list) else []

    _index_quotes_cache: dict = {}
    _index_quotes_ts: float = 0.0

    def fetch_index_quotes(self, symbols: List[str]) -> List[dict]:
        """获取指数实时点位与行情快照（多线程并发 + 短暂缓存）"""
        if not symbols:
            return []

        import time
        now = time.time()
        sym_key = ",".join(sorted(symbols))
        if sym_key in self._index_quotes_cache and (now - self._index_quotes_ts) < 3.0:
            return self._index_quotes_cache[sym_key]

        from concurrent.futures import ThreadPoolExecutor

        name_map = {
            "000001.SH": "上证指数",
            "399001.SZ": "深证成指",
            "399006.SZ": "创业板指",
            "000680.SH": "科创综指",
            "000688.SH": "科创50",
            "000300.SH": "沪深300",
            "000016.SH": "上证50",
            "000905.SH": "中证500",
            "000852.SH": "中证1000",
            "399005.SZ": "中小100",
        }

        def _fetch_one(sym: str) -> Optional[dict]:
            std = to_standard_code(sym)
            d1 = self.get_json(f"/hz/history/fsjy/{std}/d", timeout=1.5)
            if not d1 or not isinstance(d1, list):
                return None
            last_d = d1[-1]
            m5 = self.get_json(f"/hz/history/fsjy/{std}/5", timeout=1.5)
            prev_close = float(last_d.get("pc") or 0.0)
            last_price = float(m5[-1]["c"]) if m5 and isinstance(m5, list) and len(m5) > 0 else float(last_d.get("c") or 0.0)
            change_amt = last_price - prev_close if prev_close else 0.0
            change_pct = (change_amt / prev_close * 100) if prev_close else 0.0
            return {
                "symbol": sym,
                "name": name_map.get(sym, name_map.get(std, sym)),
                "last_price": last_price,
                "close": last_price,
                "prev_close": prev_close,
                "change_amount": change_amt,
                "change_pct": change_pct,
                "amount": float(last_d.get("a") or 0.0),
                "volume": float(last_d.get("v") or 0.0),
                "date": last_d.get("t"),
                "source": "zhitu",
            }

        with ThreadPoolExecutor(max_workers=min(len(symbols), 8)) as executor:
            results = list(executor.map(_fetch_one, symbols))

        quotes = [r for r in results if r is not None]
        if quotes:
            self._index_quotes_cache[sym_key] = quotes
            self._index_quotes_ts = now
        return quotes

    def fetch_daily_klines(self, symbol: str, adj: str = "n") -> List[dict]:
        """获取日K线 (adj: n 不复权, f 前复权, b 后复权)"""
        std_code = to_standard_code(symbol)
        if is_index(std_code):
            path = f"/hz/history/fsjy/{std_code}/d"
        else:
            path = f"/hs/history/{std_code}/d/{adj}"
        data = self.get_json(path)
        return data if isinstance(data, list) else []

    def fetch_minute_klines(self, symbol: str, period: str = "5", adj: str = "n", is_idx: bool = False) -> List[dict]:
        """获取分钟K线 (period: 5, 15, 30, 60)"""
        std_code = to_standard_code(symbol)
        if period not in ("5", "15", "30", "60"):
            period = "5"
        if is_idx or is_index(std_code):
            path = f"/hz/history/fsjy/{std_code}/{period}"
        else:
            path = f"/hs/history/{std_code}/{period}/{adj}"
        data = self.get_json(path)
        return data if isinstance(data, list) else []

    def fetch_realtime_quotes(self) -> List[dict]:
        """获取全市场实时行情快照"""
        data = self.get_json("/hs/custom/realall") or self.get_json("/hs/public/realall")
        return data if isinstance(data, list) else []

    def fetch_limit_up_pool(self, trade_date: str) -> List[dict]:
        """获取指定交易日涨停股池"""
        data = self.get_json(f"/hs/pool/ztgc/{trade_date}")
        return data if isinstance(data, list) else []

    def fetch_financials(self, symbol: str, table: str) -> List[dict]:
        """获取财务报表数据"""
        std_code = to_standard_code(symbol)
        path_map = {
            "metrics": f"/hs/fin/ratios/{std_code}",
            "income": f"/hs/fin/income/{std_code}",
            "balance_sheet": f"/hs/fin/balance/{std_code}",
            "cash_flow": f"/hs/fin/cashflow/{std_code}",
            "shares": f"/hs/fin/capital/{std_code}",
        }
        path = path_map.get(table)
        if not path:
            return []
        data = self.get_json(path)
        return data if isinstance(data, list) else []
