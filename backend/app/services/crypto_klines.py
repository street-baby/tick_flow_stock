# -*- coding: utf-8 -*-
"""加密货币公开行情拉取 (Bybit 优先, Binance/MEXC 兑底)。

设计对齐 CONTRIBUTING.md §4 数据源插件化精神:
  - 本模块是 crypto 市场的"实时读取"数据边界, 上层 (api/kline.py, api/indices_market.py)
    依赖这里的标准字段契约 (symbol, datetime/date, open/high/low/close, volume, amount),
    不依赖交易所响应结构。
  - 交易所 symbol 归一化: 内部统一 "BTCUSDT" (base+quote 无分隔),
    请求时按交易所规则转换 (Bybit/MEXC 用 BTCUSDT, OKX 留作后续扩展用 BTC-USDT)。
  - 只读公开行情, 不落盘, 不进 repo 存储目录 (crypto 无除权/涨跌停/停牌语义,
    enriched 指标管道是 A 股契约, 不适用)。
  - 上游失败逐级兜底, 全部失败返回空 DataFrame, 不抛异常打断 API 契约。

分钟 K datetime 为 UTC; 前端分时图 crypto 分支直接按 UTC 展示 (24/7 市场
没有"北京时间墙钟"概念, 与 A 股分时的北京时间映射规则隔离)。
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

import httpx
import polars as pl

logger = logging.getLogger(__name__)

_BYBIT_BASE = "https://api.bybit.com"
_BINANCE_BASE = "https://api.binance.com"
_MEXC_BASE = "https://api.mexc.com"
_TIMEOUT = 10.0
_MAX_BARS = 1000  # Binance 单次上限 1000; MEXC 默认 1000

# 短 TTL 内存缓存: 与 tradingview 插件 client 的防限流思路一致。
# key = (exchange, kind, symbol, interval, start_ms, end_ms)
_CACHE_LOCK = __import__("threading").RLock()
_CACHE: dict[tuple, tuple[float, object]] = {}
_CACHE_TTL_SECONDS = 60.0


def is_crypto_symbol(symbol: str) -> bool:
    """按 markets.market_of 的同一规则判断是否 crypto (避免循环 import 的轻量复制)。

    crypto 市场注册于 backend/app/markets.py (MARKET_CRYPTO); 这里只做
    "是否需要走 crypto 行情链路" 的快速判定, 复杂形态 (交易所前缀等)
    仍以 market_of 为准。
    """
    s = (symbol or "").strip().upper()
    if not s:
        return False
    if ":" in s:
        return True  # BINANCE:BTCUSDT 形态
    return s.endswith(("USDT", "USDC", "BUSD")) and len(s) >= 6


def _clean_symbol(symbol: str) -> str:
    """BINANCE:BTCUSDT -> BTCUSDT。"""
    s = (symbol or "").strip().upper()
    if ":" in s:
        return s.split(":")[-1]
    return s


def _cache_get(key: tuple) -> object | None:
    now = time.time()
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and now - hit[0] < _CACHE_TTL_SECONDS:
            return hit[1]
    return None


def _cache_put(key: tuple, val: object) -> None:
    with _CACHE_LOCK:
        if len(_CACHE) > 512:  # 简单防膨胀: 超限整体清空 (短 TTL, 代价可忽略)
            _CACHE.clear()
        _CACHE[key] = (time.time(), val)


def _http_get_json(url: str, params: dict) -> object | None:
    try:
        resp = httpx.get(url, params=params, timeout=_TIMEOUT)
        if resp.status_code != 200:
            # 交易所的 "Invalid symbol" 等业务错误是 400 + JSON 错误体,
            # 交给适配器/兜底逻辑按空数据处理, 不当网络异常吞掉。
            logger.debug("crypto klines non-200 from %s: %s %s", url, resp.status_code, resp.text[:120])
            return resp.json() if resp.text.strip().startswith(("{", "[")) else None
        return resp.json()
    except Exception as e:  # noqa: BLE001 — 上游失败由调用方兜底
        logger.debug("crypto klines request failed: %s %s: %s", url, params.get("symbol") or params.get("limit"), e)
        return None


# ---------- 交易所适配: 响应 -> 标准行 ----------

def _bybit_klines_to_rows(raw: object) -> list[dict]:
    """Bybit v5 /v5/market/kline → 标准行。

    响应: {retCode, retMsg, result:{list:[[startMs, o, h, l, c, volume, turnover], ...]}}
    (字符串数字); list 按**新→旧**排序, 这里反转成旧→新与其他交易所一致。
    retCode != 0 (如 10001 symbol 不支持) → [] 交由下一交易所兜底。
    """
    if not isinstance(raw, dict) or raw.get("retCode") != 0:
        return []
    lst = (raw.get("result") or {}).get("list")
    if not isinstance(lst, list):
        return []
    rows: list[dict] = []
    for k in lst:
        if not isinstance(k, (list, tuple)) or len(k) < 6:
            continue
        rows.append({
            "datetime": datetime.fromtimestamp(int(k[0]) / 1000, tz=timezone.utc).replace(tzinfo=None),
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
            "amount": float(k[6]) if len(k) > 6 and k[6] not in (None, "") else float(k[5]) * float(k[4]),
        })
    rows.reverse()
    return rows


def _binance_klines_to_rows(raw: object) -> list[dict]:
    """Binance /api/v3/klines 数组 → 标准行。

    数组结构: [open_time, open, high, low, close, volume, close_time,
               quote_volume, trades, ...] (字符串数字)。
    """
    if not isinstance(raw, list):
        return []
    rows: list[dict] = []
    for k in raw:
        if not isinstance(k, (list, tuple)) or len(k) < 7:
            continue
        rows.append({
            "datetime": datetime.fromtimestamp(int(k[0]) / 1000, tz=timezone.utc).replace(tzinfo=None),
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
            "amount": float(k[7]) if len(k) > 7 and k[7] not in (None, "") else float(k[5]) * float(k[4]),
        })
    return rows


def _mexc_klines_to_rows(raw: object) -> list[dict]:
    """MEXC /api/v3/klines 数组 → 标准行 (结构与 Binance 兼容: 字符串数字数组)。"""
    return _binance_klines_to_rows(raw)


def _interval_ms(interval: str) -> int:
    unit = interval[-1]
    n = int(interval[:-1])
    if unit == "m":
        return n * 60_000
    if unit == "h":
        return n * 3_600_000
    if unit == "d":
        return n * 86_400_000
    return 60_000


_BYBIT_INTERVAL_MAP = {"1m": "1", "3m": "3", "5m": "5", "15m": "15", "30m": "30", "1h": "60", "2h": "120", "4h": "240", "1d": "D", "1w": "W"}


def _iter_windows(start_ms: int, end_ms: int, interval: str, max_bars: int):
    """把 [start_ms, end_ms] 切成 <= max_bars 根的窗口 (含收尾对齐)。"""
    step = _interval_ms(interval) * max_bars
    cur = start_ms
    while cur <= end_ms:
        yield cur, min(cur + step - _interval_ms(interval), end_ms)
        cur += step


def fetch_crypto_klines(
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms: int,
) -> pl.DataFrame:
    """拉取一根或多根加密货币 K 线。

    interval: 交易所无关风格 "1m" / "5m" / "1h" / "1d"。
    返回标准列: symbol, datetime, open, high, low, close, volume, amount。
    全部上游失败 → 空 DataFrame。
    """
    sym = _clean_symbol(symbol)
    key = ("kl", sym, interval, start_ms, end_ms)
    cached = _cache_get(key)
    if cached is not None:
        return cached  # type: ignore[return-value]

    rows: list[dict] = []
    for base, path, adapter in (
        (_BYBIT_BASE, "/v5/market/kline", _bybit_klines_to_rows),
        (_BINANCE_BASE, "/api/v3/klines", _binance_klines_to_rows),
        (_MEXC_BASE, "/api/v3/klines", _mexc_klines_to_rows),
    ):
        bybit = base is _BYBIT_BASE
        for win_start, win_end in _iter_windows(start_ms, end_ms, interval, _MAX_BARS):
            if bybit:
                # Bybit v5: interval 1/3/5/15/30/60/120/240/360/720/D/W/M;
                # start/end 参数名 start/end (非 startTime); 单次 limit ≤ 1000。
                params = {
                    "category": "spot", "symbol": sym,
                    "interval": _BYBIT_INTERVAL_MAP.get(interval, interval),
                    "start": win_start, "end": win_end, "limit": _MAX_BARS,
                }
            else:
                params = {"symbol": sym, "interval": interval, "startTime": win_start, "endTime": win_end, "limit": _MAX_BARS}
            raw = _http_get_json(f"{base}{path}", params)
            part = adapter(raw) if raw is not None else []
            if part:
                rows.extend(part)
        if rows:
            break  # 第一个有数据的交易所即用 (Bybit 优先; 未上架币自动落到 Binance/MEXC)
        logger.debug("crypto klines empty from %s for %s %s", base, sym, interval)

    if not rows:
        empty = pl.DataFrame(schema={
            "symbol": pl.String, "datetime": pl.Datetime("us"),
            "open": pl.Float64, "high": pl.Float64, "low": pl.Float64,
            "close": pl.Float64, "volume": pl.Float64, "amount": pl.Float64,
        })
        _cache_put(key, empty)
        return empty

    # 去重 + 排序 (交易所偶发重叠窗口)
    df = pl.DataFrame(rows).unique(subset=["datetime"]).sort("datetime")
    df = df.with_columns(pl.lit(sym).alias("symbol"))
    df = df.select(["symbol", "datetime", "open", "high", "low", "close", "volume", "amount"])
    _cache_put(key, df)
    return df


# ---------- 分钟 K (分时图用) ----------

def _to_utc_ms(dt: datetime) -> int:
    """datetime/date → UTC epoch ms。naive 视为 UTC; aware (含系统本地时区) 转换后取值。"""
    if not isinstance(dt, datetime):
        # API 层传来的是 datetime.date (start_date/end_date 解析产物) — 当 UTC 午夜
        dt = datetime(dt.year, dt.month, dt.day)
    if dt.tzinfo is not None:
        return int(dt.timestamp() * 1000)
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


def fetch_crypto_minute(symbol: str, start_time: datetime, end_time: datetime) -> pl.DataFrame:
    """[start_time, end_time] 的 1m K (naive 按 UTC; aware 自动换算)。"""
    start_ms = _to_utc_ms(start_time)
    end_ms = _to_utc_ms(end_time)
    return fetch_crypto_klines(symbol, "1m", start_ms, end_ms)


def fetch_crypto_minute_recent(symbol: str, minutes: int = 242) -> pl.DataFrame:
    """最近 N 根 1m K (默认 242 根 ≈ 一个 A 股交易日分钟数, crypto 24/7 直接滚动展示)。"""
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - minutes * 60_000
    return fetch_crypto_klines(symbol, "1m", start_ms, end_ms)


def fetch_crypto_minute_by_date(symbol: str, trade_date) -> pl.DataFrame:
    """某"交易日"的全天 1m K (UTC 0 点起 24 小时; crypto 24/7 无收盘概念)。"""
    start_time = datetime(trade_date.year, trade_date.month, trade_date.day, 0, 0, 0)
    end_time = start_time + timedelta(days=1) - timedelta(minutes=1)
    return fetch_crypto_minute(symbol, start_time, end_time)


# ---------- 实时 ticker (清单/行情列表用) ----------

def fetch_crypto_tickers(symbols: list[str] | None = None, limit: int = 0) -> list[dict]:
    """实时 24h ticker (Bybit v5 /v5/market/tickers, category=spot)。

    返回标准行: symbol, name, last, change_pct (24h 涨跌幅, 比例小数), volume, turnover。
    symbols 给定时过滤到这些 symbol; limit>0 时截断。全部失败 → []。
    """
    cached = _cache_get(("tickers",))
    rows = cached if isinstance(cached, list) else None
    if rows is None:
        raw = _http_get_json(f"{_BYBIT_BASE}/v5/market/tickers", {"category": "spot"})
        rows = []
        if isinstance(raw, dict) and raw.get("retCode") == 0:
            for t in (raw.get("result") or {}).get("list") or []:
                try:
                    last = float(t.get("lastPrice") or 0)
                    prev = float(t.get("prevPrice24h") or 0)
                    rows.append({
                        "symbol": (t.get("symbol") or "").upper(),
                        "name": (t.get("symbol") or "").upper(),
                        "last": last,
                        "change_pct": ((last - prev) / prev) if prev else 0.0,
                        "volume": float(t.get("volume24h") or 0),
                        "turnover": float(t.get("turnover24h") or 0),
                    })
                except (TypeError, ValueError):
                    continue
        _cache_put(("tickers",), rows)
    if not rows:
        return []
    out = rows
    if symbols:
        want = {_clean_symbol(s) for s in symbols}
        out = [r for r in out if r["symbol"] in want]
    if limit and len(out) > limit:
        out = out[:limit]
    return out


# ---------- 日 K ----------

def fetch_crypto_daily(symbol: str, start_time: datetime, end_time: datetime) -> list[dict]:
    """日 K → KlineRow 兼容 dict 列表 (date/ohlc/volume/change_pct)。

    crypto 无除权因子, 直接用原始价; change_pct 按日收盘环比计算 (比例小数, 契约 §3.1)。
    """
    start_ms = _to_utc_ms(start_time)
    # 交易所把 endTime 恰好等于最后一根日K开盘时刻的区间视为不含; 加一个 interval
    # 宽度确保「end=今天」时今天的实时日K (未收盘) 也返回。
    end_ms = _to_utc_ms(end_time) + 86_400_000
    df = fetch_crypto_klines(symbol, "1d", start_ms, end_ms)
    if df.is_empty():
        return []
    df = df.sort("datetime")
    prev_close: float | None = None
    out: list[dict] = []
    for r in df.iter_rows(named=True):
        d = r["datetime"].date().isoformat()
        close = float(r["close"])
        change_pct = None
        if prev_close not in (None, 0):
            change_pct = (close - prev_close) / prev_close
        out.append({
            "symbol": r["symbol"],
            "date": d,
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": close,
            "volume": float(r["volume"]),
            "change_pct": change_pct,
        })
        prev_close = close
    return out
