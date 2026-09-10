# -*- coding: utf-8 -*-
"""TradingView 实时行情与批量报价获取。"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd
from tradingview_screener import col, crypto, stocks

from app.markets import MARKET_CRYPTO, MARKET_US, market_of
from app.plugins.tradingview.client import cached_query, get_request_kwargs, make_cache_key

logger = logging.getLogger(__name__)


def _normalize_clean_ticker(symbol: str, mkt: str) -> str:
    """提取用于 TradingView 查询的原始代码。"""
    sym = (symbol or "").strip().upper()
    if mkt == MARKET_US:
        if sym.endswith(".US"):
            return sym[:-3]
        return sym
    if mkt == MARKET_CRYPTO:
        # 去除交易所前缀如 BINANCE:BTCUSDT -> BTCUSDT
        if ":" in sym:
            return sym.split(":")[-1]
        return sym
    return sym


def get_batch_quotes(symbols: list[str]) -> list[dict[str, Any]]:
    """批量获取美股和加密货币的实时报价信息。

    Args:
        symbols: 包含股票或代币代码的列表，如 ["AAPL.US", "NVDA.US", "BTCUSDT", "ETHUSDT"]

    Returns:
        标准化报价对象列表。
    """
    if not symbols:
        return []

    us_map: dict[str, str] = {}  # clean_ticker -> original_symbol
    crypto_map: dict[str, str] = {}  # clean_ticker -> original_symbol

    for s in symbols:
        mkt = market_of(s)
        clean = _normalize_clean_ticker(s, mkt)
        if not clean:
            continue
        if mkt == MARKET_US:
            us_map[clean] = s
        elif mkt == MARKET_CRYPTO:
            crypto_map[clean] = s

    results: list[dict[str, Any]] = []

    # 1. 批量查询美股
    if us_map:
        us_tickers = list(us_map.keys())
        cache_key = make_cache_key("tv_quotes_us", sorted(us_tickers))

        def _fetch_us() -> pd.DataFrame:
            req_kwargs = get_request_kwargs()
            q = (
                stocks("america")
                .select("name", "description", "close", "change", "volume", "high", "low")
                .where(col("name").isin(us_tickers))
            )
            _, df = q.get_scanner_data(**req_kwargs)
            return df

        try:
            df_us = cached_query(cache_key, _fetch_us, ttl=10.0)
            if df_us is not None and not df_us.empty:
                df_us = df_us.drop_duplicates(subset=["name"])
                for _, r in df_us.iterrows():
                    clean_name = str(r.get("name", "")).upper()
                    orig_sym = us_map.get(clean_name, f"{clean_name}.US")
                    close = float(r.get("close", 0.0) or 0.0)
                    change = float(r.get("change", 0.0) or 0.0)
                    vol = float(r.get("volume", 0.0) or 0.0)
                    desc = str(r.get("description", "") or clean_name)

                    results.append({
                        "symbol": orig_sym,
                        "code": clean_name,
                        "name": desc,
                        "close": close,
                        "current_price": close,
                        "change_pct": change / 100.0,
                        "change_amount": round(close * change / 100.0, 4) if close else 0.0,
                        "volume": vol,
                        "market": MARKET_US,
                        "asset_type": "stock",
                    })
        except Exception as e:
            logger.warning("获取 TradingView 美股批量行情失败: %s", e)

    # 2. 批量查询加密货币
    if crypto_map:
        crypto_tickers = list(crypto_map.keys())
        cache_key = make_cache_key("tv_quotes_crypto", sorted(crypto_tickers))

        def _fetch_crypto() -> pd.DataFrame:
            req_kwargs = get_request_kwargs()
            q = (
                crypto()
                .select("name", "description", "close", "change", "volume", "high", "low")
                .where(col("name").isin(crypto_tickers))
            )
            _, df = q.get_scanner_data(**req_kwargs)
            return df

        try:
            df_crypto = cached_query(cache_key, _fetch_crypto, ttl=10.0)
            if df_crypto is not None and not df_crypto.empty:
                # 若存在多个交易所行情，优先保留包含 BINANCE 的行，其次去重
                if "ticker" in df_crypto.columns:
                    # 排序让 BINANCE 靠前
                    df_crypto["_is_binance"] = df_crypto["ticker"].astype(str).str.startswith("BINANCE:")
                    df_crypto = df_crypto.sort_values(by="_is_binance", ascending=False)
                df_crypto = df_crypto.drop_duplicates(subset=["name"])

                for _, r in df_crypto.iterrows():
                    clean_name = str(r.get("name", "")).upper()
                    orig_sym = crypto_map.get(clean_name, clean_name)
                    close = float(r.get("close", 0.0) or 0.0)
                    change = float(r.get("change", 0.0) or 0.0)
                    vol = float(r.get("volume", 0.0) or 0.0)
                    desc = str(r.get("description", "") or clean_name)
                    display_name = clean_name.replace("USDT", "/USDT")

                    results.append({
                        "symbol": orig_sym,
                        "code": clean_name,
                        "name": f"{desc} ({display_name})" if desc != clean_name else display_name,
                        "close": close,
                        "current_price": close,
                        "change_pct": change / 100.0,
                        "change_amount": round(close * change / 100.0, 6) if close else 0.0,
                        "volume": vol,
                        "market": MARKET_CRYPTO,
                        "asset_type": "crypto",
                    })
        except Exception as e:
            logger.warning("获取 TradingView 加密货币批量行情失败: %s", e)

    return results


def search_symbols(query: str, market: str | None = None, limit: int = 15) -> list[dict[str, Any]]:
    """按前缀关键词快速搜索美股或加密货币标的。"""
    kw = (query or "").strip().upper()
    if not kw:
        return []

    cache_key = make_cache_key("tv_search", {"q": kw, "m": market, "l": limit})

    def _fetch() -> list[dict[str, Any]]:
        req_kwargs = get_request_kwargs()
        items: list[dict[str, Any]] = []

        # 美股搜索
        if market in (None, MARKET_US):
            try:
                q = (
                    stocks("america")
                    .select("name", "description", "close", "change", "market_cap_basic")
                    .where(col("name").like(f"^{kw}"))
                    .order_by("market_cap_basic", ascending=False)
                    .limit(limit)
                )
                _, df = q.get_scanner_data(**req_kwargs)
                if df is not None and not df.empty:
                    df = df.drop_duplicates(subset=["name"])
                    for _, r in df.iterrows():
                        name = str(r.get("name", ""))
                        desc = str(r.get("description", "") or name)
                        close = float(r.get("close", 0.0) or 0.0)
                        change = float(r.get("change", 0.0) or 0.0)
                        items.append({
                            "symbol": f"{name}.US",
                            "code": name,
                            "name": desc,
                            "market": MARKET_US,
                            "asset_type": "stock",
                            "close": close,
                            "change_pct": change / 100.0,
                        })
            except Exception as e:
                logger.debug("TradingView 美股搜索失败: %s", e)

        # 加密货币搜索
        if market in (None, MARKET_CRYPTO):
            try:
                q = (
                    crypto()
                    .select("name", "description", "close", "change", "volume")
                    .where(
                        col("name").like(f"^{kw}"),
                        col("name").like("USDT$"),
                    )
                    .order_by("volume", ascending=False)
                    .limit(limit)
                )
                _, df = q.get_scanner_data(**req_kwargs)
                if df is not None and not df.empty:
                    if "ticker" in df.columns:
                        df["_is_binance"] = df["ticker"].astype(str).str.startswith("BINANCE:")
                        df = df.sort_values(by="_is_binance", ascending=False)
                    df = df.drop_duplicates(subset=["name"])
                    exact_target = f"{kw}USDT"
                    for _, r in df.iterrows():
                        name = str(r.get("name", ""))
                        desc = str(r.get("description", "") or name)
                        close = float(r.get("close", 0.0) or 0.0)
                        change = float(r.get("change", 0.0) or 0.0)
                        vol = float(r.get("volume", 0.0) or 0.0)
                        items.append({
                            "symbol": name,
                            "code": name,
                            "name": name.replace("USDT", "/USDT"),
                            "market": MARKET_CRYPTO,
                            "asset_type": "crypto",
                            "close": close,
                            "change_pct": change / 100.0,
                            "_priority": 0 if name == exact_target else 1,
                            "_volume": vol,
                        })
                    items.sort(key=lambda x: (x.get("_priority", 1), -x.get("_volume", 0)))
                    for item in items:
                        item.pop("_priority", None)
                        item.pop("_volume", None)
            except Exception as e:
                logger.debug("TradingView 加密货币搜索失败: %s", e)

        return items[:limit]

    return cached_query(cache_key, _fetch, ttl=60.0)
