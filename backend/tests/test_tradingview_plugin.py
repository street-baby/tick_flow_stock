# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from app.plugins.tradingview.screener import (
    get_presets_for_market,
    run_preset_scanner,
)
from app.plugins.tradingview.quotes import get_batch_quotes


def test_presets_list():
    us_presets = get_presets_for_market("us")
    assert len(us_presets) >= 4
    preset_ids = [p["id"] for p in us_presets]
    assert "us_volume_breakout" in preset_ids
    assert "us_rsi_oversold" in preset_ids

    crypto_presets = get_presets_for_market("crypto")
    assert len(crypto_presets) >= 4
    c_preset_ids = [p["id"] for p in crypto_presets]
    assert "crypto_top_gainers" in c_preset_ids
    assert "crypto_major_leaders" in c_preset_ids


def test_run_us_preset():
    # 执行美股千亿蓝筹榜预设
    result = run_preset_scanner("us", "us_megacap_leaders", limit=5)
    assert "rows" in result
    assert "total" in result
    assert len(result["rows"]) > 0
    first = result["rows"][0]
    assert "symbol" in first
    assert "name" in first
    assert "close" in first
    assert "change_pct" in first
    assert first["close"] > 0


def test_run_crypto_preset():
    # 执行加密货币主流榜
    result = run_preset_scanner("crypto", "crypto_major_leaders", limit=5)
    assert "rows" in result
    assert "total" in result
    assert len(result["rows"]) > 0
    first = result["rows"][0]
    assert "symbol" in first
    assert "close" in first
    assert first["close"] > 0


def test_batch_quotes():
    symbols = ["AAPL.US", "NVDA.US", "BTCUSDT", "ETHUSDT"]
    quotes = get_batch_quotes(symbols)
    assert len(quotes) >= 2
    # 验证提取出了价格和涨跌幅
    symbols_found = {q["symbol"] for q in quotes}
    assert any("AAPL" in s or "NVDA" in s for s in symbols_found)
    assert any("BTC" in s or "ETH" in s for s in symbols_found)
