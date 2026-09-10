# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.screener import router as screener_router


@pytest.fixture
def screener_client(tmp_path: Path):
    app = FastAPI()
    app.state.repo = SimpleNamespace(
        store=SimpleNamespace(data_dir=tmp_path),
        latest_enriched_date_market=lambda m: None,
        get_name_map=lambda s: {},
    )
    app.include_router(screener_router)
    return TestClient(app)


def test_screener_strategies_us_and_crypto(screener_client: TestClient):
    # 美股策略列表
    res_us = screener_client.get("/api/screener/strategies?market=us")
    assert res_us.status_code == 200
    data_us = res_us.json()
    presets_us = data_us.get("presets", [])
    assert len(presets_us) >= 4
    us_ids = [p["id"] for p in presets_us]
    assert "us_megacap_leaders" in us_ids
    assert "us_volume_breakout" in us_ids

    # 加密货币策略列表
    res_crypto = screener_client.get("/api/screener/strategies?market=crypto")
    assert res_crypto.status_code == 200
    data_crypto = res_crypto.json()
    presets_crypto = data_crypto.get("presets", [])
    assert len(presets_crypto) >= 4
    crypto_ids = [p["id"] for p in presets_crypto]
    assert "crypto_top_gainers" in crypto_ids
    assert "crypto_major_leaders" in crypto_ids


def test_screener_run_preset_us(screener_client: TestClient):
    req_body = {
        "strategy_id": "us_megacap_leaders",
        "market": "us",
        "timeframe": "1d",
    }
    res = screener_client.post("/api/screener/run_preset", json=req_body)
    assert res.status_code == 200
    data = res.json()
    assert "rows" in data
    assert data["total"] > 0
    first = data["rows"][0]
    assert first["symbol"].endswith(".US")
    assert first["close"] > 0


def test_screener_run_preset_crypto(screener_client: TestClient):
    req_body = {
        "strategy_id": "crypto_major_leaders",
        "market": "crypto",
        "timeframe": "1d",
    }
    res = screener_client.post("/api/screener/run_preset", json=req_body)
    assert res.status_code == 200
    data = res.json()
    assert "rows" in data
    assert data["total"] > 0
    first = data["rows"][0]
    assert "USDT" in first["symbol"]
    assert first["close"] > 0


def test_screener_cached_result_crypto(screener_client: TestClient):
    res = screener_client.get("/api/screener/cached-result/crypto_major_leaders?market=crypto")
    assert res.status_code == 200
    data = res.json()
    assert data.get("result") is not None
    assert len(data["result"].get("rows", [])) > 0
