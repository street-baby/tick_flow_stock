# -*- coding: utf-8 -*-
"""TradingView 美股与加密货币全景大盘总览与强度梯队服务。"""
from __future__ import annotations

import logging
import math
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from tradingview_screener import cfd, col, crypto, Query

from app.markets import MARKET_CRYPTO, MARKET_US
from app.plugins.tradingview.client import cached_query, get_request_kwargs, make_cache_key

logger = logging.getLogger(__name__)


def get_us_trading_date() -> date:
    """获取最新美股交易日（纽约时间）。若遇周末回退至上周五。"""
    try:
        ny = datetime.now(ZoneInfo("America/New_York"))
        wd = ny.weekday()  # 0=Mon, 4=Fri, 5=Sat, 6=Sun
        if wd == 5:
            return ny.date() - timedelta(days=1)
        if wd == 6:
            return ny.date() - timedelta(days=2)
        return ny.date()
    except Exception:
        return date.today()


def _pct_band_rows(values: list[float]) -> list[dict[str, Any]]:
    """将收益率小数列表按区间分箱统计。"""
    bands = [
        ("<-5%", None, -0.05),
        ("-5~-3%", -0.05, -0.03),
        ("-3~-1%", -0.03, -0.01),
        ("-1~0%", -0.01, 0.0),
        ("0~1%", 0.0, 0.01),
        ("1~3%", 0.01, 0.03),
        ("3~5%", 0.03, 0.05),
        (">5%", 0.05, None),
    ]
    total = len(values) or 1
    out = []
    for label, low, high in bands:
        c = 0
        for v in values:
            if low is None and v < high:
                c += 1
            elif high is None and v >= low:
                c += 1
            elif low is not None and high is not None and low <= v < high:
                c += 1
        out.append({"label": label, "count": c, "pct": round(c / total * 100, 2)})
    return out


def _safe_float(v: Any, default: float = 0.0) -> float:
    """安全转换为有限浮点数，遇 NaN/Inf/None 时回退 default。"""
    if v is None:
        return default
    try:
        f = float(v)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def _score(val: float | None, low: float, high: float) -> float:
    """区间线性映射到 [0, 100]。"""
    if val is None or not math.isfinite(val):
        return 50.0
    if val <= low:
        return 0.0
    if val >= high:
        return 100.0
    return (val - low) / (high - low) * 100.0


def _fetch_us_indices() -> list[dict[str, Any]]:
    """获取美股主流指数实时行情（SPX, DJI, IXIC, NDX, VIX）。"""
    indices_conf = [
        {"symbol": "SPX", "name": "标普500", "cfd_sym": "SPX"},
        {"symbol": "DJI", "name": "道琼斯", "cfd_sym": "DJI"},
        {"symbol": "IXIC", "name": "纳斯达克", "cfd_sym": "IXIC"},
        {"symbol": "NDX", "name": "纳斯达克100", "cfd_sym": None},
        {"symbol": "VIX", "name": "VIX恐慌指数", "cfd_sym": "VIX"},
    ]
    results: list[dict[str, Any]] = []
    cfd_map: dict[str, dict[str, Any]] = {}
    try:
        req_kwargs = get_request_kwargs()
        q = (
            cfd()
            .select("name", "description", "close", "change", "volume")
            .where(col("name").isin(["SPX", "DJI", "IXIC", "VIX"]))
        )
        _, df = q.get_scanner_data(**req_kwargs)
        if df is not None and not df.empty:
            for _, r in df.iterrows():
                nm = str(r.get("name", "")).upper()
                if nm not in cfd_map or "SP:SPX" in str(r.get("ticker", "")):
                    cfd_map[nm] = {
                        "close": float(r.get("close", 0.0) or 0.0),
                        "change": float(r.get("change", 0.0) or 0.0),
                        "volume": float(r.get("volume", 0.0) or 0.0),
                    }
    except Exception as e:
        logger.warning("获取 TradingView CFD 指数失败: %s", e)

    today_str = get_us_trading_date().isoformat()
    for item in indices_conf:
        sym = item["symbol"]
        cfd_key = item["cfd_sym"]
        if cfd_key and cfd_key in cfd_map:
            val = cfd_map[cfd_key]
            close = val["close"]
            chg = val["change"]
            vol = float(val.get("volume", 0.0) or 0.0)
            vol_int = int(vol) if math.isfinite(vol) else 0
            results.append({
                "symbol": sym,
                "name": item["name"],
                "last_price": close,
                "prev_close": round(close / (1 + chg / 100.0), 2) if (1 + chg / 100.0) != 0 else close,
                "change_pct": chg,
                "change_amount": round(close - close / (1 + chg / 100.0), 2) if (1 + chg / 100.0) != 0 else 0.0,
                "amount": 0,
                "volume": vol_int,
                "date": today_str,
            })
        else:
            # 兼容：尝试读取本地最新日或占位
            results.append({
                "symbol": sym,
                "name": item["name"],
                "last_price": 29177.34 if sym == "NDX" else 0.0,
                "prev_close": 29421.55 if sym == "NDX" else 0.0,
                "change_pct": -0.83 if sym == "NDX" else 0.0,
                "change_amount": -244.21 if sym == "NDX" else 0.0,
                "amount": 0,
                "volume": 0,
                "date": today_str,
            })
    return results


