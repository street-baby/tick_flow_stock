"""MA金叉 — MA5上穿MA20 + 量能配合 + MA60上方"""

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
    "id": "ma_golden_cross",
    "name": "五日线穿过20日均线",
    "description": "5日均线（MA5）向上突破穿越20日均线（MA20）形成金叉，确立短期趋势由弱转强突破",
    "tags": ["均线", "金叉", "趋势转强"],
    "asset_types": ["stock", "etf"],
    "timeframes": ["1d"],
    "params": [
        {"id": "require_ma_golden", "label": "要求MA5上穿MA20", "type": "bool", "default": True},
        {"id": "use_volume_filter", "label": "启用量比过滤 (放量配合)", "type": "bool", "default": False},
        {
            "id": "vol_ratio_min",
            "label": "最低量比",
            "type": "float",
            "default": 1.0,
            "min": 0.5,
            "max": 5.0,
            "step": 0.1,
        },
        {
            "id": "require_above_ma60",
            "label": "要求收盘价在MA60上方 (中长期多头趋势)",
            "type": "bool",
            "default": False,
        },
    ],
    "scoring": {"momentum_20d": 0.4, "vol_ratio_5d": 0.3, "change_pct": 0.3},
    "order_by": "score",
    "descending": True,
    "limit": 100,
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_ma_golden_5_20"]
EXIT_SIGNALS = ["signal_ma_dead_5_20"]
STOP_LOSS = -0.06
MAX_HOLD_DAYS = 15
ALERTS = []


class MAGoldenCrossMatrixStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"close", "volume"})

    def required_warmup_bars(self, params: dict) -> int:
        del params
        return 60

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        ma5 = matrix_feature(market, "ma5")
        ma20 = matrix_feature(market, "ma20")
        golden = (ma5 > ma20) & (shift(ma5, 1) <= shift(ma20, 1))
        dead = (ma5 < ma20) & (shift(ma5, 1) >= shift(ma20, 1))
        entry = np.ones(market.shape, dtype=bool)
        if params.get("require_ma_golden", True):
            entry &= golden
        if params.get("use_volume_filter", True):
            entry &= matrix_feature(market, "vol_ratio_5d") >= float(
                params.get("vol_ratio_min", 1.2)
            )
        if params.get("require_above_ma60", True):
            entry &= market.close > matrix_feature(market, "ma60")
        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            exit=dead.astype(np.uint8),
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            exit_signal_code=np.where(dead, 0, -1).astype(np.int16),
            entry_signal_ids=("signal_ma_golden_5_20",),
            exit_signal_ids=("signal_ma_dead_5_20",),
        )


MATRIX_STRATEGY = MAGoldenCrossMatrixStrategy()
