"""缩量踩20日均线十字星（亿利达主升战法）

形态特征：
1. 均线多头格局：20日均线向上推升 (MA20 >= MA20[T-3])，股价处于 MA20 之上或回踩 MA20。
2. 前期放量试盘：过去 3~15 个交易日内出现过首板或中大阳线拉升（涨幅 >= 5% 且量比 >= 1.2）。
3. 涨幅受控洗盘：距前期启动大阳最低价累计涨幅不超过 30%（处于低位洗盘蓄势区）。
4. 连续洗盘极度缩量：近期经历连续横盘洗盘，成交量极度萎缩（量比 <= 0.85 或 成交量缩至前期巨量的 1/2 以下）。
5. 精准踩线支撑：最低价触及或逼近 20 日均线 (Low <= MA20 * 1.015 且 Close >= MA20 * 0.985)。
6. 十字星企稳买点：当日 K 线实体涨跌幅 <= 2.0%，空头抛压耗尽，主力洗盘完成。
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
    "id": "ma20_pullback_doji",
    "name": "缩量踩20日均线十字星（亿利达战法）",
    "description": "首板试盘 + 涨幅<30%洗盘 + 极度缩量踩稳20日均线十字星买入 + 移动止盈",
    "tags": ["亿利达", "低吸", "20日均线", "十字星", "主力洗盘", "高盈亏比", "主升浪"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "params": [
        {
            "id": "min_surge_pct",
            "label": "前期突破大阳涨幅%",
            "type": "float",
            "default": 5.0,
            "min": 3.0,
            "max": 10.0,
            "step": 0.5,
        },
        {
            "id": "max_gain_since_surge",
            "label": "首板至今累计涨幅上限%",
            "type": "float",
            "default": 30.0,
            "min": 15.0,
            "max": 50.0,
            "step": 1.0,
        },
        {
            "id": "max_vol_ratio",
            "label": "洗盘量比上限",
            "type": "float",
            "default": 0.85,
            "min": 0.4,
            "max": 1.2,
            "step": 0.05,
        },
        {
            "id": "max_doji_body_pct",
            "label": "十字星实体上限%",
            "type": "float",
            "default": 2.0,
            "min": 0.5,
            "max": 4.0,
            "step": 0.5,
            },
        {
            "id": "bullish_ma_only",
            "label": "严格均线多头排列开仓",
            "type": "bool",
            "default": True,
        },
    ],
    "basic_filter": {
        "boards": ["沪主板", "深主板", "创业板", "科创板"],
        "exclude_st": True,
        "exclude_new_days": 30,
        "price_min": 3.0,
    },
    "scoring": {
        "momentum_20d": 0.45,
        "amount": 0.35,
        "vol_ratio_5d": -0.20,
    },
    "order_by": "score",
    "descending": True,
    "limit": 50,
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_doji_buy"]
EXIT_SIGNALS = ["signal_ma20_breakdown"]
STOP_LOSS = -0.06
TRAILING_TAKE_PROFIT_ACTIVATE = 0.07
TRAILING_TAKE_PROFIT_DRAWDOWN = 0.025
MAX_HOLD_DAYS = 5
ALERTS = []


class MA20PullbackDojiStrategy:
    def required_fields(self) -> frozenset[str]:
        return frozenset({"open", "high", "low", "close", "volume", "amount"})

    def required_warmup_bars(self, params: dict) -> int:
        del params
        return 60

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        min_surge_pct = float(params.get("min_surge_pct", 5.0)) / 100.0
        max_gain_pct = float(params.get("max_gain_since_surge", 30.0)) / 100.0
        max_vol_ratio = float(params.get("max_vol_ratio", 0.85))
        max_doji_body_pct = float(params.get("max_doji_body_pct", 2.0)) / 100.0
        bullish_ma_only = bool(params.get("bullish_ma_only", True))

        close = market.close
        open_ = market.open
        high = market.high
        low = market.low
        vol = market.volume
        amount = market.field("amount") if "amount" in market.fields else vol * close * 100

        vol_ratio = matrix_feature(market, "vol_ratio_5d")
        mom20 = matrix_feature(market, "momentum_20d")
        ma5 = matrix_feature(market, "ma5")
        ma10 = matrix_feature(market, "ma10")
        ma20 = matrix_feature(market, "ma20")
        ma60 = matrix_feature(market, "ma60")

        # 1. 严格均线多头排列 (Bullish Alignment: 必须满足均线多头顺排，非多头一律不买)
        # 5日线 > 10日线 > 20日线 > 60日线 (MA5 >= MA10 >= MA20 >= MA60)
        # 5日线向上, 10日线向上, 20日线向上, 股价站稳在 5日/10日/20日均线上方 (拒绝死叉与下行反弹)
        if bullish_ma_only:
            bullish_ma = (
                (ma5 >= ma10) &
                (ma10 >= ma20) &
                (ma20 >= ma60) &
                (ma5 >= shift(ma5, 1) * 0.998) &
                (ma10 >= shift(ma10, 1) * 0.998) &
                (ma20 >= shift(ma20, 2) * 0.998) &
                (close >= ma5 * 0.995) &
                (close >= ma10) &
                (close >= ma20) &
                (mom20 >= 0.06)
            )
        else:
            bullish_ma = (ma20 > ma60) & (ma20 >= shift(ma20, 3) * 0.995)

        # 2. 前期 3~12 天内出现过首板或放量突破大阳线
        had_big_surge = np.zeros_like(close, dtype=bool)
        lowest_since_surge = np.full_like(close, np.inf, dtype=np.float32)
        max_surge_vol = np.zeros_like(close, dtype=np.float32)
        for d in range(3, 13):
            c_d = shift(close, d)
            pc_d = shift(close, d + 1)
            l_d = shift(low, d)
            v_d = shift(vol, d)
            vr_d = shift(vol_ratio, d)
            surge = (c_d >= pc_d * (1.0 + min_surge_pct)) & (vr_d >= 1.2)
            had_big_surge |= surge
            lowest_since_surge = np.where(surge, l_d, lowest_since_surge)
            max_surge_vol = np.maximum(max_surge_vol, np.where(surge, v_d, 0))

        # 3. 累计涨幅未超过上限 (低位蓄势，非高位见顶)
        valid_low = np.isfinite(lowest_since_surge) & (lowest_since_surge > 0)
        denom = np.where(valid_low, lowest_since_surge, 1.0)
        gain_under_max = np.where(valid_low, (close - lowest_since_surge) / denom <= max_gain_pct, False)

        # 4. 连续洗盘成交量萎缩 (量比 <= max_vol_ratio 或 缩至巨量的 1/2 以下)
        shrink_vol = (vol_ratio <= max_vol_ratio) | (vol <= max_surge_vol * 0.45)

        # 5. 精准踩在 20 日均线上方获得有效支撑
        touch_ma20 = (low <= ma20 * 1.02) & (close >= ma20 * 0.995)

        # 6. 当日收出十字星企稳 K 线 (拒绝破位大阴线)
        body_pct = np.abs(close - open_) / np.where(open_ > 0, open_, 1.0)
        is_doji = (body_pct <= max_doji_body_pct) & (close >= open_ * 0.99)

        entry = bullish_ma & had_big_surge & gain_under_max & shrink_vol & touch_ma20 & is_doji & (amount >= 35_000_000)

        # 卖点: 收盘有效跌破 20 日生命线 (严格破位止损)
        exit_ = close < ma20 * 0.965

        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            exit=exit_.astype(np.uint8),
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            exit_signal_code=np.where(exit_, 0, -1).astype(np.int16),
            entry_signal_ids=("signal_doji_buy",),
            exit_signal_ids=("signal_ma20_breakdown",),
        )


MATRIX_STRATEGY = MA20PullbackDojiStrategy()
