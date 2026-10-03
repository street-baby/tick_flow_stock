# -*- coding: utf-8 -*-
"""B1 完美图形多维形态匹配引擎。

使用四维特征体系（双线结构、KDJ动能、量能特征、DTW价格形态）进行相似度计算。
无需额外 C 扩展依赖，纯 NumPy 动态规整加速，毫秒级比对标杆大牛股案例。
"""
from __future__ import annotations

from typing import Any
import numpy as np

from app.strategy.pattern.b1_config import (
    B1_PERFECT_CASES,
    MATCH_TOLERANCES,
    SIMILARITY_WEIGHTS,
)


def dtw_similarity(s1: np.ndarray, s2: np.ndarray) -> float:
    """计算两个价格序列的 DTW（动态时间规整）形态相似度，返回 0.0 ~ 1.0。"""
    if len(s1) < 2 or len(s2) < 2:
        return 0.5

    # 归一化到 [0, 1]
    min1, max1 = np.min(s1), np.max(s1)
    min2, max2 = np.min(s2), np.max(s2)
    s1_norm = (s1 - min1) / (max1 - min1 + 1e-6)
    s2_norm = (s2 - min2) / (max2 - min2 + 1e-6)

    n, m = len(s1_norm), len(s2_norm)
    dtw = np.full((n + 1, m + 1), np.inf, dtype=np.float32)
    dtw[0, 0] = 0.0

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = abs(s1_norm[i - 1] - s2_norm[j - 1])
            dtw[i, j] = cost + min(dtw[i - 1, j], dtw[i, j - 1], dtw[i - 1, j - 1])

    max_len = max(n, m)
    dist = float(dtw[n, m])
    return float(max(0.0, min(1.0, 1.0 - dist / (max_len * 0.8 + 1e-6))))


