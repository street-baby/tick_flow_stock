# -*- coding: utf-8 -*-
"""TradingView 选股器扫描策略实现与字段转换。"""
from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from tradingview_screener import col, crypto, stocks

from app.plugins.tradingview.client import cached_query, get_request_kwargs, make_cache_key

logger = logging.getLogger(__name__)

US_PRESETS: list[dict[str, Any]] = [
    {
        "id": "us_volume_breakout",
        "name": "美股 · 放量大涨突破",
        "description": "日涨幅 > 3%，相对放量 > 1.5 倍，收盘站上 MA20，市值 > 10 亿美元",
        "market": "us",
        "tags": ["美股", "放量突破", "动量", "MA20"],
    },
    {
        "id": "us_megacap_leaders",
        "name": "美股 · 千亿蓝筹巨头榜",
        "description": "市值 > 1000 亿美元，MA20 > MA50 均线多头排列，高流动性蓝筹",
        "market": "us",
        "tags": ["美股", "千亿蓝筹", "均线多头", "核心资产"],
    },
    {
        "id": "us_rsi_oversold",
        "name": "美股 · RSI 超卖拐头反弹",
        "description": "RSI(14) < 35 极度超卖区，今日收红盘阳线，寻找超跌反弹",
        "market": "us",
        "tags": ["美股", "RSI超卖", "抄底", "反弹"],
    },
    {
        "id": "us_macd_cross",
        "name": "美股 · MACD 黄金交叉",
        "description": "日线 MACD 上穿 Signal 信号线，短期动能转强",
        "market": "us",
        "tags": ["美股", "MACD金叉", "动能突破"],
    },
    {
        "id": "us_strong_buy",
        "name": "美股 · TradingView 强烈买入",
        "description": "TradingView 云端综合多指标评分评级为 Strong Buy",
        "market": "us",
        "tags": ["美股", "TradingView评级", "强力买入"],
    },
]

CRYPTO_PRESETS: list[dict[str, Any]] = [
    {
        "id": "crypto_top_gainers",
        "name": "加密 · 24H 暴涨动量榜",
        "description": "24 小时涨幅 > 5%，24 小时成交量充沛，主力资金活跃",
        "market": "crypto",
        "tags": ["加密货币", "24H涨幅榜", "主力异动", "动量"],
    },
    {
        "id": "crypto_major_leaders",
        "name": "加密 · 主流大市值币种榜",
        "description": "BTC/ETH/SOL 等主流百大币种，流动性充沛，按成交活跃度排序",
        "market": "crypto",
        "tags": ["加密货币", "主流币", "高流动性", "现货主力"],
    },
    {
        "id": "crypto_volume_breakout",
        "name": "加密 · 主力放量突破",
        "description": "相对成交量激增 1.8 倍以上，24H 涨幅 > 2%，平台向上突破",
        "market": "crypto",
        "tags": ["加密货币", "放量突破", "异动突破"],
    },
    {
        "id": "crypto_rsi_oversold",
        "name": "加密 · RSI 极度超卖抄底",
        "description": "RSI(14) < 32 极度超卖区，博弈超跌反弹修复",
        "market": "crypto",
        "tags": ["加密货币", "RSI超卖", "超跌抄底"],
    },
    {
        "id": "crypto_golden_cross",
        "name": "加密 · 日线 MACD 金叉",
        "description": "日线 MACD 上穿信号线，短期趋势多头走强",
        "market": "crypto",
        "tags": ["加密货币", "MACD金叉", "多头共振"],
    },
]


def get_presets_for_market(market: str) -> list[dict[str, Any]]:
    """返回指定市场的预设策略列表。"""
    if market == "us":
        return US_PRESETS
    if market == "crypto":
        return CRYPTO_PRESETS
    return []


def _build_us_query(preset_id: str, limit: int):
    q = stocks("america").select(
        "name",
        "description",
        "close",
        "change",
        "volume",
        "market_cap_basic",
        "price_earnings_ttm",
        "RSI",
        "MACD.macd",
        "MACD.signal",
        "Recommend.All",
    )

    if preset_id == "us_volume_breakout":
        q = (
            q.where(
                col("market_cap_basic") >= 1_000_000_000,
                col("change") > 3.0,
                col("relative_volume_10d_calc") > 1.5,
                col("close") >= col("SMA20"),
            )
            .order_by("volume", ascending=False)
        )
    elif preset_id == "us_megacap_leaders":
        q = (
            q.where(
                col("market_cap_basic") >= 100_000_000_000,
                col("SMA20") >= col("SMA50"),
            )
            .order_by("market_cap_basic", ascending=False)
        )
    elif preset_id == "us_rsi_oversold":
        q = (
            q.where(
                col("market_cap_basic") >= 500_000_000,
                col("RSI") < 35,
                col("change") > 0,
            )
            .order_by("volume", ascending=False)
        )
    elif preset_id == "us_macd_cross":
        q = (
            q.where(
                col("market_cap_basic") >= 1_000_000_000,
                col("MACD.macd") >= col("MACD.signal"),
                col("change") > 0.5,
            )
            .order_by("volume", ascending=False)
        )
    elif preset_id == "us_strong_buy":
        q = (
            q.where(
                col("market_cap_basic") >= 2_000_000_000,
                col("Recommend.All") >= 0.5,
            )
            .order_by("volume", ascending=False)
        )
    else:
        # 默认回退按成交量排序
        q = q.order_by("volume", ascending=False)

    return q.limit(limit)


