# -*- coding: utf-8 -*-
"""涨停缩量大阴/十字星回踩均线尾盘低吸战法 (ShrinkBearReboundMA5MA10Strategy)。

核心交易逻辑：
1. 涨停基因：前 5 个交易日内曾发生过涨停板（主板≥9.6%，双创≥19.2%），确保主力资金高强度介入、股性极度活跃；
2. 洗盘蓄势（当天形态，15:00尾盘选出）：
   - 形态A（缩量大阴线）：当天收阴下跌洗盘（跌幅 -1.8% ~ -6.5%），但成交量较昨日显著萎缩（缩量≥25%），非主力出逃，而是假摔震仓；
   - 形态B（缩量十字星）：当天实体极短（振幅收敛、收出十字星/纺锤线），成交量同步萎缩，变盘蓄势；
3. 均线回踩（当天回踩企稳）：当天最低价精准回踩 5 日均线（进攻线）或 10 日均线（生命线），且收盘获得有效支撑（收在均线附近或上方）；
4. 尾盘入场：在当天 15:00 选出后，于 14:50~15:00 尾盘集合竞价或 15:00~15:30 盘后固定价格交易申报买入（收盘价成交）；
5. 隔日反包获利：博弈次日或第 3 日主力强势反包大阳线或反包涨停，短线快进快出，2~4 日内了结。
"""
from __future__ import annotations

import numpy as np

from app.backtest.matrix import (
    MarketDataMatrix,
    SignalMatrix,
    make_signal_matrix,
    matrix_feature,
    valid_shift as shift,
)