class B1PatternMatcher:
    """B1 完美图形匹配器。"""

    def __init__(
        self,
        weights: dict[str, float] | None = None,
        tolerances: dict[str, float] | None = None,
    ):
        self.weights = weights or SIMILARITY_WEIGHTS
        self.tolerances = tolerances or MATCH_TOLERANCES
        self.cases = B1_PERFECT_CASES

    def match_features(self, cand: dict[str, Any], case_features: dict[str, Any]) -> dict[str, Any]:
        """计算候选特征与单个案例特征的相似度得分。"""
        scores: dict[str, float] = {}

        # 1. 知行趋势线双线结构相似度 (30%)
        cand_ts = cand.get("trend_structure", {})
        case_ts = case_features.get("trend_structure", {})
        if cand_ts and case_ts:
            scores["trend_structure"] = self._calc_trend_similarity(cand_ts, case_ts)
        else:
            scores["trend_structure"] = 0.5

        # 2. KDJ 动能状态相似度 (20%)
        cand_kdj = cand.get("kdj_state", {})
        case_kdj = case_features.get("kdj_state", {})
        if cand_kdj and case_kdj:
            scores["kdj_state"] = self._calc_kdj_similarity(cand_kdj, case_kdj)
        else:
            scores["kdj_state"] = 0.5

        # 3. 量能特征相似度 (25%)
        cand_vol = cand.get("volume_pattern", {})
        case_vol = case_features.get("volume_pattern", {})
        if cand_vol and case_vol:
            scores["volume_pattern"] = self._calc_volume_similarity(cand_vol, case_vol)
        else:
            scores["volume_pattern"] = 0.5

        # 4. 价格形态相似度 (25%)
        cand_shape = cand.get("price_shape", {})
        case_shape = case_features.get("price_shape", {})
        if cand_shape and case_shape:
            scores["price_shape"] = self._calc_shape_similarity(cand_shape, case_shape)
        else:
            scores["price_shape"] = 0.5

        # 加权总分 (0~100)
        total = sum(scores[k] * self.weights.get(k, 0.25) for k in scores)
        return {
            "total_score": round(float(total * 100.0), 1),
            "breakdown": {k: round(float(v * 100.0), 1) for k, v in scores.items()},
        }

    def _calc_trend_similarity(self, cand: dict[str, Any], case: dict[str, Any]) -> float:
        sims: list[float] = []
        trend_ratio_tol = self.tolerances.get("trend_ratio", 0.10)
        price_bias_tol = self.tolerances.get("price_bias", 10.0)
        trend_spread_tol = self.tolerances.get("trend_spread", 10.0)

        # short_vs_bullbear 比值
        if "short_vs_bullbear" in cand and "short_vs_bullbear" in case:
            diff = abs(cand["short_vs_bullbear"] - case["short_vs_bullbear"])
            sims.append(max(0.0, 1.0 - diff / trend_ratio_tol))

        # 斜率方向同向性
        if "short_slope" in cand and "short_slope" in case:
            same_dir = (cand["short_slope"] > 0) == (case["short_slope"] > 0)
            diff = abs(cand["short_slope"] - case["short_slope"])
            sims.append(max(0.7, 1.0 - diff / 10.0) if same_dir else max(0.0, 0.3 - diff / 20.0))

        # 是否在碗中一致性
        if "is_in_bowl" in cand and "is_in_bowl" in case:
            sims.append(1.0 if cand["is_in_bowl"] == case["is_in_bowl"] else 0.4)

        # 价格偏离多空线/短期趋势线
        if "price_bias_pct" in cand and "price_bias_pct" in case:
            diff = abs(cand["price_bias_pct"] - case["price_bias_pct"])
            sims.append(max(0.0, 1.0 - diff / price_bias_tol))

        # 趋势发散度
        if "trend_spread_pct" in cand and "trend_spread_pct" in case:
            diff = abs(cand["trend_spread_pct"] - case["trend_spread_pct"])
            sims.append(max(0.0, 1.0 - diff / trend_spread_tol))

        return float(np.mean(sims)) if sims else 0.5

    def _calc_kdj_similarity(self, cand: dict[str, Any], case: dict[str, Any]) -> float:
        sims: list[float] = []
        j_tol = self.tolerances.get("j_value", 30.0)

        # J值位置
        cand_pos = cand.get("j_position", "中位")
        case_pos = case.get("j_position", "中位")
        if cand_pos == case_pos:
            sims.append(1.0)
        elif {cand_pos, case_pos} == {"低位", "中位"}:
            sims.append(0.75)
        else:
            sims.append(0.4)

        # J数值绝对差
        if "j_value" in cand and "j_value" in case:
            diff = abs(cand["j_value"] - case["j_value"])
            sims.append(max(0.0, 1.0 - diff / j_tol))

        # 金叉状态
        if "k_cross_d" in cand and "k_cross_d" in case:
            sims.append(1.0 if cand["k_cross_d"] == case["k_cross_d"] else 0.6)

        return float(np.mean(sims)) if sims else 0.5

    def _calc_volume_similarity(self, cand: dict[str, Any], case: dict[str, Any]) -> float:
        sims: list[float] = []
        # 均量比
        if "avg_volume_ratio" in cand and "avg_volume_ratio" in case:
            diff = abs(cand["avg_volume_ratio"] - case["avg_volume_ratio"])
            sims.append(max(0.0, 1.0 - diff / 1.5))

        # 缩量后放量模式
        if cand.get("shrink_then_expand") and case.get("shrink_then_expand"):
            sims.append(1.0)
        elif cand.get("volume_trend") == case.get("volume_trend"):
            sims.append(0.85)
        else:
            sims.append(0.5)

        # 最大量比
        if "max_volume_ratio" in cand and "max_volume_ratio" in case:
            diff = abs(cand["max_volume_ratio"] - case["max_volume_ratio"])
            sims.append(max(0.0, 1.0 - diff / 3.0))

        return float(np.mean(sims)) if sims else 0.5

    def _calc_shape_similarity(self, cand: dict[str, Any], case: dict[str, Any]) -> float:
        sims: list[float] = []
        dd_tol = self.tolerances.get("drawdown", 15.0)

        # 最大回撤
        if "max_drawdown" in cand and "max_drawdown" in case:
            diff = abs(cand["max_drawdown"] - case["max_drawdown"])
            sims.append(max(0.0, 1.0 - diff / dd_tol))

        # 整体趋势
        if cand.get("overall_trend") == case.get("overall_trend"):
            sims.append(1.0)
        else:
            sims.append(0.6)

        # DTW 曲线匹配 (如果有 curve 序列)
        if "curve" in cand and "curve" in case:
            sims.append(dtw_similarity(cand["curve"], case["curve"]))

        return float(np.mean(sims)) if sims else 0.5

    def evaluate_candidate(self, candidate_features: dict[str, Any]) -> dict[str, Any]:
        """将候选股票特征与全部标杆案例比对，返回最佳匹配案例和总相似度。"""
        best_case = None
        best_score = 0.0
        best_breakdown: dict[str, float] = {}

        for case in self.cases:
            match_res = self.match_features(candidate_features, case.get("features", {}))
            score = match_res["total_score"]
            if score > best_score:
                best_score = score
                best_case = case
                best_breakdown = match_res["breakdown"]

        return {
            "similarity": best_score,
            "matched_case_name": best_case["name"] if best_case else "无",
            "matched_case_code": best_case["code"] if best_case else "",
            "matched_case_desc": best_case["description"] if best_case else "",
            "breakdown": best_breakdown,
        }