def _build_crypto_query(preset_id: str, limit: int):
    q = crypto().select(
        "name",
        "description",
        "close",
        "change",
        "volume",
        "24h_vol_cmc",
        "RSI",
        "MACD.macd",
        "MACD.signal",
        "Recommend.All",
    ).where(
        col("name").like("USDT$"),
        col("close") > 0.0001,
    )

    if preset_id == "crypto_top_gainers":
        q = (
            q.where(
                col("change") > 5.0,
                col("volume") >= 50_000,
            )
            .order_by("change", ascending=False)
        )
    elif preset_id == "crypto_major_leaders":
        q = (
            q.where(
                col("volume") >= 100_000,
            )
            .order_by("volume", ascending=False)
        )
    elif preset_id == "crypto_volume_breakout":
        q = (
            q.where(
                col("change") > 2.0,
                col("relative_volume_10d_calc") > 1.8,
            )
            .order_by("relative_volume_10d_calc", ascending=False)
        )
    elif preset_id == "crypto_rsi_oversold":
        q = (
            q.where(
                col("RSI") < 32,
                col("volume") >= 50_000,
            )
            .order_by("volume", ascending=False)
        )
    elif preset_id == "crypto_golden_cross":
        q = (
            q.where(
                col("MACD.macd") >= col("MACD.signal"),
                col("change") > 0.0,
                col("volume") >= 100_000,
            )
            .order_by("volume", ascending=False)
        )
    else:
        q = q.order_by("volume", ascending=False)

    return q.limit(limit)


def run_preset_scanner(market: str, preset_id: str, limit: int = 50) -> dict[str, Any]:
    """执行美股或加密货币策略扫描。"""
    t0 = time.perf_counter()
    cache_key = make_cache_key("tv_scan", {"m": market, "p": preset_id, "l": limit})

    def _fetch() -> tuple[int, pd.DataFrame]:
        req_kwargs = get_request_kwargs()
        if market == "us":
            q = _build_us_query(preset_id, limit)
        elif market == "crypto":
            q = _build_crypto_query(preset_id, limit)
        else:
            raise ValueError(f"TradingView 扫描器不支持市场: {market}")

        return q.get_scanner_data(**req_kwargs)

    count, df = cached_query(cache_key, _fetch, ttl=20.0)

    # 标准化转换
    rows: list[dict[str, Any]] = []
    if df is not None and not df.empty:
        # 去重
        if "name" in df.columns:
            df = df.drop_duplicates(subset=["name"])

        for _, r in df.iterrows():
            raw_name = str(r.get("name", ""))
            raw_desc = str(r.get("description", "") or raw_name)
            close = float(r.get("close", 0.0) or 0.0)
            change = float(r.get("change", 0.0) or 0.0)  # 百分比，如 3.5 代表 +3.5%
            vol = float(r.get("volume", 0.0) or 0.0)
            mcap = float(r.get("market_cap_basic", 0.0) or 0.0)
            pe = float(r.get("price_earnings_ttm", 0.0) or 0.0)
            rsi = float(r.get("RSI", 0.0) or 0.0)

            # symbol 规范化
            if market == "us":
                symbol = raw_name if raw_name.endswith(".US") else f"{raw_name}.US"
                display_name = raw_desc or raw_name
            else:  # crypto
                symbol = raw_name
                display_name = raw_name.replace("USDT", "/USDT")

            rows.append({
                "symbol": symbol,
                "name": display_name,
                "close": close,
                "change_pct": change / 100.0,  # 统一转为小数，如 0.035
                "volume": vol,
                "amount": vol * close,
                "market_cap": mcap,
                "pe": pe if pe > 0 else None,
                "rsi": rsi if rsi > 0 else None,
                "score": 100.0 - len(rows),
            })

    elapsed = round((time.perf_counter() - t0) * 1000, 1)
    return {
        "as_of": date.today().isoformat(),
        "strategy_id": preset_id,
        "rows": rows[:limit],
        "total": len(rows),
        "elapsed_ms": elapsed,
        "scores": {},
        "entry_signal_hits": [],
        "exit_signal_hits": [],
    }
