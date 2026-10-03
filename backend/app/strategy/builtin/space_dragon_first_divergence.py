# -*- coding: utf-8 -*-
"""空间龙首日分歧选股与低吸战法 (SpaceDragonFirstDivergenceMatrixStrategy)。

核心实战业务逻辑：
1. 空间龙头基因（昨天四板或五板）：
   昨天处于 4 连板或 5 连板高标空间龙（可调整为 3~5 板），是市场最高辨识度的核心情绪标的；
2. 今日首日分歧（全部选出，不漏过任何分歧）：
   今日未能封住涨停板，首次出现分歧。不管是：
   - 出现跌停板（触及跌停或一字/换手跌停）
   - 出现大阴线（收跌 -5% ~ -8% 巨阴砸盘洗盘）
   - 出现冲高回落 / 假阴真阳 / 小阴小阳
   全部无遗漏筛选出来，供盘中或尾盘监控资金承接、寻找分歧日回踩低吸或跌停撬板（地天板/反核）机会；
3. 多维度分歧形态与回踩选择：
   - 默认模式：全部首日分歧一网打尽（含跌停、大阴线、断板未涨停）；
   - 可选模式：仅看跌停与大阴线、仅看首阴、或温和回踩；
4. 排序规则：
   连板高度优先（5板 > 4板）+ 充分换手率 + 大成交额。
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
    "id": "space_dragon_first_divergence",
    "name": "空间龙首日分歧低吸",
    "description": "昨天4板或5板空间龙，今日出现首日分歧（未涨停，包括跌停、大阴线、冲高回落等），全部筛选出来用于监控承接与回踩低吸",
    "tags": ["空间龙", "四板五板", "首日分歧", "首阴低吸", "跌停反核", "断板", "回踩买入", "弱转强"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "params": [
        {
            "id": "min_boards",
            "label": "昨天最少连板数",
            "type": "int",
            "default": 4,
            "min": 2,
            "max": 10,
            "step": 1,
        },
        {
            "id": "max_boards",
            "label": "昨天最多连板数",
            "type": "int",
            "default": 5,
            "min": 2,
            "max": 10,
            "step": 1,
        },
        {
            "id": "divergence_pattern",
            "label": "分歧形态要求",
            "type": "choice",
            "choices": ["all_divergence", "limit_down_or_big_bear", "bear_only", "broken_not_down"],
            "default": "all_divergence",
        },
        {
            "id": "support_type",
            "label": "回踩形态要求",
            "type": "choice",
            "choices": ["all_divergence", "has_intraday_dip", "pullback_ma5", "pullback_prev_board"],
            "default": "all_divergence",
        },
        {
            "id": "min_amount",
            "label": "分歧日最小成交额(万元)",
            "type": "float",
            "default": 3000.0,
            "min": 0.0,
            "max": 30000.0,
            "step": 1000.0,
        },
        {
            "id": "main_board_only",
            "label": "仅限沪深主板(10%连板生态)",
            "type": "bool",
            "default": True,
        },
    ],
    "basic_filter": {
        "exclude_st": True,
        "exclude_new_days": 30,
        "price_min": 1.0,
        "amount_min": 10000000.0,
    },
    "scoring": {
        "consecutive_limit_ups": 0.40,
        "turnover_rate": 0.35,
        "amount": 0.25,
    },
    "order_by": "score",
    "descending": True,
    "limit": 10,
}

EXECUTION_BACKEND = "matrix_native"
ENTRY_SIGNALS = ["signal_space_dragon_divergence_entry"]
EXIT_SIGNALS = ["signal_ma5_breakdown"]
DEFAULT_MATCHING = "close_t"
DEFAULT_ENTRY_FILL = "close_t"
STOP_LOSS = -0.060
TAKE_PROFIT = 0.098
TRAILING_TAKE_PROFIT_ACTIVATE = None
TRAILING_TAKE_PROFIT_DRAWDOWN = None
MAX_HOLD_DAYS = 2
ALERTS = []


class SpaceDragonFirstDivergenceMatrixStrategy:
    """空间龙首日分歧低吸策略矩阵实现。"""

    def required_fields(self) -> frozenset[str]:
        return frozenset({
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "consecutive_limit_ups",
        })

    def required_warmup_bars(self, params: dict) -> int:
        del params
        return 35

    def compute_signals(self, market: MarketDataMatrix, params: dict) -> SignalMatrix:
        rows, cols = market.shape

        # 参数提取
        min_boards = int(params.get("min_boards", 4))
        max_boards = int(params.get("max_boards", 5))
        divergence_pattern = str(params.get("divergence_pattern", "all_divergence"))
        support_type = str(params.get("support_type", "all_divergence"))
        min_amount = float(params.get("min_amount", 3000.0)) * 10000.0
        main_board_only = bool(params.get("main_board_only", True))

        # 基础数据有效性掩码
        close_valid = np.isfinite(market.close) & (market.close > 0)
        open_valid = np.isfinite(market.open) & (market.open > 0)
        low_valid = np.isfinite(market.low) & (market.low > 0)
        vol_valid = np.isfinite(market.volume) & (market.volume > 0)

        change_pct = matrix_feature(market, "change_pct")
        prev_close = shift(market.close, 1)
        ma5 = matrix_feature(market, "ma5")

        # 连板数特征
        consec = matrix_feature(market, "consecutive_limit_ups")
        prev_consec = shift(consec, 1)

        # 0. 板块过滤（主板优先）
        if main_board_only:
            is_main = np.zeros(market.shape, dtype=bool)
            for s_idx, sym in enumerate(market.symbols):
                code = sym.split(".")[0]
                if code.startswith(("000", "001", "002", "003", "600", "601", "603", "605")):
                    is_main[:, s_idx] = True
        else:
            is_main = np.ones(market.shape, dtype=bool)

        # 1. 空间龙基因判定：昨日处于 4 板或 5 板（或用户配置区间）
        is_space_dragon = (prev_consec >= min_boards) & (prev_consec <= max_boards)

        # 2. 今日首日分歧：今日未封死涨停板 (断板)
        is_broken = (consec == 0)

        # 3. 分歧形态判定（包含跌停、大阴线、小阴假阳、冲高回落）
        is_limit_down = (change_pct <= -0.095) | (market.low <= prev_close * 0.905)
        is_big_bear = (change_pct <= -0.050) | is_limit_down
        is_bear = (market.close < market.open) | (change_pct < 0)

        if divergence_pattern == "limit_down_or_big_bear":
            pattern_ok = is_big_bear
        elif divergence_pattern == "bear_only":
            pattern_ok = is_bear
        elif divergence_pattern == "broken_not_down":
            pattern_ok = ~is_limit_down
        else:  # all_divergence: 全部选出
            pattern_ok = np.ones(market.shape, dtype=bool)

        # 4. 回踩支撑/下探判定
        low_dip_rate = (market.low - prev_close) / np.where(prev_close > 0, prev_close, 1.0)
        has_dip = (low_dip_rate <= 0.0)  # 盘中出现下探昨收盘价以下
        pullback_prev_board = (low_dip_rate <= 0.005) & (market.close >= prev_close * 0.945)
        touch_ma5 = (market.low <= ma5 * 1.03) & (market.close >= ma5 * 0.95)

        if support_type == "has_intraday_dip":
            support_ok = has_dip
        elif support_type == "pullback_ma5":
            support_ok = touch_ma5
        elif support_type == "pullback_prev_board":
            support_ok = pullback_prev_board
        else:  # all_divergence: 不限回踩形态，全部选出
            support_ok = np.ones(market.shape, dtype=bool)

        # 5. 流动性与成交额过滤
        if "amount" in market.fields:
            amount = market.fields["amount"]
        else:
            amount = market.close * market.volume * 100.0
        liquidity_ok = amount >= min_amount

        # 6. 综合入场信号 (首日分歧全部选出)
        entry = (
            is_main
            & is_space_dragon
            & is_broken
            & pattern_ok
            & support_ok
            & liquidity_ok
            & vol_valid
            & close_valid
            & open_valid
            & low_valid
        )

        # 7. 出场信号：跌破 5 日均线
        breakdown_ma5 = (market.close < ma5 * 0.970) & (shift(market.close, 1) >= shift(ma5, 1) * 0.970)
        exit_ = breakdown_ma5

        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            exit=exit_.astype(np.uint8),
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            exit_signal_code=np.where(breakdown_ma5, 0, -1).astype(np.int16),
            entry_signal_ids=("signal_space_dragon_divergence_entry",),
            exit_signal_ids=("signal_ma5_breakdown",),
        )


MATRIX_STRATEGY = SpaceDragonFirstDivergenceMatrixStrategy()
