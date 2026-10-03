"""Regression test for false positive limit up/down signals.

Ensures that stocks with small gains (e.g. +1.24%, +3%, or STAR stocks with +8.5%)
are never classified as limit up, and stocks with small drops are never classified as limit down.
"""
from __future__ import annotations

from datetime import date
import polars as pl
import pytest

from app.indicators.pipeline import compute_limit_signals, _compute_limit_signals_today


def test_false_limit_up_rejected_when_gain_is_insufficient():
    # 601199.SH main board stock, raw_close 6.55, prev_raw 6.47 (+1.24% gain)
    # Even if effective_limit_up were erroneously low (e.g. 6.41), it must NOT be marked limit up.
    today = date(2026, 9, 14)
    rows = pl.DataFrame({
        "symbol": ["601199.SH"],
        "date": [today],
        "open": [6.50],
        "high": [6.77],
        "low": [6.46],
        "close": [6.55],
        "raw_close": [6.55],
        "raw_high": [6.77],
        "_prev_close_raw": [6.47],
        "change_pct": [0.0124],
        "volume": [260000.0],
    })
    instruments = pl.DataFrame({
        "symbol": ["601199.SH"],
        "name": ["江南水务"],
    })
    res = _compute_limit_signals_today(rows, instruments)
    assert res["signal_limit_up"][0] is False
    assert res["signal_broken_limit_up"][0] is False


def test_star_market_stock_needs_twenty_percent():
    # 688260.SH STAR market stock (20% limit), raw_close 119.23, prev_raw 109.90 (+8.49% gain)
    today = date(2026, 9, 14)
    rows = pl.DataFrame({
        "symbol": ["688260.SH"],
        "date": [today],
        "open": [103.6],
        "high": [123.0],
        "low": [102.5],
        "close": [119.23],
        "raw_close": [119.23],
        "raw_high": [123.0],
        "_prev_close_raw": [109.90],
        "change_pct": [0.0849],
        "volume": [78000.0],
    })
    instruments = pl.DataFrame({
        "symbol": ["688260.SH"],
        "name": ["昀冢科技"],
    })
    res = _compute_limit_signals_today(rows, instruments)
    assert res["signal_limit_up"][0] is False


def test_real_limit_up_detected_correctly():
    # 000993.SZ main board +10% limit up
    today = date(2026, 9, 14)
    rows = pl.DataFrame({
        "symbol": ["000993.SZ"],
        "date": [today],
        "open": [14.51],
        "high": [15.27],
        "low": [14.51],
        "close": [15.27],
        "raw_close": [15.27],
        "raw_high": [15.27],
        "_prev_close_raw": [13.88],
        "change_pct": [0.1001],
        "volume": [510000.0],
    })
    instruments = pl.DataFrame({
        "symbol": ["000993.SZ"],
        "name": ["闽东电力"],
    })
    res = _compute_limit_signals_today(rows, instruments)
    assert res["signal_limit_up"][0] is True
    assert res["consecutive_limit_ups"][0] == 1


def test_compute_limit_signals_full_history_defense():
    # 2 days: day 1 close=10.0, day 2 close=10.2 (+2.0% gain)
    df = pl.DataFrame({
        "symbol": ["600001.SH", "600001.SH"],
        "date": [date(2026, 9, 11), date(2026, 9, 14)],
        "open": [10.0, 10.1],
        "high": [10.0, 10.3],
        "low": [10.0, 10.0],
        "close": [10.0, 10.2],
        "raw_close": [10.0, 10.2],
        "raw_high": [10.0, 10.3],
        "change_pct": [0.0, 0.02],
        "volume": [1000.0, 1000.0],
    })
    instruments = pl.DataFrame({
        "symbol": ["600001.SH"],
        "name": ["普通股"],
    })
    res = compute_limit_signals(df, instruments).sort("date")
    assert res["signal_limit_up"].to_list()[-1] is False
    assert res["signal_broken_limit_up"].to_list()[-1] is False


