"""涨停不破（首板回踩不破·缩量十字星蓄势）

筛选逻辑：
1. 涨停日涨幅 ≥ 9.8%（主板首板涨停）
2. 涨停后 2 ~ 8 个交易日内，所有交易日最低价（low）始终未跌破涨停日收盘价
3. 当日缩量十字星/小实体蓄势：K线实体 ≤ 3.5%，成交量较涨停日显著萎缩（≤ 80%）
4. 价格贴近涨停支撑区（涨停价上沿 0% ~ 8% 区间），不追高
5. 首板后不再涨停：窗口期内仅一次涨停（排除已连续加速个股）
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
    "description": "主板首板涨停后，回踩坚守涨停价上方 + 缩量十字星/小实体蓄势突破（高胜率低回撤）",
    "tags": ["涨停", "首板", "十字星", "缩量洗盘", "回踩支撑"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "params": [
        {
            "id": "lookback_window",
            "label": "考察窗口(交易日)",
            "type": "int",
            "default": 8,
            "min": 3,
            "max": 15,
            "step": 1,
        },
        {
            "id": "min_days_after",
            "label": "涨停后至少交易日数",
            "type": "int",
            "default": 2,
            "min": 1,
            "max": 6,
            "step": 1,
        },
        {
            "id": "require_doji",
            "label": "要求当日缩量十字星/小实体",
            "type": "bool",
            "default": True,
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
        "amount": 0.35,
        "change_pct": 0.35,
        "momentum_20d": 0.30,
    },
    "order_by": "score",
    "descending": True,
    "limit": 50,
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_limit_up"]
EXIT_SIGNALS = ["signal_ma20_breakdown", "signal_ma_dead_5_20"]
STOP_LOSS = -0.04
TAKE_PROFIT = 0.10
TRAILING_TAKE_PROFIT_ACTIVATE = 0.06
TRAILING_TAKE_PROFIT_DRAWDOWN = 0.025
MAX_HOLD_DAYS = 5
ALERTS = []


class LimitUpHoldAboveStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"close", "low", "high", "open", "volume"})

    def required_warmup_bars(self, params: dict) -> int:
        return int(params.get("lookback_window", 8)) + 15

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        lookback = int(params.get("lookback_window", 8))
        min_days = int(params.get("min_days_after", 2))
        min_pct = float(params.get("min_limit_up_pct", 9.8)) / 100.0
        only_single = bool(params.get("only_single_limit_up", True))
        require_doji = bool(params.get("require_doji", True))

        change_pct = matrix_feature(market, "change_pct")
        close_valid = np.isfinite(market.close)
        low_valid = np.isfinite(market.low) & (market.low > 0)
        open_valid = np.isfinite(market.open) & (market.open > 0)
        vol_valid = np.isfinite(market.volume) & (market.volume > 0)

        is_limit = (change_pct >= min_pct) & close_valid

        # 统计考察窗口内涨停总次数
        T, N = market.shape
        limit_count_in_window = np.zeros(market.shape, dtype=np.int32)
        for t in range(T):
            start = max(0, t - lookback + 1)
            limit_count_in_window[t] = np.sum(is_limit[start : t + 1], axis=0)

        # 实体大小与振幅判定 (十字星/小实体蓄势)
        body_pct = np.abs(market.close - market.open) / np.maximum(market.open, 1e-4)
        is_small_body = body_pct <= 0.035

        entry_bool = np.zeros(market.shape, dtype=bool)

        # 遍历涨停日距离当前条的偏移 k: k in [min_days, lookback]
        for k in range(min_days, lookback + 1):
            shifted_limit = valid_shift(is_limit.astype(np.float32), k, close_valid)
            limit_k_ago = np.nan_to_num(shifted_limit, nan=0.0) > 0.5
            limit_close_k_ago = valid_shift(market.close, k, close_valid)
            limit_vol_k_ago = valid_shift(market.volume, k, vol_valid)

            # 涨停后所有后续交易日（从 t-k+1 到 t 共 k 根 K 线）的最低价始终坚守涨停价
            min_low_k = valid_rolling_min(market.low, low_valid, k)

            holds = (
                np.isfinite(min_low_k)
                & np.isfinite(limit_close_k_ago)
                & (min_low_k >= limit_close_k_ago * 0.995)
            )

            # 价格处于健康蓄势区间（涨停价上沿 0% ~ 8% 内，不过度追高）
            near_support = (market.close >= limit_close_k_ago * 0.99) & (
                market.close <= limit_close_k_ago * 1.085
            )

            # 缩量验证：当日成交量比涨停日明显萎缩 (≤ 85%)
            vol_contract = np.isfinite(limit_vol_k_ago) & (
                market.volume <= np.maximum(limit_vol_k_ago * 0.85, 1.0)
            )

            cond = limit_k_ago & holds & near_support
            if require_doji:
                cond &= (is_small_body & vol_contract)

            entry_bool |= cond

        if only_single:
            entry_bool &= (limit_count_in_window == 1)

        return make_signal_matrix(
            market.shape,
            entry=entry_bool.astype(np.uint8),
            entry_signal_code=np.where(entry_bool, 0, -1).astype(np.int16),
            entry_signal_ids=("signal_limit_up",),
        )


MATRIX_STRATEGY = LimitUpHoldAboveStrategy()
