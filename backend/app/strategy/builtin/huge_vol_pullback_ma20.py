"""巨量洗盘回踩MA20 — 前期巨量拉升后连阴缩量洗盘，阴线精准回踩MA20上方 + 成交量萎缩至巨量1/4左右"""

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    SignalMatrix,
    make_signal_matrix,
    matrix_feature,
)
from app.backtest.matrix import (
    valid_shift as shift,
)

META = {
    "id": "huge_vol_pullback_ma20",
    "name": "巨量洗盘回踩MA20",
    "description": "前期巨量拉升后连阴缩量洗盘，阴线回踩触及20日均线（MA20）且获得支撑，成交量萎缩至前期巨量的1/4左右地量蓄势",
    "tags": ["回踩", "均线", "地量", "洗盘", "MA20"],
    "asset_types": ["stock", "etf"],
    "timeframes": ["1d"],
    "params": [
        {
            "id": "require_consecutive_bears",
            "label": "要求近期连续阴线回踩 (2~3连阴)",
            "type": "bool",
            "default": True,
        },
        {
            "id": "ma20_touch_tolerance",
            "label": "MA20踩线容差%",
            "type": "float",
            "default": 2.5,
            "min": 0.5,
            "max": 6.0,
            "step": 0.5,
        },
        {
            "id": "max_vol_ratio_to_huge",
            "label": "回踩成交量占前期巨量上限%",
            "type": "float",
            "default": 35.0,
            "min": 15.0,
            "max": 50.0,
            "step": 5.0,
        },
        {
            "id": "huge_vol_window",
            "label": "前期巨量回溯天数 (3~N天前)",
            "type": "int",
            "default": 15,
            "min": 5,
            "max": 30,
            "step": 1,
        },
        {
            "id": "require_above_ma60",
            "label": "要求收盘价在MA60上方 (多头趋势)",
            "type": "bool",
            "default": True,
        },
    ],
    "scoring": {"momentum_20d": 0.4, "vol_ratio_5d": 0.3, "change_pct": 0.3},
    "order_by": "score",
    "descending": True,
    "limit": 100,
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_ma20_breakout"]
EXIT_SIGNALS = ["signal_ma20_breakdown", "signal_ma_dead_5_20"]
STOP_LOSS = -0.05
MAX_HOLD_DAYS = 15
ALERTS = []


class HugeVolPullbackMA20MatrixStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"open", "high", "low", "close", "volume"})

    def required_warmup_bars(self, params: dict) -> int:
        del params
        return 60

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        rows, cols = market.shape
        ma5 = matrix_feature(market, "ma5")
        ma20 = matrix_feature(market, "ma20")
        ma60 = matrix_feature(market, "ma60")

        # 1. 阴线判定: 当日收盘 < 开盘 (或收阴/十字微绿)
        is_bear_0 = (market.close < market.open) | (market.close < shift(market.close, 1))
        is_bear_1 = (shift(market.close, 1) < shift(market.open, 1)) | (shift(market.close, 1) < shift(market.close, 2))
        is_bear_2 = (shift(market.close, 2) < shift(market.open, 2)) | (shift(market.close, 2) < shift(market.close, 3))

        consecutive_bears = is_bear_0 & (is_bear_1 | is_bear_2)
        three_bears = is_bear_0 & is_bear_1 & is_bear_2

        # 2. 踩在 MA20 均线上方附近
        tolerance_pct = float(params.get("ma20_touch_tolerance", 2.5)) / 100.0
        # 最低价触碰/逼近 MA20 (low <= MA20 * (1 + tolerance)) 且 收盘未有效跌破 MA20 (close >= MA20 * 0.985)
        touch_ma20 = (
            (market.low <= ma20 * (1.0 + tolerance_pct))
            & (market.close >= ma20 * 0.985)
            & (market.low >= ma20 * 0.94)
        )

        # 3. 前期 2 ~ N 天内的最大巨量寻找
        window_len = int(params.get("huge_vol_window", 15))
        # 构造窗口内历史巨量数组 (回溯 t-2 至 t-window_len)
        max_huge_vol = np.zeros_like(market.volume)
        for d in range(2, max(3, window_len + 1)):
            s_vol = shift(market.volume, d)
            max_huge_vol = np.maximum(max_huge_vol, s_vol)

        # 4. 当前成交量萎缩至前期巨量的 1/4 左右 (<= max_vol_ratio_to_huge)
        max_ratio = float(params.get("max_vol_ratio_to_huge", 35.0)) / 100.0
        # 确保前期确实存在明显巨量 (巨量至少大于 0，且当前成交量萎缩到该巨量的 1/4 上下)
        is_shrunk_to_quarter = (max_huge_vol > 0) & (market.volume <= max_huge_vol * max_ratio)

        entry = np.ones(market.shape, dtype=bool)

        if params.get("require_consecutive_bears", True):
            entry &= consecutive_bears
        else:
            entry &= is_bear_0

        entry &= touch_ma20
        entry &= is_shrunk_to_quarter

        if params.get("require_above_ma60", True):
            entry &= market.close > ma60

        ma20_breakdown = (market.close < ma20) & (shift(market.close, 1) >= shift(ma20, 1))
        ma_dead = (ma5 < ma20) & (shift(ma5, 1) >= shift(ma20, 1))
        exit_ = ma20_breakdown | ma_dead

        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            exit=exit_.astype(np.uint8),
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            exit_signal_code=np.where(ma20_breakdown, 0, np.where(ma_dead, 1, -1)).astype(np.int16),
            entry_signal_ids=("signal_ma20_breakout",),
            exit_signal_ids=("signal_ma20_breakdown", "signal_ma_dead_5_20"),
        )


MATRIX_STRATEGY = HugeVolPullbackMA20MatrixStrategy()
