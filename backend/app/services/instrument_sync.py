"""标的维表同步服务。

盘前 9:10 调用 tf.exchanges.get_instruments("SH"/"SZ"/"BJ", type="stock")
获取全量标的元数据，flatten ext 字段，写入 instruments.parquet。

Starter+ 盘后可用 quotes.get(universes) 顺便补充 name。
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import polars as pl

from app.tickflow.client import get_client

logger = logging.getLogger(__name__)

# A 股三个交易所; 港美股按市场注册表（见 app.markets）
_EXCHANGES = ["SH", "SZ", "BJ"]

# 市场 → TickFlow 交易所（多市场扩展）
_MARKET_EXCHANGES: dict[str, list[str]] = {
    "cn": ["SH", "SZ", "BJ"],
    "hk": ["HK"],
    "us": ["US"],
}


def _market_of_exchange(exchange: str) -> str:
    for market, exchanges in _MARKET_EXCHANGES.items():
        if exchange in exchanges:
            return market
    return "cn"


def _clean_float(v: Any) -> float | None:
    if v is None or v == "" or v == "-":
        return None
    try:
        import math
        f = float(v)
        return f if math.isfinite(f) else None
    except (ValueError, TypeError):
        return None


def _flatten_instruments(items: list[dict]) -> list[dict]:
    """把 SDK 返回的 Instrument 列表 flatten 成扁平行。"""
    rows = []
    for item in items:
        ext = item.get("ext") or {}
        row = {
            "symbol": str(item.get("symbol") or ""),
            "name": str(item.get("name") or ""),
            "code": str(item.get("code") or ""),
            "exchange": str(item.get("exchange") or ""),
            "region": str(item.get("region") or ""),
            "type": str(item.get("type") or "stock"),
            "market": _market_of_exchange(str(item.get("exchange") or "")),
            "listing_date": str(ext.get("listing_date") or item.get("listing_date") or "") or None,
            "total_shares": _clean_float(ext.get("total_shares") if ext.get("total_shares") is not None else item.get("total_shares")),
            "float_shares": _clean_float(ext.get("float_shares") if ext.get("float_shares") is not None else item.get("float_shares")),
            "tick_size": _clean_float(ext.get("tick_size") if ext.get("tick_size") is not None else item.get("tick_size")),
            "limit_up": _clean_float(ext.get("limit_up") if ext.get("limit_up") is not None else item.get("limit_up")),
            "limit_down": _clean_float(ext.get("limit_down") if ext.get("limit_down") is not None else item.get("limit_down")),
        }
        rows.append(row)
    return rows


def _fetch_instruments_via_provider() -> list[dict] | None:
    """若当前日K数据源不是 tickflow 且该 provider 提供 get_instruments, 用它拉标的维表。

    返回 flatten 行列表; 未命中(仍应走 tickflow)时返回 None。
    标的维表跟随日K数据源(二者天然耦合, 无独立偏好项)。
    """
    from app.services import preferences

    provider_name = preferences.get_daily_data_provider()
    if provider_name == "tickflow":
        return None
    from app.data_providers import custom as custom_sources

    if not custom_sources.is_custom_provider(provider_name):
        return None
    provider = custom_sources.get_provider(provider_name)
    if not hasattr(provider, "get_instruments"):
        return None
    try:
        items = provider.get_instruments("stock") or []
    except Exception as e:  # noqa: BLE001
        logger.warning("provider %s get_instruments 失败: %s", provider_name, e)
        return None
    rows = _flatten_instruments(items)
    logger.info("instruments via %s: %d stocks", provider_name, len(rows))
    return rows


def sync_instruments(data_dir: Path, markets: list[str] | None = None) -> int:
    """全量同步标的维表 → data/instruments/instruments.parquet。

    markets: 指定同步哪些市场（cn/hk/us），缺省同步全部市场。
    返回写入的行数。
    """
    from app.markets import ALL_MARKETS, get_market

    if markets is None:
        markets = list(ALL_MARKETS)

    all_rows = []
    synced_markets = set()

    # 1. 尝试通过自定义数据源 (如智兔) 获取 A 股 / cn
    if "cn" in markets:
        cn_rows = _fetch_instruments_via_provider()
        if cn_rows:
            all_rows.extend(cn_rows)
            synced_markets.add("cn")

    # 2. 补充尚未获取的市场（如 hk, us 或未配置自定义源时的 cn）
    remaining_markets = [m for m in markets if m not in synced_markets]
    if remaining_markets:
        tf = get_client()
        for market in remaining_markets:
            for ex in get_market(market).exchanges:
                try:
                    items = tf.exchanges.get_instruments(ex, instrument_type="stock")
                    if items:
                        all_rows.extend(_flatten_instruments(items))
                        logger.info("instruments %s (%s): %d stocks", ex, market, len(items))
                except Exception as e:
                    logger.warning("get_instruments(%s) failed: %s", ex, e)

    if not all_rows:
        return 0

    df = pl.DataFrame(all_rows, infer_schema_length=None)
    df = df.with_columns(pl.lit(date.today()).alias("as_of"))

    out = data_dir / "instruments" / "instruments.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(out)

    logger.info("instruments synced: %d rows → %s", df.height, out)
    return df.height


def enrich_names_from_quotes(
    data_dir: Path,
    quotes_data: list[dict],
) -> int:
    """从 quotes 响应中提取 name，更新 instruments 维表（兜底补充）。

    盘后 quotes.get(universes) 返回的数据中包含 ext.name，
    用来补充 instruments 中可能缺失的 name。
    """
    if not quotes_data:
        return 0

    # 构建 symbol → name 映射
    name_map: dict[str, str] = {}
    for q in quotes_data:
        symbol = q.get("symbol", "")
        ext = q.get("ext") or {}
        name = ext.get("name") or q.get("name", "")
        if symbol and name:
            name_map[symbol] = name

    if not name_map:
        return 0

    inst_path = data_dir / "instruments" / "instruments.parquet"
    if not inst_path.exists():
        return 0

    df = pl.read_parquet(inst_path)

    # 只更新空 name 的行
    updates = pl.DataFrame({
        "symbol": list(name_map.keys()),
        "_new_name": list(name_map.values()),
    })
    df = df.join(updates, on="symbol", how="left")
    df = df.with_columns(
        pl.when(pl.col("name").is_null() | (pl.col("name") == ""))
        .then(pl.col("_new_name"))
        .otherwise(pl.col("name"))
        .alias("name"),
    ).drop("_new_name")

    df.write_parquet(inst_path)
    logger.info("instruments name enriched from quotes: %d names", len(name_map))
    return len(name_map)