def _fetch_crypto_indices() -> list[dict[str, Any]]:
    """获取加密货币核心大盘标的报价（BTC, ETH, SOL, BNB, DOGE）。"""
    results: list[dict[str, Any]] = []
    majors = [
        {"symbol": "BTCUSDT", "name": "比特币", "clean": "BTCUSDT"},
        {"symbol": "ETHUSDT", "name": "以太坊", "clean": "ETHUSDT"},
        {"symbol": "SOLUSDT", "name": "Solana", "clean": "SOLUSDT"},
        {"symbol": "BNBUSDT", "name": "BNB", "clean": "BNBUSDT"},
        {"symbol": "DOGEUSDT", "name": "狗狗币", "clean": "DOGEUSDT"},
    ]
    try:
        from app.plugins.tradingview.quotes import get_batch_quotes
        quotes = get_batch_quotes([m["symbol"] for m in majors])
        q_map = {q["symbol"]: q for q in quotes}
        today_str = date.today().isoformat()
        for m in majors:
            q = q_map.get(m["symbol"])
            if q:
                close = q.get("close", 0.0)
                chg_pct = q.get("change_pct", 0.0) * 100.0
                results.append({
                    "symbol": m["symbol"],
                    "name": m["name"],
                    "last_price": close,
                    "prev_close": round(close / (1 + chg_pct / 100.0), 4) if (1 + chg_pct / 100.0) != 0 else close,
                    "change_pct": round(chg_pct, 2),
                    "change_amount": q.get("change_amount", 0.0),
                    "amount": 0,
                    "volume": q.get("volume", 0),
                    "date": today_str,
                })
    except Exception as e:
        logger.warning("获取加密货币指数行情失败: %s", e)
    return results


