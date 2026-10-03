# -*- coding: utf-8 -*-
"""crypto 分钟/日K 公开行情链路测试。

覆盖:
1. is_crypto_symbol 判定 (USDT/USDC 后缀, 交易所前缀, 股票/美股不误判)
2. fetch_crypto_klines 交易所适配: Binance 优先 → MEXC 兜底 → 全部失败返回空
3. 标准字段契约: symbol/datetime/open/high/low/close/volume/amount
4. fetch_crypto_daily 的 KlineRow 兼容输出 + change_pct 小数比例 (契约 §3.1)
5. API 层 crypto 分流: /minute 不走 repo/交易日逻辑, sync_minute_single 显式拒绝

mock 范式沿用 test_minute_routing.py (monkeypatch 模块属性)。
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from unittest.mock import patch

import polars as pl
import pytest

from app.services import crypto_klines as ck


# ---------- 辅助 ----------

def _clear_cache() -> None:
    with ck._CACHE_LOCK:
        ck._CACHE.clear()


def _fake_http(rows: list[dict] | None):
    """构造 _http_get_json 的 fake: rows 非空时按 URL 返回对应交易所风格的 klines。

    - bybit: {retCode:0, result:{list:[[ms,o,h,l,c,v,turnover],...]}} (新→旧, 适配器反转)
    - binance/mexc: 裸数组 (字符串数字)
    """
    if rows is None:
        return lambda url, params: None
    binance_style = [
        [
            str(int(datetime(2026, 9, 17, 0, i, tzinfo=timezone.utc).timestamp() * 1000)),
            "0.001", "0.002", "0.0009", "0.0015",
            "100.0", "0", "0.15", "10", "0.0", "0.0", "0",
        ]
        for i, _ in enumerate(rows)
    ]
    bybit_style = {
        "retCode": 0,
        "retMsg": "OK",
        "result": {"list": list(reversed([
            [
                str(int(datetime(2026, 9, 17, 0, i, tzinfo=timezone.utc).timestamp() * 1000)),
                "0.001", "0.002", "0.0009", "0.0015", "100.0", "0.15",
            ]
            for i, _ in enumerate(rows)
        ]))},
    }
    return lambda url, params: bybit_style if "bybit" in url else binance_style


@pytest.fixture(autouse=True)
def _no_network_and_clean_cache():
    """默认断网 + 清缓存: 单测不得依赖真实交易所。"""
    _clear_cache()
    with patch.object(ck, "_http_get_json", lambda url, params: None):
        yield
    _clear_cache()


# ---------- 1. is_crypto_symbol 判定 ----------

def test_is_crypto_symbol_matches_quote_suffix():
    assert ck.is_crypto_symbol("SAYLORMOONUSDT") is True
    assert ck.is_crypto_symbol("BTCUSDT") is True
    assert ck.is_crypto_symbol("ETHUSDC") is True
    assert ck.is_crypto_symbol("BINANCE:BTCUSDT") is True
    # 小写归一
    assert ck.is_crypto_symbol("btcusdt") is True


def test_is_crypto_symbol_rejects_non_crypto():
    # A股/ETF/指数/美股 不得误判
    assert ck.is_crypto_symbol("600000.SH") is False
    assert ck.is_crypto_symbol("000001.SZ") is False
    assert ck.is_crypto_symbol("510300.SH") is False
    assert ck.is_crypto_symbol("000300.SH") is False
    assert ck.is_crypto_symbol("AAPL.US") is False
    assert ck.is_crypto_symbol("00700.HK") is False
    assert ck.is_crypto_symbol("") is False
    # 短串 (长度 < 6) 不判: 如 "USDT" 本身
    assert ck.is_crypto_symbol("USDT") is False


# ---------- 2. 交易所适配与兜底 ----------

def test_bybit_success_short_circuits_lower_exchanges():
    """Bybit (首位) 有数据时不再请求 Binance/MEXC (优先级语义)。"""
    calls: list[str] = []

    def fake_http(url: str, params: dict):
        calls.append(url)
        return _fake_http(["x"])(url, params)

    with patch.object(ck, "_http_get_json", fake_http):
        df = ck.fetch_crypto_klines("BTCUSDT", "1m", 0, 60_000)

    assert df.height == 1
    assert all("bybit" in u for u in calls)
    assert len(calls) == 1


def test_mexc_fallback_when_upper_exchanges_invalid_symbol():
    """Bybit/Binance 都无此交易对 (错误体) → 兜底 MEXC (SAYLORMOON 场景)。"""
    calls: list[str] = []

    def fake_http(url: str, params: dict):
        calls.append(url)
        if "binance" in url:
            return {"code": -1121, "msg": "Invalid symbol."}
        if "bybit" in url:
            return {"retCode": 10001, "retMsg": "symbol not supported"}
        return _fake_http(["x"])(url, params)

    with patch.object(ck, "_http_get_json", fake_http):
        df = ck.fetch_crypto_klines("SAYLORMOONUSDT", "1m", 0, 60_000)

    assert df.height == 1
    assert any("mexc" in u for u in calls)
    assert df["symbol"][0] == "SAYLORMOONUSDT"


def test_all_upstreams_fail_returns_empty_df():
    """全部上游失败 → 空 DataFrame (契约列齐全), 不抛异常。"""

    with patch.object(ck, "_http_get_json", lambda url, params: None):
        df = ck.fetch_crypto_klines("FOOBARUSDT", "1m", 0, 60_000)

    assert df.is_empty()
    assert set(df.columns) == {"symbol", "datetime", "open", "high", "low", "close", "volume", "amount"}


def test_exchange_prefix_symbol_cleaned():
    """BINANCE:BTCUSDT 形态归一为 BTCUSDT 后请求。"""
    seen: list[str] = []

    def fake_http(url: str, params: dict):
        seen.append(params.get("symbol"))
        return _fake_http(["x"])(url, params)

    with patch.object(ck, "_http_get_json", fake_http):
        df = ck.fetch_crypto_klines("BINANCE:BTCUSDT", "1m", 0, 60_000)

    assert seen[0] == "BTCUSDT"
    assert df["symbol"][0] == "BTCUSDT"


def test_cache_hit_avoids_second_fetch():
    """同 key 第二次调用命中缓存, 不再发 HTTP。"""
    n_calls = 0

    def fake_http(url: str, params: dict):
        nonlocal n_calls
        n_calls += 1
        return _fake_http(["x"])(url, params)

    with patch.object(ck, "_http_get_json", fake_http):
        ck.fetch_crypto_klines("BTCUSDT", "1m", 0, 60_000)
        ck.fetch_crypto_klines("BTCUSDT", "1m", 0, 60_000)

    assert n_calls == 1


# ---------- 3. 标准字段契约 ----------

def test_row_contract_fields_and_types():
    with patch.object(ck, "_http_get_json", _fake_http(["a", "b"])):
        df = ck.fetch_crypto_klines("BTCUSDT", "1m", 0, 120_000)

    assert df.height == 2
    assert df.schema["datetime"] == pl.Datetime("us")
    for col in ("open", "high", "low", "close", "volume", "amount"):
        assert df.schema[col] == pl.Float64
    # amount 取 quote volume (第 8 列)
    assert df["amount"][0] == pytest.approx(0.15)
    # datetime 为 UTC naive
    assert df["datetime"][0] == datetime(2026, 9, 17, 0, 0)


def test_duplicate_windows_deduped_and_sorted():
    """窗口重叠时去重并按时间排序。"""
    def fake_http(url: str, params: dict):
        return [
            [
                str(int(datetime(2026, 9, 17, 0, i, tzinfo=timezone.utc).timestamp() * 1000)),
                "0.001", "0.002", "0.0009", "0.0015", "100.0", "0", "0.15", "10", "0", "0", "0",
            ]
            for i in (2, 0, 1, 2)  # 乱序 + 重复
        ]

    with patch.object(ck, "_http_get_json", fake_http):
        df = ck.fetch_crypto_klines("BTCUSDT", "1m", 0, 240_000)

    assert df.height == 3
    assert df["datetime"].to_list() == sorted(df["datetime"].to_list())


# ---------- 4. 日 K 输出契约 ----------

def test_daily_rows_contract_and_change_pct_decimal():
    """日K 输出 KlineRow 兼容字段; change_pct 为小数比例 (§3.1), 首行 None。"""
    def fake_http(url: str, params: dict):
        # 两根日 K: close 0.001 → 0.0015 → change_pct = 0.5
        return [
            [
                str(int(datetime(2026, 9, 16, tzinfo=timezone.utc).timestamp() * 1000)),
                "0.0008", "0.0012", "0.0007", "0.001", "1000.0", "0", "1.0", "10", "0", "0", "0",
            ],
            [
                str(int(datetime(2026, 9, 17, tzinfo=timezone.utc).timestamp() * 1000)),
                "0.001", "0.0016", "0.0009", "0.0015", "1200.0", "0", "1.8", "10", "0", "0", "0",
            ],
        ]

    with patch.object(ck, "_http_get_json", fake_http):
        rows = ck.fetch_crypto_daily("BTCUSDT", datetime(2026, 9, 16), datetime(2026, 9, 17))

    assert len(rows) == 2
    assert rows[0]["date"] == "2026-09-16"
    assert rows[0]["change_pct"] is None
    assert rows[1]["change_pct"] == pytest.approx(0.5)
    assert rows[1]["close"] == pytest.approx(0.0015)
    for key in ("symbol", "date", "open", "high", "low", "close", "volume"):
        assert key in rows[0]


def test_daily_empty_upstream_returns_empty_list():
    with patch.object(ck, "_http_get_json", lambda url, params: None):
        rows = ck.fetch_crypto_daily("FOOBARUSDT", datetime(2026, 9, 16), datetime(2026, 9, 17))
    assert rows == []


# ---------- 5. API 层分流 ----------

class _FakeRepo:
    """最小 repo 桩: crypto 请求不得触达 (分流在 resolve 之前)。"""

    def resolve_asset_type(self, symbol: str) -> str:
        raise AssertionError("crypto 分流不应触达 repo.resolve_asset_type")

    def latest_daily_date(self):
        raise AssertionError("crypto 分流不应触达 repo.latest_daily_date")


class _FakeCapset:
    def has(self, _cap) -> bool:
        return True

    def limits(self, _cap):
        return None


def _fake_request():
    from unittest.mock import MagicMock

    req = MagicMock()
    req.app.state.repo = _FakeRepo()
    req.app.state.capabilities = _FakeCapset()
    return req


def test_api_minute_crypto_bypasses_repo():
    from app.api.kline import get_minute

    def fake_fetch(symbol, trade_date):
        return pl.DataFrame({
            "symbol": [symbol],
            "datetime": [datetime(2026, 9, 17, 0, 0)],
            "open": [0.001], "high": [0.002], "low": [0.0009],
            "close": [0.0015], "volume": [100.0], "amount": [0.15],
        })

    with patch.object(ck, "fetch_crypto_minute_by_date", fake_fetch):
        resp = get_minute(
            _fake_request(),
            symbol="SAYLORMOONUSDT",
            trade_date=datetime(2026, 9, 17).date(),
        )

    assert resp["asset_type"] == "crypto"
    assert resp["source"] == "crypto-live"
    assert len(resp["rows"]) == 1
    # crypto 无涨跌停: rate=0 且上下限为 None
    assert resp["price_limit"]["rate"] == 0
    assert resp["price_limit"]["limit_up"] is None
    assert resp["price_limit"]["limit_down"] is None


def test_api_minute_crypto_recent_when_no_date():
    from app.api.kline import get_minute

    with patch.object(
        ck, "fetch_crypto_minute_recent",
        lambda symbol, minutes=242: pl.DataFrame(),
    ):
        resp = get_minute(_fake_request(), symbol="BTCUSDT", trade_date=None)

    assert resp["source"] == "none"
    assert resp["rows"] == []


@pytest.mark.asyncio
async def test_api_sync_minute_single_crypto_rejected():
    from app.api.kline import sync_minute_single
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        await sync_minute_single(_fake_request(), {"symbol": "BTCUSDT"})
    assert "加密货币" in exc_info.value.detail or "crypto" in str(exc_info.value.detail)


# ---------- 6. indices_market crypto 端点 ----------

def test_indices_crypto_list_shape():
    from app.api.indices_market import crypto_indices_list

    resp = crypto_indices_list()
    assert resp["count"] >= 5
    first = resp["results"][0]
    assert first["symbol"] == "BTCUSDT"
    assert first["asset_type"] == "crypto"
    assert first["name"]


def test_indices_crypto_quotes_with_ticker_mock():
    from app.api.indices_market import crypto_indices_quotes

    tickers = [
        {"symbol": "BTCUSDT", "name": "BTCUSDT", "last": 81000.0,
         "change_pct": 0.0123, "volume": 1234.0, "turnover": 9.9e7},
    ]
    with patch.object(ck, "fetch_crypto_tickers", lambda *a, **k: tickers):
        resp = crypto_indices_quotes()

    assert resp["count"] >= 5
    btc = next(r for r in resp["rows"] if r["symbol"] == "BTCUSDT")
    assert btc["last_price"] == 81000.0
    assert btc["pct"] == 0.0123
    # 未返回 ticker 的币 → 字段为 None 而不是炸接口
    eth = next(r for r in resp["rows"] if r["symbol"] == "ETHUSDT")
    assert eth["last_price"] is None
    assert eth["change_pct"] is None


def test_indices_crypto_daily_contract():
    from app.api.indices_market import crypto_indices_daily

    rows = [{"symbol": "BTCUSDT", "date": "2026-09-18", "open": 1.0, "high": 2.0,
             "low": 0.5, "close": 1.5, "volume": 10.0, "change_pct": 0.05}]
    with patch.object(ck, "fetch_crypto_daily", lambda s, a, b: rows):
        resp = crypto_indices_daily(symbol="BTCUSDT")

    assert resp["symbol"] == "BTCUSDT"
    assert resp["rows"] == rows
    assert resp["index_info"]["name"]


def test_indices_crypto_daily_rejects_non_crypto():
    from app.api.indices_market import crypto_indices_daily
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        crypto_indices_daily(symbol="600000.SH")
    assert "加密货币" in exc_info.value.detail


def test_indices_crypto_minute_contract():
    from app.api.indices_market import crypto_indices_minute

    df = pl.DataFrame({
        "symbol": ["BTCUSDT"],
        "datetime": [datetime(2026, 9, 19, 12, 0)],
        "open": [1.0], "high": [2.0], "low": [0.5],
        "close": [1.5], "volume": [10.0], "amount": [15.0],
    })
    with patch.object(ck, "fetch_crypto_minute_recent", lambda s, minutes=242: df):
        resp = crypto_indices_minute(symbol="BTCUSDT")

    assert resp["rows"][0]["datetime"].startswith("2026-09-19T12:00")
    assert resp["rows"][0]["close"] == 1.5
    assert resp["rows"][0]["amount"] == 15.0


def test_thread_safety_cache_lock_exists():
    """缓存锁存在且可用 (并发安全 §6.2 冒烟)。"""
    assert isinstance(ck._CACHE_LOCK, type(threading.RLock()))
    with ck._CACHE_LOCK:
        ck._CACHE.clear()
