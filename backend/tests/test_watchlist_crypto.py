# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import polars as pl
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.kline import router as kline_router
from app.api.watchlist import router as watchlist_router
from app.services import watchlist


@pytest.fixture
def client_app(tmp_path: Path):
    app = FastAPI()

    # Mock repo
    repo = SimpleNamespace(
        store=SimpleNamespace(data_dir=tmp_path, db=None),
        get_instruments_asset=lambda t: pl.DataFrame(),
        get_name_map=lambda syms: {},
        get_etf_symbol_set=lambda: set(),
        get_index_symbol_set=lambda: set(),
        get_enriched_latest=lambda: (pl.DataFrame(), None),
        get_instruments=lambda: pl.DataFrame(),
    )
    app.state.repo = repo
    app.include_router(kline_router)
    app.include_router(watchlist_router)
    return TestClient(app)


def test_watchlist_search_us_and_crypto(client_app: TestClient):
    # 搜索 AAPL
    res = client_app.get("/api/kline/instruments/search?q=AAPL&limit=5")
    assert res.status_code == 200
    results = res.json().get("results", [])
    assert any("AAPL" in r["symbol"] for r in results)

    # 搜索 BTC
    res_crypto = client_app.get("/api/kline/instruments/search?q=BTC&limit=5")
    assert res_crypto.status_code == 200
    c_results = res_crypto.json().get("results", [])
    assert any("BTC" in r["symbol"] for r in c_results)


def test_watchlist_add_and_enrich_crypto_us(client_app: TestClient):
    # 添加 AAPL.US 和 BTCUSDT
    watchlist.add("AAPL.US", "Apple test")
    watchlist.add("BTCUSDT", "Bitcoin test")

    try:
        # 获取自选股基础列表
        res_list = client_app.get("/api/watchlist")
        assert res_list.status_code == 200
        symbols = [s["symbol"] for s in res_list.json().get("symbols", [])]
        assert "AAPL.US" in symbols
        assert "BTCUSDT" in symbols

        # 获取自选股 enriched 行情
        res_enriched = client_app.get("/api/watchlist/enriched")
        assert res_enriched.status_code == 200
        rows = res_enriched.json().get("rows", [])
        assert len(rows) >= 2

        row_map = {r["symbol"]: r for r in rows}
        aapl = row_map.get("AAPL.US")
        btc = row_map.get("BTCUSDT")

        assert aapl is not None
        assert aapl.get("close") is not None and aapl["close"] > 0
        assert aapl.get("change_pct") is not None
        assert aapl.get("name") is not None

        assert btc is not None
        assert btc.get("close") is not None and btc["close"] > 0
        assert btc.get("change_pct") is not None
        assert btc.get("name") is not None
        assert btc.get("asset_type") == "crypto"
    finally:
        watchlist.remove("AAPL.US")
        watchlist.remove("BTCUSDT")
