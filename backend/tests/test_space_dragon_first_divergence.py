# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    build_market_data_matrix,
    load_market_data_matrix_from_parquet,
)
from app.strategy.builtin.space_dragon_first_divergence import (
    MATRIX_STRATEGY,
    META,
)
from app.strategy.engine import StrategyEngine


def test_space_dragon_strategy_registry():
    builtin_dir = Path(__file__).resolve().parents[1] / "app" / "strategy" / "builtin"
    engine = StrategyEngine(strategy_dirs=[builtin_dir])
    strategy = engine.get("space_dragon_first_divergence")
    assert strategy is not None
    assert strategy.meta["id"] == "space_dragon_first_divergence"
    assert strategy.meta["name"] == "空间龙首日分歧低吸"
    assert strategy.execution_backend == "matrix_native"
    assert strategy.matrix_strategy is not None

    param_ids = {p["id"] for p in strategy.meta["params"]}
    assert "min_boards" in param_ids
    assert "max_boards" in param_ids
    assert "divergence_pattern" in param_ids
    assert "support_type" in param_ids
    assert "min_amount" in param_ids
    assert "main_board_only" in param_ids


def test_space_dragon_synthetic_signals_including_limit_down_and_bear():
    # 构造数据:
    # Day 0: 首板
    # Day 1: 2板
    # Day 2: 3板
    # Day 3: 4板 (consec = 4)
    # Day 4: 跌停分歧或大阴线 (consec = 0)
    num_dates = 6
    num_symbols = 2
    dates = [date(2026, 1, 1) + timedelta(days=i) for i in range(num_dates)]
    symbols = ("000001.SZ", "600000.SH")

    open_arr = np.ones((num_dates, num_symbols), dtype=np.float64) * 10.0
    high_arr = np.ones((num_dates, num_symbols), dtype=np.float64) * 10.5
    low_arr = np.ones((num_dates, num_symbols), dtype=np.float64) * 9.8
    close_arr = np.ones((num_dates, num_symbols), dtype=np.float64) * 10.0
    volume_arr = np.ones((num_dates, num_symbols), dtype=np.float64) * 1_000_000.0
    amount_arr = np.ones((num_dates, num_symbols), dtype=np.float64) * 100_000_000.0
    consec_arr = np.zeros((num_dates, num_symbols), dtype=np.float64)
    tradable = np.ones((num_dates, num_symbols), dtype=bool)
    limit_up = np.zeros((num_dates, num_symbols), dtype=bool)
    limit_down = np.zeros((num_dates, num_symbols), dtype=bool)

    # 4 连板 (Day 0 ~ 3)
    for s in range(2):
        for i in range(4):
            close_arr[i, s] = 10.0 * (1.1 ** (i + 1))
            open_arr[i, s] = 10.0 * (1.1 ** i)
            high_arr[i, s] = close_arr[i, s]
            low_arr[i, s] = open_arr[i, s]
            consec_arr[i, s] = float(i + 1)
            limit_up[i, s] = True

    # Day 4:
    # 股票 0: 出现跌停板 (-10%)
    prev_c_0 = close_arr[3, 0]
    close_arr[4, 0] = prev_c_0 * 0.90
    open_arr[4, 0] = prev_c_0 * 0.95
    high_arr[4, 0] = prev_c_0 * 0.95
    low_arr[4, 0] = prev_c_0 * 0.90
    consec_arr[4, 0] = 0.0

    # 股票 1: 出现大阴线 (-7%)
    prev_c_1 = close_arr[3, 1]
    close_arr[4, 1] = prev_c_1 * 0.93
    open_arr[4, 1] = prev_c_1 * 1.02
    high_arr[4, 1] = prev_c_1 * 1.03
    low_arr[4, 1] = prev_c_1 * 0.92
    consec_arr[4, 1] = 0.0

    matrix = MarketDataMatrix(
        timestamps=np.array([d.strftime("%Y-%m-%d") for d in dates]),
        timestamp_labels=tuple(d.strftime("%Y-%m-%d") for d in dates),
        session_ids=np.zeros(num_dates, dtype=np.int32),
        symbols=symbols,
        names=("平安银行", "浦发银行"),
        open=open_arr,
        high=high_arr,
        low=low_arr,
        close=close_arr,
        volume=volume_arr,
        tradable=tradable,
        limit_up_locked=limit_up,
        limit_down_locked=limit_down,
        fields={
            "amount": amount_arr,
            "consecutive_limit_ups": consec_arr,
        },
    )

    signals = MATRIX_STRATEGY.compute_signals(matrix, {})
    # 验证股票 0（跌停）和股票 1（大阴线）在 Day 4 全部被选出！
    assert signals.entry[4, 0] == 1, "4板次日跌停应被选出"
    assert signals.entry[4, 1] == 1, "4板次日大阴线应被选出"
