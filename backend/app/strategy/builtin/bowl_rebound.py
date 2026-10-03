# -*- coding: utf-8 -*-
"""碗口反弹策略 (BowlReboundStrategy) — 通达信经典形态与知行双线量化版。

结合通达信知行短期趋势线、知行多空线、前期放量阳线异动、剔除最大量阴线及KDJ低位超卖蓄势。
支持回落碗中、靠近多空线、靠近短期趋势线三档分类筛选，无缝接入矩阵加速引擎与B1形态相似度评估。
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
    "id": "bowl_rebound",
    "name": "碗口反弹策略",
    "description": "基于知行短期趋势线与多空线、前期放量阳线、剔除最大阴量、KDJ极度超卖回落蓄势，结合B1形态相似度排序的经典反弹策略",
    "tags": ["碗口反弹", "通达信", "KDJ超卖", "放量异动", "B1形态", "均线"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "params": [
        {
            "id": "N",
            "label": "放量异动倍数 (V >= 昨日 * N)",
            "type": "float",
            "default": 2.4,
            "min": 1.5,
            "max": 5.0,
            "step": 0.1,
        },
        {
            "id": "M",
            "label": "异动阳线回溯天数",
            "type": "int",
            "default": 20,
            "min": 5,
            "max": 40,
            "step": 1,
        },
        {
            "id": "J_VAL",
            "label": "KDJ-J值超卖上限",
            "type": "float",
            "default": 15.0,
            "min": -20.0,
            "max": 50.0,
            "step": 1.0,
        },
        {
            "id": "duokong_pct",
            "label": "靠近多空线容差 %",
            "type": "float",
            "default": 3.0,
            "min": 1.0,
            "max": 6.0,
            "step": 0.5,
        },
        {
            "id": "short_pct",
            "label": "靠近短期趋势线容差 %",
            "type": "float",
            "default": 2.0,
            "min": 0.5,
            "max": 5.0,
            "step": 0.5,
        },
        {
            "id": "require_trend_above",
            "label": "要求短期趋势线在多空线上方 (上升趋势)",
            "type": "bool",
            "default": True,
        },
        {
            "id": "exclude_max_vol_bear",
            "label": "剔除回顾期内最大量为阴线 (主力出逃)",
            "type": "bool",
            "default": True,
        },
    ],
    "scoring": {"momentum_20d": 0.35, "vol_ratio_5d": 0.35, "change_pct": 0.3},
    "order_by": "score",
    "descending": True,
    "limit": 100,
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_bowl_rebound_entry"]
EXIT_SIGNALS = ["signal_bowl_breakdown", "signal_ma_dead_5_20"]
STOP_LOSS = -0.05
MAX_HOLD_DAYS = 15
ALERTS = []


def _calc_matrix_ema(data: np.ndarray, span: int) -> np.ndarray:
    """计算 2D 矩阵 (bars, stocks) 的指数移动平均 EMA。"""
    alpha = 2.0 / (span + 1.0)
    ema = np.copy(data).astype(np.float32)
    for i in range(1, data.shape[0]):
        prev = ema[i - 1]
        curr = data[i]
        valid = np.isfinite(curr)
        ema[i] = np.where(valid, np.where(np.isfinite(prev), prev * (1.0 - alpha) + curr * alpha, curr), prev)
    return ema


def _calc_matrix_kdj(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    n: int = 9,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """计算 2D 矩阵的 KDJ(9,3,3) 指标。"""
    bars, stocks = close.shape
    llv = np.copy(low)
    hhv = np.copy(high)
    for d in range(1, n):
        llv = np.minimum(llv, shift(low, d))
        hhv = np.maximum(hhv, shift(high, d))

    denom = hhv - llv
    rsv = np.full((bars, stocks), 50.0, dtype=np.float32)
    valid_denom = denom > 1e-6
    np.divide(
        (close - llv) * 100.0,
        denom,
        out=rsv,
        where=valid_denom,
    )

    k = np.full((bars, stocks), 50.0, dtype=np.float32)
    d = np.full((bars, stocks), 50.0, dtype=np.float32)
    for i in range(1, bars):
        k[i] = (rsv[i] + 2.0 * k[i - 1]) / 3.0
        d[i] = (k[i] + 2.0 * d[i - 1]) / 3.0

    j = 3.0 * k - 2.0 * d
    return k, d, j


class BowlReboundMatrixStrategy:
    """碗口反弹矩阵策略实现。"""

    def required_fields(self) -> frozenset[str]:
        return frozenset({"open", "high", "low", "close", "volume"})

    def required_warmup_bars(self, params: dict) -> int:
        del params
        return 60

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        rows, cols = market.shape

        # 1. 均线计算
        ma5 = matrix_feature(market, "ma5")
        ma10 = matrix_feature(market, "ma10")
        ma20 = matrix_feature(market, "ma20")
        ma30 = matrix_feature(market, "ma30")

        # 2. 知行短期趋势线 = EMA(EMA(Close, 10), 10)
        ema_close_10 = _calc_matrix_ema(market.close, 10)
        zhixing_short = _calc_matrix_ema(ema_close_10, 10)

        # 3. 知行多空线 = (MA5 + MA10 + MA20 + MA30) / 4
        zhixing_bullbear = (ma5 + ma10 + ma20 + ma30) / 4.0

        # 4. KDJ 计算 (9,3,3)
        _, _, j_val = _calc_matrix_kdj(market.high, market.low, market.close, n=9)

        # 5. 上升趋势条件: 知行短期趋势线 > 知行多空线
        trend_above = zhixing_short > zhixing_bullbear
        if not params.get("require_trend_above", True):
            trend_above = np.ones(market.shape, dtype=bool)

        # 6. KDJ 超卖条件: J <= J_VAL
        j_thresh = float(params.get("J_VAL", 15.0))
        j_low = j_val <= j_thresh

        # 7. M天内放量阳线异动查找 (V >= REF(V, 1) * N 且 Close > Open)
        vol_multiple = float(params.get("N", 2.4))
        m_days = int(params.get("M", 20))

        # 判定单日是否放量阳线
        prev_vol = shift(market.volume, 1)
        is_vol_surge = (market.volume >= prev_vol * vol_multiple) & (prev_vol > 0)
        is_positive = market.close > market.open
        key_candle = is_vol_surge & is_positive

        # 回溯 M 天内是否存在 key_candle
        has_abnormal = np.zeros(market.shape, dtype=bool)
        key_candle_float = key_candle.astype(np.float32)
        for d in range(1, max(2, m_days + 1)):
            s_key = shift(key_candle_float, d)
            has_abnormal |= (s_key > 0.5)

        # 8. 剔除：若过去 M 天内最大成交量的一天是阴线 (主力出逃)
        if params.get("exclude_max_vol_bear", True):
            max_vol = np.zeros(market.shape, dtype=np.float32)
            max_vol_is_bear = np.zeros(market.shape, dtype=bool)
            for d in range(1, max(2, m_days + 1)):
                s_vol = np.nan_to_num(shift(market.volume, d), nan=0.0)
                s_close = shift(market.close, d)
                s_open = shift(market.open, d)
                s_is_bear = (s_close < s_open) & np.isfinite(s_close) & np.isfinite(s_open)

                is_new_max = s_vol > max_vol
                max_vol = np.where(is_new_max, s_vol, max_vol)
                max_vol_is_bear = np.where(is_new_max, s_is_bear, max_vol_is_bear)

            not_max_bear = ~max_vol_is_bear
        else:
            not_max_bear = np.ones(market.shape, dtype=bool)

        # 9. 位置分类条件 (满足其一即可入选)
        # ① 回落碗中: 多空线 <= Close <= 短期趋势线
        fall_in_bowl = (market.close >= zhixing_bullbear * 0.995) & (market.close <= zhixing_short * 1.005)

        # ② 靠近多空线: |Close - 多空线| / 多空线 <= duokong_pct%
        duokong_tol = float(params.get("duokong_pct", 3.0)) / 100.0
        near_duokong = np.abs(market.close - zhixing_bullbear) <= zhixing_bullbear * duokong_tol

        # ③ 靠近短期趋势线: |Close - 短期趋势线| / 短期趋势线 <= short_pct%
        short_tol = float(params.get("short_pct", 2.0)) / 100.0
        near_short = np.abs(market.close - zhixing_short) <= zhixing_short * short_tol

        position_match = fall_in_bowl | near_duokong | near_short

        # 10. 综合买入信号判定
        entry = (
            trend_above
            & j_low
            & has_abnormal
            & not_max_bear
            & position_match
            & (market.volume > 0)
            & np.isfinite(market.close)
        )

        # 11. 卖出信号: 收盘有效跌破多空线 1.5% 或 5日均线下穿20日均线
        breakdown_duokong = (market.close < zhixing_bullbear * 0.985) & (shift(market.close, 1) >= shift(zhixing_bullbear, 1) * 0.985)
        ma_dead = (ma5 < ma20) & (shift(ma5, 1) >= shift(ma20, 1))
        exit_ = breakdown_duokong | ma_dead

        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            exit=exit_.astype(np.uint8),
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            exit_signal_code=np.where(breakdown_duokong, 0, np.where(ma_dead, 1, -1)).astype(np.int16),
            entry_signal_ids=("signal_bowl_rebound_entry",),
            exit_signal_ids=("signal_bowl_breakdown", "signal_ma_dead_5_20"),
        )


MATRIX_STRATEGY = BowlReboundMatrixStrategy()