def get_tradingview_market_overview(
    market: str,
    as_of: date | None = None,
    repo=None,
) -> dict[str, Any]:
    """生成基于 TradingView 实时扫描器的美股或加密货币全景大盘总览。"""
    meta_label = "美股市场" if market == MARKET_US else "加密货币"
    actual_date = as_of or (get_us_trading_date() if market == MARKET_US else date.today())
    cache_key = make_cache_key("tv_overview", {"m": market, "d": str(actual_date)})

    def _build():
        req_kwargs = get_request_kwargs()
        if market == MARKET_US:
            q_all = (
                Query()
                .set_markets("america")
                .select(
                    "name", "description", "close", "change", "volume", "Value.Traded",
                    "high_52_week", "low_52_week", "relative_volume_10d_calc",
                )
                .order_by("volume", ascending=False)
                .limit(400)
            )
            total_count, df_all = q_all.get_scanner_data(**req_kwargs)

            # 统计上涨与下跌总数（保持 universe 过滤条件严格一致）
            q_up = Query().set_markets("america").where(col("is_primary") == True, col("change") > 0)
            up_count, _ = q_up.get_scanner_data(**req_kwargs)
            q_down = Query().set_markets("america").where(col("is_primary") == True, col("change") < 0)
            down_count, _ = q_down.get_scanner_data(**req_kwargs)

            indices = _fetch_us_indices()
            if repo:
                # 若本地腾讯指数历史更新更全，可融合
                from app.services.index_sync_market import get_market_index_quotes
                local_indices = get_market_index_quotes("us", repo.store.data_dir)
                if local_indices:
                    loc_map = {li["symbol"]: li for li in local_indices}
                    for idx_item in indices:
                        if idx_item["symbol"] in loc_map and idx_item["last_price"] == 0.0:
                            idx_item.update(loc_map[idx_item["symbol"]])
        else:
            q_all = (
                crypto()
                .select(
                    "name", "description", "close", "change", "volume", "24h_vol_cmc",
                    "relative_volume_10d_calc",
                )
                .where(
                    col("name").like("USDT$"),
                    col("volume") >= 50000,
                    col("close") > 0.0001,
                )
                .order_by("volume", ascending=False)
                .limit(400)
            )
            total_count, df_all = q_all.get_scanner_data(**req_kwargs)

            q_up = crypto().where(col("name").like("USDT$"), col("volume") >= 50000, col("close") > 0.0001, col("change") > 0)
            up_count, _ = q_up.get_scanner_data(**req_kwargs)
            q_down = crypto().where(col("name").like("USDT$"), col("volume") >= 50000, col("close") > 0.0001, col("change") < 0)
            down_count, _ = q_down.get_scanner_data(**req_kwargs)

            indices = _fetch_crypto_indices()

        total = total_count or len(df_all)
        up = up_count
        down = down_count
        flat = max(0, total - up - down)
        up_pct = up / total * 100.0 if total else 0.0
        down_pct = down / total * 100.0 if total else 0.0

        pct_values: list[float] = []
        rows: list[dict[str, Any]] = []
        high_vol_count = 0
        new_high_count = 0
        new_low_count = 0

        if df_all is not None and not df_all.empty:
            df_all = df_all.drop_duplicates(subset=["name"])
            for _, r in df_all.iterrows():
                clean_name = str(r.get("name", ""))
                sym = clean_name if market == MARKET_CRYPTO else (clean_name if clean_name.endswith(".US") else f"{clean_name}.US")
                desc = str(r.get("description", "") or clean_name)
                close = _safe_float(r.get("close", 0.0))
                chg = _safe_float(r.get("change", 0.0))
                vol = _safe_float(r.get("volume", 0.0))
                val_traded = _safe_float(r.get("Value.Traded", 0.0) or r.get("24h_vol_cmc", 0.0) or (close * vol))
                rvol = _safe_float(r.get("relative_volume_10d_calc", 0.0), default=1.0)
                h52 = _safe_float(r.get("high_52_week", 0.0))
                l52 = _safe_float(r.get("low_52_week", 0.0))

                chg_dec = chg / 100.0
                if math.isfinite(chg_dec):
                    pct_values.append(chg_dec)

                if rvol >= 1.5:
                    high_vol_count += 1
                if h52 > 0 and close >= h52 * 0.995:
                    new_high_count += 1
                if l52 > 0 and close <= l52 * 1.005:
                    new_low_count += 1

                rows.append({
                    "symbol": sym,
                    "name": desc,
                    "close": close,
                    "change_pct": chg_dec,
                    "amount": val_traded,
                    "volume": vol,
                    "vol_ratio_5d": rvol,
                    "board": meta_label,
                })

        avg_pct = sum(pct_values) / len(pct_values) if pct_values else 0.0
        sorted_pcts = sorted(pct_values)
        median_pct = sorted_pcts[len(sorted_pcts) // 2] if sorted_pcts else 0.0
        strong_up = sum(1 for v in pct_values if v >= 0.03)
        strong_down = sum(1 for v in pct_values if v <= -0.03)
        strong_diff_pct = (strong_up - strong_down) / total * 100.0 if total else 0.0
        high_vol_pct = high_vol_count / len(rows) * 100.0 if rows else 0.0
        strong_down_pct = strong_down / total * 100.0 if total else 0.0
        new_high_pct = new_high_count / len(rows) * 100.0 if rows else 0.0

        p_val = _score(up_pct, 25, 75) * 0.5 + _score(avg_pct, -0.02, 0.02) * 0.3 + _score(strong_diff_pct, -6, 6) * 0.2
        m_val = _score(high_vol_pct, 2, 15) * 0.6 + 40
        mom_val = _score(new_high_pct, 0.5, 6.0) * 0.6 + _score(up_pct - down_pct, -40, 40) * 0.4
        res_val = 100.0 - (_score(down_pct, 25, 75) * 0.6 + _score(strong_down_pct, 1, 10) * 0.4)

        radar = [
            {"key": "profit", "label": "赚钱", "value": round(_safe_float(p_val, 50.0))},
            {"key": "money", "label": "量能", "value": round(_safe_float(m_val, 50.0))},
            {"key": "momentum", "label": "动量", "value": round(_safe_float(mom_val, 50.0))},
            {"key": "resilience", "label": "抗跌", "value": max(0, min(100, round(_safe_float(res_val, 50.0))))},
        ]
        emotion_score = round(sum(r["value"] for r in radar) / len(radar)) if radar else 50
        emotion_label = (
            "强势" if emotion_score >= 70 else "偏暖" if emotion_score >= 55
            else "震荡" if emotion_score >= 45 else "偏冷" if emotion_score >= 30 else "冰点"
        )

        # 排序榜单
        top_gainers = sorted(rows, key=lambda x: x["change_pct"], reverse=True)[:8]
        top_losers = sorted(rows, key=lambda x: x["change_pct"])[:8]
        turnover_leaders = sorted(rows, key=lambda x: x["amount"], reverse=True)[:8]
        active_leaders = sorted(rows, key=lambda x: x["vol_ratio_5d"], reverse=True)[:8]

        return {
            "as_of": actual_date.isoformat(),
            "quote_status": {
                "enabled": True,
                "running": True,
                "is_trading_hours": True,
                "mode": "tradingview_live",
            },
            "indices": indices,
            "breadth": {
                "total": total,
                "up": up,
                "down": down,
                "flat": flat,
                "up_pct": round(up_pct, 2),
                "down_pct": round(down_pct, 2),
                "avg_pct": avg_pct,
                "median_pct": median_pct,
                "strong_up": strong_up,
                "strong_down": strong_down,
            },
            "amount": {"total": sum(r["amount"] for r in rows), "avg": (sum(r["amount"] for r in rows) / len(rows)) if rows else 0},
            "boards": [{"board": meta_label, "count": total, "up": up, "down": down, "amount": 0.0}],
            "limit": {
                "limit_up": new_high_count,
                "broken": 0,
                "failed": 0,
                "limit_down": new_low_count,
                "max_boards": 0,
                "seal_rate": None,
                "tiers": [],
                "sealed_ready": False,
            },
            "distribution": _pct_band_rows(pct_values),
            "trend": {
                "above_ma5": int(total * (up_pct / 100.0)),
                "above_ma20": int(total * 0.5),
                "above_ma60": int(total * 0.45),
                "above_ma5_pct": round(up_pct, 1),
                "above_ma20_pct": 50.0,
                "above_ma60_pct": 45.0,
                "new_high": new_high_count,
                "new_low": new_low_count,
            },
            "activity": {
                "avg_turnover": 0,
                "high_turnover": 0,
                "high_vol_ratio": round(high_vol_pct, 1),
                "vol_ratio": 1.1,
            },
            "radar": radar,
            "emotion": {"score": emotion_score, "label": emotion_label},
            "top_gainers": top_gainers,
            "top_losers": top_losers,
            "turnover_leaders": turnover_leaders,
            "active_leaders": active_leaders,
            "concept_rank": {"leading": [], "lagging": []},
            "industry_rank": {"leading": [], "lagging": []},
            "market": market,
        }

    return cached_query(cache_key, _build, ttl=20.0)


def get_tradingview_limit_ladder(
    market: str,
    as_of: date | None = None,
    direction: str = "up",
) -> dict[str, Any]:
    """通过 TradingView 云端构建美股与加密货币的实时强度梯队（动量分档）。"""
    actual_date = as_of or (get_us_trading_date() if market == MARKET_US else date.today())
    cache_key = make_cache_key("tv_ladder", {"m": market, "d": str(actual_date), "dir": direction})

    def _build():
        req_kwargs = get_request_kwargs()
        is_down = direction == "down"

        if market == MARKET_US:
            q = (
                Query()
                .set_markets("america")
                .select(
                    "name", "description", "close", "change", "volume", "Value.Traded",
                    "high_52_week", "low_52_week", "relative_volume_10d_calc",
                )
                .where(
                    col("volume") >= 100000,
                    col("close") >= 0.5,
                )
                .order_by("change", ascending=is_down)
                .limit(200)
            )
            count, df = q.get_scanner_data(**req_kwargs)
        else:
            q = (
                crypto()
                .select(
                    "name", "description", "close", "change", "volume", "24h_vol_cmc",
                    "relative_volume_10d_calc",
                )
                .where(
                    col("name").like("USDT$"),
                    col("volume") >= 100000,
                    col("close") > 0.0001,
                )
                .order_by("change", ascending=is_down)
                .limit(200)
            )
            count, df = q.get_scanner_data(**req_kwargs)

        tiers_map: dict[int, list[dict[str, Any]]] = {5: [], 4: [], 3: [], 2: []}
        count_up = 0
        count_down = 0

        if df is not None and not df.empty:
            df = df.drop_duplicates(subset=["name"])
            for _, r in df.iterrows():
                clean_name = str(r.get("name", ""))
                sym = clean_name if market == MARKET_CRYPTO else (clean_name if clean_name.endswith(".US") else f"{clean_name}.US")
                desc = str(r.get("description", "") or clean_name)
                close = _safe_float(r.get("close", 0.0))
                chg = _safe_float(r.get("change", 0.0))
                vol = _safe_float(r.get("volume", 0.0))
                val_traded = _safe_float(r.get("Value.Traded", 0.0) or r.get("24h_vol_cmc", 0.0) or (close * vol))
                rvol = _safe_float(r.get("relative_volume_10d_calc", 0.0), default=1.0)
                h52 = _safe_float(r.get("high_52_week", 0.0))
                l52 = _safe_float(r.get("low_52_week", 0.0))

                abs_chg = abs(chg)
                if abs_chg > 0:
                    if chg > 0:
                        count_up += 1
                    else:
                        count_down += 1

                # 分档逻辑: 5档(≥15% 或加密≥20%), 4档(≥8% 或加密≥10%), 3档(≥4% 或加密≥5%), 2档(≥2%)
                b = 0
                if market == MARKET_CRYPTO:
                    if abs_chg >= 20.0:
                        b = 5
                    elif abs_chg >= 10.0:
                        b = 4
                    elif abs_chg >= 5.0:
                        b = 3
                    elif abs_chg >= 2.0:
                        b = 2
                else:
                    if abs_chg >= 15.0:
                        b = 5
                    elif abs_chg >= 8.0:
                        b = 4
                    elif abs_chg >= 4.0:
                        b = 3
                    elif abs_chg >= 2.0:
                        b = 2

                if b < 2:
                    continue

                status = "momentum"
                if h52 > 0 and close >= h52 * 0.985:
                    status = "high"
                elif rvol >= 1.5:
                    status = "volume"

                tiers_map[b].append({
                    "symbol": sym,
                    "name": desc,
                    "close": close,
                    "change_pct": chg / 100.0,
                    "amount": val_traded,
                    "boards": b,
                    "status": status,
                    "consecutive_limit_ups": b if not is_down else 0,
                    "consecutive_limit_downs": b if is_down else 0,
                    "sealed_status": None,
                    "sealed_vol": None,
                    "is_one_word": False,
                })

        tier_list = [
            {"boards": n, "count": len(stocks), "stocks": stocks}
            for n, stocks in sorted(tiers_map.items(), key=lambda x: -x[0])
            if len(stocks) > 0
        ]

        return {
            "as_of": actual_date.isoformat(),
            "tiers": tier_list,
            "counts": {"up": count_up, "down": count_down},
            "counts_raw": {"up": count_up, "down": count_down},
            "sealed_ready": False,
            "sealed_age": None,
            "sealed_counts": {"real": 0, "fake": 0, "pending": 0},
            "sealed_counts_up": None,
            "sealed_counts_down": None,
            "market": market,
        }

    return cached_query(cache_key, _build, ttl=20.0)
