# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from app.markets import (
    ALL_MARKETS,
    MARKET_CN,
    MARKET_CRYPTO,
    MARKET_HK,
    MARKET_US,
    get_market,
    market_of,
    normalize_symbol,
)


def test_crypto_market_registration():
    assert MARKET_CRYPTO == "crypto"
    assert MARKET_CRYPTO in ALL_MARKETS

    meta = get_market(MARKET_CRYPTO)
    assert meta.market == "crypto"
    assert meta.label == "加密货币"
    assert meta.t_plus == 0
    assert meta.has_limit is False
    assert meta.stamp_tax == 0.0


def test_market_of_crypto():
    # 常见加密货币交易对
    assert market_of("BTCUSDT") == "crypto"
    assert market_of("ETHUSDT") == "crypto"
    assert market_of("SOLUSDT") == "crypto"
    assert market_of("DOGEUSDT") == "crypto"
    assert market_of("BINANCE:BTCUSDT") == "crypto"
    assert market_of("COINBASE:BTCUSD") == "crypto"
    assert market_of("BTC.CRYPTO") == "crypto"

    # 原有市场不受影响
    assert market_of("600000.SH") == "cn"
    assert market_of("000001.SZ") == "cn"
    assert market_of("00700.HK") == "hk"
    assert market_of("AAPL.US") == "us"
    assert market_of("TSLA.US") == "us"


def test_normalize_symbol_crypto():
    assert normalize_symbol("btcusdt") == "BTCUSDT"
    assert normalize_symbol(" binance:ethusdt ") == "BINANCE:ETHUSDT"
