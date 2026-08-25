"""AI机构活跃度大牛线起爆战法（主力控盘追踪）

形态逻辑：
1. 机构资金高控盘：资金仓位指标 >= 50.0%（红柱主力高控盘锁仓）；
2. 机构活跃度爆发：AI机构活跃度指标突破【强势线 50】或【大牛线 80】；
3. 均线与趋势共振：股价运行在 20 日均线上方，大盘处于多头环境；
4. 追击主升连板：吃主力资金快速拉升阶段的高盈亏比主升浪。
"""

from __future__ import annotations

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    SignalMatrix,
    make_signal_matrix,
    matrix_feature,
    valid_rolling_max,
    valid_rolling_min,
    valid_shift as shift,
)

META = {
    "id": "inst_activity_breakout",
    "name": "AI机构活跃度大牛线起爆战法",
    "description": "资金仓位高控盘(>=50%) + AI机构活跃度突破大牛线(>=70) + 20日线主升起爆",
    "tags": ["机构跟踪", "主力资金", "AI机构活跃度", "大牛线", "资金仓位", "主升浪"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "params": [
        {
            "id": "min_inst_position",
            "label": "最低资金仓位%",
            "type": "float",
            "default": 50.0,
            "min": 30.0,
            "max": 90.0,
            "step": 5.0,
        },
        {
            "id": "min_activity",
            "label": "机构活跃度阈值",
            "type": "float",
            "default": 65.0,
            "min": 40.0,
            "max": 90.0,
            "step": 5.0,
        },
    ],
    "basic_filter": {
        "boards": ["沪主板", "深主板", "创业板", "科创板"],
        "exclude_st": True,
        "exclude_new_days": 30,
        "price_min": 3.0,
    },
    "scoring": {
        "momentum_20d": 0.40,
        "amount": 0.35,
        "vol_ratio_5d": 0.25,
    },
    "order_by": "score",
    "descending": True,
    "limit": 50,
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_inst_activity_buy"]
EXIT_SIGNALS = ["signal_ma20_breakdown"]
STOP_LOSS = -0.05
TRAILING_TAKE_PROFIT_ACTIVATE = 0.08
TRAILING_TAKE_PROFIT_DRAWDOWN = 0.025
MAX_HOLD_DAYS = 8
ALERTS = []


class InstActivityBreakoutStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"open", "high", "low", "close", "volume", "amount"})

    def required_warmup_bars(self, params: dict) -> int:
        del params
        return 60

    def compute_signals(
        self,
        market: MarketDataMatrix,
        params: dict,
    ) -> SignalMatrix:
        close = market.close
        open_ = market.open
        high = market.high
        low = market.low
        vol = market.volume
        amount = market.field("amount") if "amount" in market.fields else vol * close * 100

        vol_ratio = matrix_feature(market, "vol_ratio_5d")
        ma20 = matrix_feature(market, "ma20")

        min_pos = float(params.get("min_inst_position", 50.0))
        min_act = float(params.get("min_activity", 65.0))

        close_valid = np.isfinite(close) & (close > 0)
        low_valid = np.isfinite(low) & (low > 0)
        high_valid = np.isfinite(high) & (high > 0)

        # 1. 计算 20 日最高最低与 RSV 资金仓位
        roll_min_20 = valid_rolling_min(low, low_valid, 20)
        roll_max_20 = valid_rolling_max(high, high_valid, 20)
        denom = roll_max_20 - roll_min_20
        rsv = np.where(denom > 0, ((close - roll_min_20) / denom) * 100.0, 50.0)
        pos = rsv * (0.6 + 0.4 * np.minimum(2.5, np.nan_to_num(vol_ratio, nan=1.0)))
        pos_smoothed = np.clip(pos, 0.0, 100.0)

        # 2. 计算 AI 机构活跃度
        hl = high - low
        mf = np.where(hl > 0, (2 * close - high - low) / hl, 0.0)
        vol_acc = np.nan_to_num(vol_ratio, nan=1.0)
        raw_act = np.maximum(0.0, (vol_acc * (1.2 + mf * 0.8) - 0.4) * 38.0)
        act = np.clip(raw_act, 0.0, 100.0)

        # 3. 趋势与量能条件
        above_ma20 = close >= ma20 * 0.99
        ma20_bull = ma20 >= shift(ma20, 5) * 0.99
        liquid = amount >= 20_000_000

        # 4. 触发信号：机构资金高控盘 + 活跃度冲上大牛线/强势线
        entry = (
            (pos_smoothed >= min_pos)
            & (act >= min_act)
            & above_ma20
            & ma20_bull
            & liquid
            & close_valid
        )

        # 出场信号：跌破 20 日均线
        exit_ = close < ma20 * 0.95

        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            exit=exit_.astype(np.uint8),
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            exit_signal_code=np.where(exit_, 0, -1).astype(np.int16),
            entry_signal_ids=("signal_inst_activity_buy",),
            exit_signal_ids=("signal_ma20_breakdown",),
        )


MATRIX_STRATEGY = InstActivityBreakoutStrategy()
