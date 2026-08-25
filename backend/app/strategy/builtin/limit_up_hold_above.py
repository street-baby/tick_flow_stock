"""涨停不破（首板后最低价不破涨停价）

筛选逻辑：
1. 涨停日涨幅 ≥ 9.8%（主板首板涨停）
2. 涨停后至少经历 3 个交易日（且在近一个月 / 20 个交易日窗口内）
3. 期间所有后续交易日最低价（low）始终未跌破涨停日收盘价
4. 首板后不再涨停：窗口期内仅一次涨停（无连板、无再涨停）
5. 标的范围：主板股票，自动排除 ST、科创板、创业板、北交所
"""
from __future__ import annotations

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    SignalMatrix,
    make_signal_matrix,
    matrix_feature,
    valid_rolling_min,
    valid_shift,
)

META = {
    "id": "limit_up_hold_above",
    "name": "涨停不破（首板回踩不破）",
    "description": "主板单次首板涨停后，后续所有交易日最低价均高于涨停收盘价（强势承接横盘/突破）",
    "tags": ["涨停", "首板", "主板", "强势整理", "突破"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "params": [
        {
            "id": "lookback_window",
            "label": "考察窗口(交易日)",
            "type": "int",
            "default": 20,
            "min": 5,
            "max": 60,
            "step": 1,
        },
        {
            "id": "min_days_after",
            "label": "涨停后至少交易日数",
            "type": "int",
            "default": 3,
            "min": 1,
            "max": 15,
            "step": 1,
        },
        {
            "id": "min_limit_up_pct",
            "label": "涨停涨幅阈值%",
            "type": "float",
            "default": 9.8,
            "min": 8.0,
            "max": 10.5,
            "step": 0.1,
        },
        {
            "id": "only_single_limit_up",
            "label": "仅限首板（无连板/再涨停）",
            "type": "bool",
            "default": True,
        },
    ],
    "basic_filter": {
        "boards": ["沪主板", "深主板"],
        "exclude_st": True,
        "exclude_new_days": 30,
        "price_min": 3.0,
    },
    "scoring": {
        "amount": 0.4,
        "change_pct": 0.3,
        "momentum_20d": 0.3,
    },
    "order_by": "score",
    "descending": True,
    "limit": 100,
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_limit_up"]
EXIT_SIGNALS = ["signal_ma20_breakdown"]
STOP_LOSS = -0.05
MAX_HOLD_DAYS = 15
ALERTS = []


class LimitUpHoldAboveStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"close", "low", "high", "open"})

    def required_warmup_bars(self, params: dict) -> int:
        return int(params.get("lookback_window", 20)) + 10

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        lookback = int(params.get("lookback_window", 20))
        min_days = int(params.get("min_days_after", 3))
        min_pct = float(params.get("min_limit_up_pct", 9.8)) / 100.0
        only_single = bool(params.get("only_single_limit_up", True))

        change_pct = matrix_feature(market, "change_pct")
        close_valid = np.isfinite(market.close)
        low_valid = np.isfinite(market.low) & (market.low > 0)

        is_limit = (change_pct >= min_pct) & close_valid

        # 统计考察窗口内涨停总次数
        T, N = market.shape
        limit_count_in_window = np.zeros(market.shape, dtype=np.int32)
        for t in range(T):
            start = max(0, t - lookback + 1)
            limit_count_in_window[t] = np.sum(is_limit[start : t + 1], axis=0)

        entry_bool = np.zeros(market.shape, dtype=bool)

        # 遍历涨停日距离当前条的偏移 k: k in [min_days, lookback - 1]
        for k in range(min_days, lookback):
            shifted_limit = valid_shift(is_limit.astype(np.float32), k, close_valid)
            limit_k_ago = np.nan_to_num(shifted_limit, nan=0.0) > 0.5
            limit_close_k_ago = valid_shift(market.close, k, close_valid)

            # 涨停后所有后续交易日（从 t-k+1 到 t 共 k 根 K 线）的最低价
            min_low_k = valid_rolling_min(market.low, low_valid, k)

            holds = (
                np.isfinite(min_low_k)
                & np.isfinite(limit_close_k_ago)
                & (min_low_k >= limit_close_k_ago)
            )
            entry_bool |= (limit_k_ago & holds)

        if only_single:
            entry_bool &= (limit_count_in_window == 1)

        return make_signal_matrix(
            market.shape,
            entry=entry_bool.astype(np.uint8),
            entry_signal_code=np.where(entry_bool, 0, -1).astype(np.int16),
            entry_signal_ids=("signal_limit_up",),
        )


MATRIX_STRATEGY = LimitUpHoldAboveStrategy()
