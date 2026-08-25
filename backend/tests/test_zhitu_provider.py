# -*- coding: utf-8 -*-
"""ZhituProvider 契约与接口测试。"""
import datetime as dt
from app.plugins.zhitu import provider as zp
from app.plugins.zhitu.provider import ZhituProvider, availability
from app.data_providers.custom import loader as cs


def test_zhitu_availability():
    ok, reason = availability()
    assert ok is True
    assert reason == "ok"


def test_zhitu_plugin_discovered():
    cs._load_builtin_plugins()
    assert "zhitu" in cs.names()
    assert cs.is_custom_provider("zhitu")
    assert cs.provider_has_dataset("zhitu", "daily")
    assert cs.provider_has_dataset("zhitu", "realtime")
    assert cs.provider_has_dataset("zhitu", "minute")
    assert cs.provider_has_dataset("zhitu", "adj_factor")


def test_zhitu_get_instruments():
    p = ZhituProvider()
    stocks = p.get_instruments("stock")
    assert len(stocks) > 5000
    assert any(s["symbol"] == "600519.SH" for s in stocks)


def test_zhitu_get_daily():
    p = ZhituProvider()
    df = p.get_daily(["600519.SH"], dt.datetime(2026, 1, 1), dt.datetime(2026, 1, 15))
    assert not df.is_empty()
    assert "symbol" in df.columns
    assert "date" in df.columns
    assert "close" in df.columns
