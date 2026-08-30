"""强势高开（早盘竞价跳空爆量起爆龙头）

筛选逻辑：
1. 早盘跳空高开 2.0% ~ 7.5%（主力抢筹黄金区间，排除一字封死无法买入）
2. 高开高走收真阳线（排除假高开低走杀跌大阴棒）
3. 站稳 5 日与 20 日生命线（多头趋势）
4. 放量进攻（成交量较前一日放大 ≥ 15%）
"""
from __future__ import annotations

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    SignalMatrix,
    make_signal_matrix,
    matrix_feature,
    valid_shift,
)

META = {
    "id": "strong_open",
    "name": "强势高开（早盘竞价起爆龙头）",
    "description": "早盘竞价跳空高开2%~7.5% + 放量高开高走真阳线 + 站稳生命线（高盈亏比主升浪起爆）",
    "tags": ["高开", "强势", "起爆", "集合竞价", "主升浪"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "params": [
        {
            "id": "min_open_gap",
            "label": "最低高开%",
            "type": "float",
            "default": 2.0,
            "min": 1.0,
            "max": 8.0,
            "step": 0.5,
        },
        {
            "id": "max_open_gap",
            "label": "最高高开%",
            "type": "float",
            "default": 7.5,
            "min": 4.0,
            "max": 10.0,
            "step": 0.5,
        },
        {
            "id": "require_red_candle",
            "label": "要求高开高走真阳线",
            "type": "bool",
            "default": True,
        },
        {
            "id": "require_vol_surge",
            "label": "要求成交量放大",
            "type": "bool",
            "default": True,
        },
    ],
    "basic_filter": {
        "boards": ["沪主板", "深主板", "创业板"],
        "exclude_st": True,
        "exclude_new_days": 30,
        "price_min": 3.0,
    },
    "scoring": {
        "amount": 0.40,
        "change_pct": 0.35,
        "momentum_20d": 0.25,
    },
    "order_by": "score",
    "descending": True,
    "limit": 30,
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_strong_open"]
EXIT_SIGNALS = ["signal_ma20_breakdown", "signal_ma_dead_5_20"]
STOP_LOSS = -0.04
TAKE_PROFIT = 0.18
TRAILING_TAKE_PROFIT_ACTIVATE = 0.08
TRAILING_TAKE_PROFIT_DRAWDOWN = 0.03
MAX_HOLD_DAYS = 5
ALERTS = []


class StrongOpenMatrixStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"open", "high", "low", "close", "volume"})

    def required_warmup_bars(self, params: dict) -> int:
        return 60

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        min_gap = float(params.get("min_open_gap", 2.0)) / 100.0
        max_gap = float(params.get("max_open_gap", 7.5)) / 100.0
        req_red = bool(params.get("require_red_candle", True))
        req_vol = bool(params.get("require_vol_surge", True))

        close_valid = np.isfinite(market.close)
        open_valid = np.isfinite(market.open) & (market.open > 0)
        vol_valid = np.isfinite(market.volume) & (market.volume > 0)

        prev_close = valid_shift(market.close, 1, close_valid)
        open_gap = (market.open - prev_close) / np.maximum(prev_close, 1e-4)

        # 1. 黄金高开区间
        gold_open = (open_gap >= min_gap) & (open_gap <= max_gap)

        # 2. 高开高走真阳线
        red_candle = market.close > market.open if req_red else np.ones(market.shape, dtype=bool)

        # 3. 站稳 MA5 与 MA20
        ma5 = matrix_feature(market, "ma5")
        ma20 = matrix_feature(market, "ma20")
        above_ma = (market.close > ma20) & (market.close > ma5)

        # 4. 放量
        prev_vol = valid_shift(market.volume, 1, vol_valid)
        vol_up = (market.volume >= prev_vol * 1.15) if req_vol else np.ones(market.shape, dtype=bool)

        entry_bool = gold_open & red_candle & above_ma & vol_up

        return make_signal_matrix(
            market.shape,
            entry=entry_bool.astype(np.uint8),
            entry_signal_code=np.where(entry_bool, 0, -1).astype(np.int16),
            entry_signal_ids=("signal_strong_open",),
        )


MATRIX_STRATEGY = StrongOpenMatrixStrategy()
