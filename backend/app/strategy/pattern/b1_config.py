# -*- coding: utf-8 -*-
"""B1 完美图形配置管理与案例库。

基于通达信/akshare A股量化选股系统的 10 个历史成功标杆案例特征。
用于对通过碗口反弹初筛的股票进行多维度相似度评分与排名。
"""
from __future__ import annotations

from typing import Any

# 10 个历史成功案例标准特征配置
B1_PERFECT_CASES: list[dict[str, Any]] = [
    {
        "id": "case_001",
        "name": "华纳药厂",
        "code": "688799",
        "breakout_date": "2025-05-12",
        "lookback_days": 25,
        "tags": ["科创板", "医药", "杯柄突破"],
        "description": "杯型整理 + 缩量地量蓄势 + KDJ极端超卖J值低位",
        "features": {
            "trend_structure": {
                "short_vs_bullbear": 1.035,
                "short_slope": 1.8,
                "bullbear_slope": 0.8,
                "price_vs_short_pct": -1.2,
                "price_vs_bullbear_pct": 2.1,
                "is_in_bowl": True,
                "trend_spread_pct": 3.4,
                "price_bias_pct": 0.4,
            },
            "kdj_state": {
                "j_value": -5.2,
                "j_position": "低位",
                "k_cross_d": False,
                "j_trend": -1.5,
            },
            "volume_pattern": {
                "avg_volume_ratio": 0.65,
                "volume_trend": "缩量后放量",
                "shrink_then_expand": True,
                "max_volume_ratio": 3.2,
            },
            "price_shape": {
                "max_drawdown": 8.5,
                "breakout_strength": 1.2,
                "overall_trend": "震荡",
            },
        },
    },
    {
        "id": "case_002",
        "name": "宁波韵升",
        "code": "600366",
        "breakout_date": "2025-08-06",
        "lookback_days": 25,
        "tags": ["主板", "稀土永磁", "均线回踩"],
        "description": "回落短期趋势线支撑 + 量能平稳 + J值中低位企稳",
        "features": {
            "trend_structure": {
                "short_vs_bullbear": 1.052,
                "short_slope": 2.5,
                "bullbear_slope": 1.2,
                "price_vs_short_pct": 0.2,
                "price_vs_bullbear_pct": 5.4,
                "is_in_bowl": False,
                "trend_spread_pct": 5.1,
                "price_bias_pct": 2.7,
            },
            "kdj_state": {
                "j_value": 12.5,
                "j_position": "中位",
                "k_cross_d": True,
                "j_trend": 2.8,
            },
            "volume_pattern": {
                "avg_volume_ratio": 0.95,
                "volume_trend": "量能平稳",
                "shrink_then_expand": False,
                "max_volume_ratio": 2.8,
            },
            "price_shape": {
                "max_drawdown": 6.2,
                "breakout_strength": 2.5,
                "overall_trend": "上升",
            },
        },
    },
    {
        "id": "case_003",
        "name": "微芯生物",
        "code": "688321",
        "breakout_date": "2025-06-20",
        "lookback_days": 25,
        "tags": ["科创板", "医药", "平台蓄势"],
        "description": "长期箱体平台整理 + 极度缩量后异动放量 + J值超卖回升",
        "features": {
            "trend_structure": {
                "short_vs_bullbear": 1.028,
                "short_slope": 1.2,
                "bullbear_slope": 0.5,
                "price_vs_short_pct": -0.8,
                "price_vs_bullbear_pct": 1.9,
                "is_in_bowl": True,
                "trend_spread_pct": 2.7,
                "price_bias_pct": 0.5,
            },
            "kdj_state": {
                "j_value": 4.5,
                "j_position": "低位",
                "k_cross_d": True,
                "j_trend": 1.9,
            },
            "volume_pattern": {
                "avg_volume_ratio": 0.72,
                "volume_trend": "缩量后放量",
                "shrink_then_expand": True,
                "max_volume_ratio": 3.8,
            },
            "price_shape": {
                "max_drawdown": 5.8,
                "breakout_strength": 1.8,
                "overall_trend": "震荡",
            },
        },
    },
    {
        "id": "case_004",
        "name": "方正科技",
        "code": "600601",
        "breakout_date": "2025-07-23",
        "lookback_days": 25,
        "tags": ["主板", "半导体/算力", "多空线支撑"],
        "description": "精准踩在多空线上方 + 浮筹洗净量能平稳 + J值中位蓄势",
        "features": {
            "trend_structure": {
                "short_vs_bullbear": 1.041,
                "short_slope": 2.1,
                "bullbear_slope": 1.1,
                "price_vs_short_pct": -1.8,
                "price_vs_bullbear_pct": 0.9,
                "is_in_bowl": True,
                "trend_spread_pct": 4.0,
                "price_bias_pct": -0.4,
            },
            "kdj_state": {
                "j_value": 16.8,
                "j_position": "中位",
                "k_cross_d": False,
                "j_trend": 0.8,
            },
            "volume_pattern": {
                "avg_volume_ratio": 0.88,
                "volume_trend": "量能平稳",
                "shrink_then_expand": False,
                "max_volume_ratio": 2.6,
            },
            "price_shape": {
                "max_drawdown": 9.2,
                "breakout_strength": 1.4,
                "overall_trend": "震荡",
            },
        },
    },
    {
        "id": "case_005",
        "name": "澄天伟业",
        "code": "300689",
        "breakout_date": "2025-07-15",
        "lookback_days": 25,
        "tags": ["创业板", "芯片", "地量变盘"],
        "description": "连续多日缩量地量 + 价格窄幅箱体震荡 + J值探底企稳",
        "features": {
            "trend_structure": {
                "short_vs_bullbear": 1.018,
                "short_slope": 0.6,
                "bullbear_slope": 0.4,
                "price_vs_short_pct": -0.5,
                "price_vs_bullbear_pct": 1.2,
                "is_in_bowl": True,
                "trend_spread_pct": 1.7,
                "price_bias_pct": 0.3,
            },
            "kdj_state": {
                "j_value": -2.1,
                "j_position": "低位",
                "k_cross_d": True,
                "j_trend": 1.2,
            },
            "volume_pattern": {
                "avg_volume_ratio": 0.58,
                "volume_trend": "持续缩量",
                "shrink_then_expand": False,
                "max_volume_ratio": 2.1,
            },
            "price_shape": {
                "max_drawdown": 7.1,
                "breakout_strength": 0.9,
                "overall_trend": "震荡",
            },
        },
    },
    {
        "id": "case_006",
        "name": "国轩高科",
        "code": "002074",
        "breakout_date": "2025-08-04",
        "lookback_days": 25,
        "tags": ["主板", "固态电池/锂电", "趋势中继"],
        "description": "靠近短期趋势线 + 量价健康无异常抛压 + J值低位转折",
        "features": {
            "trend_structure": {
                "short_vs_bullbear": 1.065,
                "short_slope": 3.2,
                "bullbear_slope": 1.8,
                "price_vs_short_pct": 0.4,
                "price_vs_bullbear_pct": 6.8,
                "is_in_bowl": False,
                "trend_spread_pct": 6.3,
                "price_bias_pct": 3.5,
            },
            "kdj_state": {
                "j_value": 8.6,
                "j_position": "低位",
                "k_cross_d": True,
                "j_trend": 3.4,
            },
            "volume_pattern": {
                "avg_volume_ratio": 1.05,
                "volume_trend": "量能平稳",
                "shrink_then_expand": False,
                "max_volume_ratio": 2.9,
            },
            "price_shape": {
                "max_drawdown": 5.4,
                "breakout_strength": 3.1,
                "overall_trend": "上升",
            },
        },
    },
    {
        "id": "case_007",
        "name": "野马电池",
        "code": "605378",
        "breakout_date": "2025-08-01",
        "lookback_days": 25,
        "tags": ["主板", "储能", "深蹲起跳"],
        "description": "持续洗盘缩量 + J值深度负值超跌 + 趋势线上移支撑",
        "features": {
            "trend_structure": {
                "short_vs_bullbear": 1.022,
                "short_slope": 0.9,
                "bullbear_slope": 0.6,
                "price_vs_short_pct": -1.9,
                "price_vs_bullbear_pct": 0.3,
                "is_in_bowl": True,
                "trend_spread_pct": 2.1,
                "price_bias_pct": -0.8,
            },
            "kdj_state": {
                "j_value": -9.8,
                "j_position": "低位",
                "k_cross_d": False,
                "j_trend": -0.5,
            },
            "volume_pattern": {
                "avg_volume_ratio": 0.52,
                "volume_trend": "持续缩量",
                "shrink_then_expand": False,
                "max_volume_ratio": 2.3,
            },
            "price_shape": {
                "max_drawdown": 11.2,
                "breakout_strength": 0.5,
                "overall_trend": "震荡",
            },
        },
    },
    {
        "id": "case_008",
        "name": "光电股份",
        "code": "600184",
        "breakout_date": "2025-07-10",
        "lookback_days": 25,
        "tags": ["主板", "军工装备", "二波启动"],
        "description": "缩量洗盘后首阳放量 + J值超卖金叉 + 趋势加速上行",
        "features": {
            "trend_structure": {
                "short_vs_bullbear": 1.078,
                "short_slope": 3.8,
                "bullbear_slope": 2.0,
                "price_vs_short_pct": 1.1,
                "price_vs_bullbear_pct": 8.9,
                "is_in_bowl": False,
                "trend_spread_pct": 7.6,
                "price_bias_pct": 4.8,
            },
            "kdj_state": {
                "j_value": 14.2,
                "j_position": "中位",
                "k_cross_d": True,
                "j_trend": 4.1,
            },
            "volume_pattern": {
                "avg_volume_ratio": 1.25,
                "volume_trend": "缩量后放量",
                "shrink_then_expand": True,
                "max_volume_ratio": 4.2,
            },
            "price_shape": {
                "max_drawdown": 6.8,
                "breakout_strength": 3.9,
                "overall_trend": "上升",
            },
        },
    },
    {
        "id": "case_009",
        "name": "新瀚新材",
        "code": "301076",
        "breakout_date": "2025-08-01",
        "lookback_days": 25,
        "tags": ["创业板", "新材料", "均线粘合突破"],
        "description": "缩量后首根倍量突破 + 价格贴着短期趋势线 + 蓄势充分",
        "features": {
            "trend_structure": {
                "short_vs_bullbear": 1.038,
                "short_slope": 1.9,
                "bullbear_slope": 1.0,
                "price_vs_short_pct": 0.5,
                "price_vs_bullbear_pct": 4.3,
                "is_in_bowl": False,
                "trend_spread_pct": 3.7,
                "price_bias_pct": 2.3,
            },
            "kdj_state": {
                "j_value": 18.5,
                "j_position": "中位",
                "k_cross_d": True,
                "j_trend": 2.2,
            },
            "volume_pattern": {
                "avg_volume_ratio": 1.10,
                "volume_trend": "缩量后放量",
                "shrink_then_expand": True,
                "max_volume_ratio": 3.5,
            },
            "price_shape": {
                "max_drawdown": 7.5,
                "breakout_strength": 2.8,
                "overall_trend": "上升",
            },
        },
    },
    {
        "id": "case_010",
        "name": "航天发展",
        "code": "000547",
        "breakout_date": "2025-11-12",
        "lookback_days": 25,
        "tags": ["主板", "商业航天/军工", "回落碗中"],
        "description": "回落短期趋势线与多空线夹角碗中 + J值极度恐慌 + 主力倍量护盘",
        "features": {
            "trend_structure": {
                "short_vs_bullbear": 1.045,
                "short_slope": 2.2,
                "bullbear_slope": 1.2,
                "price_vs_short_pct": -1.4,
                "price_vs_bullbear_pct": 2.9,
                "is_in_bowl": True,
                "trend_spread_pct": 4.3,
                "price_bias_pct": 0.7,
            },
            "kdj_state": {
                "j_value": 1.2,
                "j_position": "低位",
                "k_cross_d": True,
                "j_trend": 1.8,
            },
            "volume_pattern": {
                "avg_volume_ratio": 0.85,
                "volume_trend": "缩量后放量",
                "shrink_then_expand": True,
                "max_volume_ratio": 3.6,
            },
            "price_shape": {
                "max_drawdown": 8.1,
                "breakout_strength": 2.1,
                "overall_trend": "震荡",
            },
        },
    },
]

# 四维相似度权重分配
SIMILARITY_WEIGHTS: dict[str, float] = {
    "trend_structure": 0.30,  # 双线结构（30%）
    "kdj_state": 0.20,        # KDJ动能（20%）
    "volume_pattern": 0.25,   # 量能特征（25%）
    "price_shape": 0.25,      # 价格形态（25%）
}

# 容差配置
MATCH_TOLERANCES: dict[str, float] = {
    "trend_ratio": 0.10,  # 趋势比值容差（±10%）
    "price_bias": 10.0,   # 价格偏离容差（±10%）
    "trend_spread": 10.0, # 趋势发散容差（±10%）
    "j_value": 30.0,      # J值差异容差（±30）
    "drawdown": 15.0,     # 回撤幅度容差（±15%）
}