META = {
    "id": "shrink_bear_rebound_ma5_10",
    "name": "涨停缩量回踩尾盘低吸",
    "description": "前5日内有涨停板，当天收缩量大阴线或缩量十字星并回踩5日/10日均线企稳，15:00尾盘买入博弈反包",
    "tags": ["涨停洗盘", "缩量大阴", "十字星", "回踩MA5", "回踩MA10", "尾盘买入", "盘后定价", "低吸反包"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "params": [
        {
            "id": "lookback_limit_up",
            "label": "涨停回溯天数(交易日)",
            "type": "int",
            "default": 5,
            "min": 2,
            "max": 10,
            "step": 1,
        },
        {
            "id": "candle_pattern",
            "label": "当天洗盘K线形态",
            "type": "choice",
            "choices": ["both", "bear_only", "doji_only"],
            "default": "both",
        },
        {
            "id": "vol_shrink_ratio",
            "label": "当天成交量较昨日上限%",
            "type": "float",
            "default": 75.0,
            "min": 50.0,
            "max": 90.0,
            "step": 5.0,
        },
        {
            "id": "bear_min_drop_pct",
            "label": "大阴线最小跌幅%",
            "type": "float",
            "default": 1.8,
            "min": 1.0,
            "max": 5.0,
            "step": 0.2,
        },
        {
            "id": "doji_max_body_pct",
            "label": "十字星最大实体幅度%",
            "type": "float",
            "default": 1.2,
            "min": 0.5,
            "max": 2.0,
            "step": 0.1,
        },
        {
            "id": "support_choice",
            "label": "均线支撑类型",
            "type": "choice",
            "choices": ["ma5_or_ma10", "only_ma5", "only_ma10"],
            "default": "ma5_or_ma10",
        },
        {
            "id": "ma_touch_tolerance_pct",
            "label": "回踩均线容差%",
            "type": "float",
            "default": 1.8,
            "min": 0.5,
            "max": 3.5,
            "step": 0.2,
        },
        {
            "id": "require_ma10_up",
            "label": "要求10日均线走平或向上",
            "type": "bool",
            "default": True,
        },
    ],
    "basic_filter": {
        "exclude_st": True,
        "exclude_new_days": 30,
        "price_min": 3.0,
        "amount_min": 30000000.0,
    },
    "scoring": {
        "turnover_rate": 0.35,
        "vol_ratio_5d": 0.35,
        "momentum_20d": 0.30,
    },
    "order_by": "score",
    "descending": True,
    "limit": 5,
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_shrink_bear_ma_entry"]
EXIT_SIGNALS = ["signal_ma10_breakdown"]
DEFAULT_MATCHING = "close_t"
DEFAULT_ENTRY_FILL = "close_t"
STOP_LOSS = -0.038
TAKE_PROFIT = 0.075
TRAILING_TAKE_PROFIT_ACTIVATE = 0.038
TRAILING_TAKE_PROFIT_DRAWDOWN = 0.015
MAX_HOLD_DAYS = 3
ALERTS = []


class ShrinkBearReboundMA5MA10MatrixStrategy:
    """涨停缩量大阴/十字星回踩MA5/MA10尾盘低吸策略矩阵实现。"""

    def required_fields(self) -> frozenset[str]:
        return frozenset({"open", "high", "low", "close", "volume"})

    def required_warmup_bars(self, params: dict) -> int:
        del params
        return 35

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        rows, cols = market.shape

        # 参数提取
        lookback_limit_up = int(params.get("lookback_limit_up", 5))
        candle_pattern = str(params.get("candle_pattern", "both"))
        vol_shrink_ratio = float(params.get("vol_shrink_ratio", 75.0)) / 100.0
        bear_min_drop_pct = float(params.get("bear_min_drop_pct", 1.8)) / 100.0
        doji_max_body_pct = float(params.get("doji_max_body_pct", 1.2)) / 100.0
        support_choice = str(params.get("support_choice", "ma5_or_ma10"))
        ma_touch_tolerance_pct = float(params.get("ma_touch_tolerance_pct", 1.8)) / 100.0
        require_ma10_up = bool(params.get("require_ma10_up", True))

        # 基础指标与有效掩码
        close_valid = np.isfinite(market.close) & (market.close > 0)
        open_valid = np.isfinite(market.open) & (market.open > 0)
        low_valid = np.isfinite(market.low) & (market.low > 0)
        vol_valid = np.isfinite(market.volume) & (market.volume > 0)

        change_pct = matrix_feature(market, "change_pct")
        ma5 = matrix_feature(market, "ma5")
        ma10 = matrix_feature(market, "ma10")
        ma20 = matrix_feature(market, "ma20")

        # 1. 识别各板涨停 (主板>=9.6%, 创业板/科创板>=19.2%)
        is_20cm = np.array([s.startswith(("30", "68")) for s in market.symbols], dtype=bool)
        limit_threshold = np.where(is_20cm, 0.192, 0.096)
        limit_thresh_matrix = np.tile(limit_threshold, (rows, 1))
        is_limit_up = (change_pct >= limit_thresh_matrix) & close_valid

        # 回溯考察：近 1 至 lookback_limit_up 个交易日内（T-1 到 T-5）必须有涨停发生
        has_limit_up = np.zeros(market.shape, dtype=bool)
        is_limit_up_float = is_limit_up.astype(np.float32)
        for d in range(1, max(2, lookback_limit_up + 1)):
            has_limit_up |= (shift(is_limit_up_float, d) > 0.5)

        # 2. 当天 (T日) 缩量判定 (相较 T-1 日成交量萎缩至上限以下)
        prev1_vol = shift(market.volume, 1)
        is_shrunk = (market.volume <= prev1_vol * vol_shrink_ratio) & (prev1_vol > 0)

        # 实体幅度计算
        body_rate = (market.close - market.open) / np.where(open_valid, market.open, 1.0)
        abs_body_rate = np.abs(body_rate)

        # 2.1 当天形态 A：缩量大阴线 (收盘收阴，跌幅显著但非跌停踩踏)
        not_limit_down = change_pct > (-limit_thresh_matrix * 0.90)
        is_bear_candle = (
            (market.close < market.open)
            & ((change_pct <= -bear_min_drop_pct) | (body_rate <= -bear_min_drop_pct))
            & (change_pct >= -0.075)  # 避免跌幅过深破位
            & not_limit_down
            & is_shrunk
        )

        # 2.2 当天形态 B：缩量十字星 / 纺锤线 (实体极小，窄幅蓄势)
        is_doji_candle = (
            (abs_body_rate <= doji_max_body_pct)
            & (change_pct >= -0.025)
            & (change_pct <= 0.015)
            & is_shrunk
        )

        if candle_pattern == "bear_only":
            pattern_ok = is_bear_candle
        elif candle_pattern == "doji_only":
            pattern_ok = is_doji_candle
        else:
            pattern_ok = is_bear_candle | is_doji_candle

        # 3. 当天回踩 5 日均线或 10 日均线 (最低价触及或下探，收盘站稳在均线支撑区)
        touch_ma5 = (
            (market.low <= ma5 * (1.0 + ma_touch_tolerance_pct))
            & (market.close >= ma5 * 0.990)
        )

        touch_ma10 = (
            (market.low <= ma10 * (1.0 + ma_touch_tolerance_pct))
            & (market.close >= ma10 * 0.990)
        )

        if support_choice == "only_ma5":
            support_ok = touch_ma5
        elif support_choice == "only_ma10":
            support_ok = touch_ma10
        else:
            support_ok = touch_ma5 | touch_ma10

        # 4. 趋势与健康度过滤
        # MA10 趋势：走平或向上
        ma10_s1 = shift(ma10, 1)
        ma10_trend_ok = (ma10 >= ma10_s1 * 0.995) if require_ma10_up else np.ones(market.shape, dtype=bool)

        # 价格处于 MA20 生命周期上方或附近
        above_ma20 = market.close >= ma20 * 0.98

        # 5. 综合入场信号 (当天T日15:00发出，尾盘买入)
        entry = (
            has_limit_up
            & pattern_ok
            & support_ok
            & ma10_trend_ok
            & above_ma20
            & vol_valid
            & close_valid
            & open_valid
            & low_valid
        )

        # 6. 出场信号：收盘有效跌破 10 日均线 2.0%
        breakdown_ma10 = (market.close < ma10 * 0.98) & (shift(market.close, 1) >= shift(ma10, 1) * 0.98)
        exit_ = breakdown_ma10

        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            exit=exit_.astype(np.uint8),
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            exit_signal_code=np.where(breakdown_ma10, 0, -1).astype(np.int16),
            entry_signal_ids=("signal_shrink_bear_ma_entry",),
            exit_signal_ids=("signal_ma10_breakdown",),
        )


MATRIX_STRATEGY = ShrinkBearReboundMA5MA10MatrixStrategy()
