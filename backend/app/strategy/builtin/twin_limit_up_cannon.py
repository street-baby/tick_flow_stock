"""涨停双响炮蓄势起爆战法 (Twin Limit-Up Cannon Breakout)

形态与量化逻辑：
1. 【左炮立桩】：前 3 ~ 15 个交易日内出现涨停板大阳线（首板放量启动，奠定主力建仓基调）；
2. 【缩量洗盘】：左炮后经历 3 ~ 14 天窄幅洗盘（小阴小阳/十字星），最低价坚决守在左炮起爆价/20日均线上方，且成交量显著萎缩；
3. 【右炮起爆】：洗盘蓄势完毕后，再次放量涨停或大阳突破（一阳吞多线），开启主升浪或连板加速！
4. 【出场机制】：跌破 MA20 止损，跟踪止盈锁定主升浪利润。
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
    "id": "twin_limit_up_cannon",
    "name": "涨停双响炮蓄势起爆战法",
    "description": "左炮首板立桩 + 缩量洗盘不破底 + 回踩MA20企稳 + 右炮放量涨停反包主升",
    "tags": ["涨停双响炮", "主力资金", "缩量洗盘", "MA20支撑", "起爆点", "主升浪"],
    "asset_types": ["stock"],
    "timeframes": ["1d"],
    "params": [
        {
            "id": "min_left_limit_pct",
            "label": "左炮最低涨幅%",
            "type": "float",
            "default": 9.5,
            "min": 8.0,
            "max": 20.0,
            "step": 0.5,
        },
        {
            "id": "min_right_limit_pct",
            "label": "右炮最低涨幅%",
            "type": "float",
            "default": 9.5,
            "min": 8.0,
            "max": 20.0,
            "step": 0.5,
        },
        {
            "id": "max_middle_days",
            "label": "最长洗盘天数",
            "type": "int",
            "default": 14,
            "min": 3,
            "max": 20,
            "step": 1,
        },
        {
            "id": "min_middle_days",
            "label": "最短洗盘天数",
            "type": "int",
            "default": 3,
            "min": 2,
            "max": 10,
            "step": 1,
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
ENTRY_SIGNALS = ["signal_twin_cannon_buy"]
EXIT_SIGNALS = ["signal_ma20_breakdown"]
STOP_LOSS = -0.05
TRAILING_TAKE_PROFIT_ACTIVATE = 0.09
TRAILING_TAKE_PROFIT_DRAWDOWN = 0.03
MAX_HOLD_DAYS = 10
ALERTS = []


class TwinLimitUpCannonStrategy:
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

        min_left_pct = float(params.get("min_left_limit_pct", 9.5)) / 100.0
        min_right_pct = float(params.get("min_right_limit_pct", 9.5)) / 100.0
        min_mid_days = int(params.get("min_middle_days", 3))
        max_mid_days = int(params.get("max_middle_days", 14))

        T, N = close.shape

        # 1. 计算每日真实涨幅
        prev_close = shift(close, 1)
        daily_ret = np.where(prev_close > 0, (close - prev_close) / prev_close, 0.0)

        # 2. 右炮判断 (当日涨停/大阳放量突破)
        is_right_cannon = daily_ret >= min_right_pct

        # 3. 扫描前 3 ~ 14 天内的左炮与中间洗盘
        has_valid_left_cannon = np.zeros((T, N), dtype=bool)

        for k in range(min_mid_days, max_mid_days + 1):
            # k 天前的左炮
            left_ret = shift(daily_ret, k)
            left_open = shift(open_, k)
            left_low = shift(low, k)
            left_vol = shift(vol, k)

            is_left_bar = left_ret >= min_left_pct

            # 中间 k-1 天的最低价与成交量
            # 使用 shift 遍历中间各天
            mid_low_ok = np.ones((T, N), dtype=bool)
            mid_no_crash = np.ones((T, N), dtype=bool)

            left_floor = np.minimum(left_open, left_low) * 0.98

            for m in range(1, k):
                m_low = shift(low, m)
                m_ret = shift(daily_ret, m)
                # 洗盘期间不跌破左炮下沿
                mid_low_ok &= (m_low >= left_floor)
                # 洗盘期间没有单日大跌停 (跌幅 <= -7.5%)
                mid_no_crash &= (m_ret > -0.075)

            match_k = is_left_bar & mid_low_ok & mid_no_crash
            has_valid_left_cannon |= match_k

        # 4. 均线与大盘多头环境确认
        ma20_support = np.where(ma20 > 0, close >= ma20 * 0.96, True)
        close_valid = np.isfinite(close) & (close > 0)
        liquid = amount >= 20_000_000

        # 5. 买入信号：右炮 + 左炮洗盘形态确认 + MA20均线支撑 + 流动性充裕
        entry = is_right_cannon & has_valid_left_cannon & ma20_support & close_valid & liquid

        # 6. 卖出信号：收盘跌破 20日均线
        exit_ = np.where(ma20 > 0, close < ma20 * 0.95, False) & close_valid

        return make_signal_matrix(
            market.shape,
            entry=entry.astype(np.uint8),
            exit=exit_.astype(np.uint8),
            entry_signal_code=np.where(entry, 0, -1).astype(np.int16),
            exit_signal_code=np.where(exit_, 0, -1).astype(np.int16),
            entry_signal_ids=("signal_twin_cannon_buy",),
            exit_signal_ids=("signal_ma20_breakdown",),
        )


MATRIX_STRATEGY = TwinLimitUpCannonStrategy()