def extract_stock_features(
    closes: np.ndarray,
    highs: np.ndarray,
    lows: np.ndarray,
    volumes: np.ndarray,
    zhixing_short: np.ndarray,
    zhixing_bullbear: np.ndarray,
    j_values: np.ndarray,
    k_values: np.ndarray | None = None,
    d_values: np.ndarray | None = None,
) -> dict[str, Any]:
    """从股票近25日历史数据序列提取四维特征。"""
    if len(closes) < 10:
        return {}

    latest_close = float(closes[-1])
    latest_short = float(zhixing_short[-1])
    latest_bb = float(zhixing_bullbear[-1])
    short_5d_ago = float(zhixing_short[-5]) if len(zhixing_short) >= 5 else latest_short
    bb_5d_ago = float(zhixing_bullbear[-5]) if len(zhixing_bullbear) >= 5 else latest_bb

    short_slope = (latest_short / short_5d_ago - 1.0) * 100.0 if short_5d_ago > 0 else 0.0
    bb_slope = (latest_bb / bb_5d_ago - 1.0) * 100.0 if bb_5d_ago > 0 else 0.0
    price_vs_short = (latest_close - latest_short) / latest_short * 100.0 if latest_short > 0 else 0.0
    price_vs_bb = (latest_close - latest_bb) / latest_bb * 100.0 if latest_bb > 0 else 0.0
    is_in_bowl = latest_short > latest_close >= latest_bb
    trend_spread = (latest_short - latest_bb) / latest_bb * 100.0 if latest_bb > 0 else 0.0
    avg_trend = (latest_short + latest_bb) / 2.0
    price_bias = (latest_close - avg_trend) / avg_trend * 100.0 if avg_trend > 0 else 0.0

    # KDJ 特征
    latest_j = float(j_values[-1])
    j_pos = "低位" if latest_j <= 20.0 else ("高位" if latest_j >= 80.0 else "中位")
    k_cross_d = False
    if k_values is not None and d_values is not None and len(k_values) >= 2:
        k_cross_d = bool(k_values[-2] < d_values[-2] and k_values[-1] > d_values[-1])
    j_trend = float(latest_j - j_values[-3]) if len(j_values) >= 3 else 0.0

    # 量能特征
    recent_vol = np.mean(volumes[-10:]) if len(volumes) >= 10 else np.mean(volumes)
    prev_vol = np.mean(volumes[-20:-10]) if len(volumes) >= 20 else recent_vol
    vol_ratio = float(recent_vol / (prev_vol + 1e-6))
    shrink_then_expand = bool(recent_vol > 1.2 * prev_vol)
    max_vol_ratio = float(np.max(volumes[-20:]) / (np.mean(volumes[-20:]) + 1e-6)) if len(volumes) >= 20 else 2.0
    vol_trend = "缩量后放量" if shrink_then_expand else ("持续缩量" if vol_ratio < 0.7 else "量能平稳")

    # 形态特征
    peak = np.maximum.accumulate(closes)
    drawdowns = (peak - closes) / (peak + 1e-6) * 100.0
    max_dd = float(np.max(drawdowns))
    breakout_str = float((closes[-1] / (closes[-2] + 1e-6) - 1.0) * 100.0) if len(closes) >= 2 else 0.0
    overall = "上升" if closes[-1] > closes[0] else "震荡"

    return {
        "trend_structure": {
            "short_vs_bullbear": round(latest_short / (latest_bb + 1e-6), 3),
            "short_slope": round(short_slope, 2),
            "bullbear_slope": round(bb_slope, 2),
            "price_vs_short_pct": round(price_vs_short, 2),
            "price_vs_bullbear_pct": round(price_vs_bb, 2),
            "is_in_bowl": is_in_bowl,
            "trend_spread_pct": round(trend_spread, 2),
            "price_bias_pct": round(price_bias, 2),
        },
        "kdj_state": {
            "j_value": round(latest_j, 1),
            "j_position": j_pos,
            "k_cross_d": k_cross_d,
            "j_trend": round(j_trend, 2),
        },
        "volume_pattern": {
            "avg_volume_ratio": round(vol_ratio, 2),
            "volume_trend": vol_trend,
            "shrink_then_expand": shrink_then_expand,
            "max_volume_ratio": round(max_vol_ratio, 2),
        },
        "price_shape": {
            "max_drawdown": round(max_dd, 1),
            "breakout_strength": round(breakout_str, 2),
            "overall_trend": overall,
            "curve": closes[-25:] if len(closes) >= 25 else closes,
        },
    }