def test_limit_ladder_endpoint_defends_against_dirty_signal(tmp_path):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.screener import router as screener_router

    today = date(2026, 9, 14)
    # Simulated enriched table where 601199.SH was erroneously marked signal_limit_up=True
    # but has change_pct=0.0124 (only +1.24%)
    enriched_df = pl.DataFrame({
        "symbol": ["000993.SZ", "601199.SH"],
        "name": ["闽东电力", "江南水务"],
        "date": [today, today],
        "close": [15.27, 6.55],
        "open": [14.51, 6.50],
        "high": [15.27, 6.77],
        "low": [14.51, 6.46],
        "raw_close": [15.27, 6.55],
        "raw_high": [15.27, 6.77],
        "change_pct": [0.1001, 0.0124],
        "signal_limit_up": [True, True],
        "signal_limit_down": [False, False],
        "signal_broken_limit_up": [False, False],
        "consecutive_limit_ups": [4, 1],
        "consecutive_limit_downs": [0, 0],
    })

    app = FastAPI()
    app.state.repo = SimpleNamespace(
        store=SimpleNamespace(data_dir=tmp_path),
        latest_enriched_date_market=lambda m: None,
        get_name_map=lambda s: {},
        get_enriched_latest_asset=lambda a: (enriched_df, today),
        get_instruments_asset=lambda a: pl.DataFrame(),
        load_prior_consecutive=lambda d, c: pl.DataFrame(),
        latest_daily_date=lambda: today,
    )
    app.include_router(screener_router)
    client = TestClient(app)

    res = client.get(f"/api/screener/limit-ladder?as_of={today.isoformat()}&direction=up")
    assert res.status_code == 200
    data = res.json()

    # Up count must only count the real limit up (1), not the +1.24% fake one
    assert data["counts"]["up"] == 1

    all_symbols = [s["symbol"] for t in data.get("tiers", []) for s in t.get("stocks", [])]
    assert "000993.SZ" in all_symbols
    assert "601199.SH" not in all_symbols


def test_limit_ladder_promotes_to_next_board_when_prior_consecutive_exists(tmp_path):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.screener import router as screener_router

    today = date(2026, 9, 22)
    # Stock is limit up today, but enriched table had consecutive_limit_ups=1
    enriched_df = pl.DataFrame({
        "symbol": ["600825.SH"],
        "name": ["新华传媒"],
        "date": [today],
        "close": [6.42],
        "open": [6.42],
        "high": [6.42],
        "low": [6.42],
        "raw_close": [6.42],
        "raw_high": [6.42],
        "change_pct": [0.0993],
        "signal_limit_up": [True],
        "signal_limit_down": [False],
        "signal_broken_limit_up": [False],
        "consecutive_limit_ups": [1],
        "consecutive_limit_downs": [0],
    })

    # Prior day had 1 board in enriched storage parquet
    prior_df = pl.DataFrame({
        "symbol": ["600825.SH"],
        "consecutive_limit_ups": [1],
        "consecutive_limit_downs": [0],
    })
    prior_dir = tmp_path / "kline_daily_enriched" / "date=2026-09-21"
    prior_dir.mkdir(parents=True)
    prior_df.write_parquet(prior_dir / "part.parquet")

    app = FastAPI()
    app.state.repo = SimpleNamespace(
        store=SimpleNamespace(data_dir=tmp_path),
        latest_enriched_date_market=lambda m: None,
        get_name_map=lambda s: {},
        get_enriched_latest_asset=lambda a: (enriched_df, today),
        get_instruments_asset=lambda a: pl.DataFrame(),
        latest_daily_date=lambda: today,
    )
    app.include_router(screener_router)
    client = TestClient(app)

    res = client.get(f"/api/screener/limit-ladder?as_of={today.isoformat()}&direction=up")
    assert res.status_code == 200
    data = res.json()

    # Must be placed in tier 2 (2板), NOT tier 1 (首板)
    tier_map = {t["boards"]: t["stocks"] for t in data.get("tiers", [])}
    assert 2 in tier_map, "Expected stock to be in 2板 tier"
    assert 1 not in tier_map or not any(s["symbol"] == "600825.SH" for s in tier_map.get(1, []))

    stock_in_tier2 = [s for s in tier_map[2] if s["symbol"] == "600825.SH"]
    assert len(stock_in_tier2) == 1
    assert stock_in_tier2[0]["boards"] == 2
    assert stock_in_tier2[0]["consecutive_limit_ups"] == 2

