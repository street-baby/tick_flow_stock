"""自选股服务(§6.1)。

存储:`data/user_data/watchlist.parquet`, 字段 symbol + added_at + note + group。
支持按板块分类/自定义分组进行自选股归类管理。
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

from app.config import settings
from app.tickflow.capabilities import Cap, CapabilitySet
from app.tickflow.client import get_client
from app.tickflow.rate_limits import chunked, resolve_limit

logger = logging.getLogger(__name__)

SCHEMA = {
    "symbol": pl.Utf8,
    "added_at": pl.Utf8,
    "note": pl.Utf8,
    "group": pl.Utf8,
}


def _path() -> Path:
    p = settings.data_dir / "user_data" / "watchlist.parquet"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_df() -> pl.DataFrame:
    p = _path()
    if not p.exists():
        return pl.DataFrame(schema=SCHEMA)
    try:
        df = pl.read_parquet(p)
    except Exception as e:  # noqa: BLE001
        logger.warning("read watchlist.parquet failed, resetting: %s", e)
        return pl.DataFrame(schema=SCHEMA)

    # 兼容历史数据补全字段
    if "group" not in df.columns:
        df = df.with_columns(pl.lit("默认").alias("group"))
    else:
        df = df.with_columns(pl.col("group").fill_null("默认"))
    if "note" not in df.columns:
        df = df.with_columns(pl.lit("").alias("note"))
    else:
        df = df.with_columns(pl.col("note").fill_null(""))
    return df


def list_symbols(group: str | None = None) -> list[dict[str, Any]]:
    df = _load_df()
    if df.is_empty():
        return []
    if group and group not in ("", "全部"):
        df = df.filter(pl.col("group") == group)
    return df.to_dicts()


def list_groups() -> list[dict[str, Any]]:
    """返回现有自选分组及数量统计。"""
    df = _load_df()
    if df.is_empty():
        return [{"name": "全部", "count": 0}, {"name": "默认", "count": 0}]

    group_counts: dict[str, int] = {}
    for r in df.iter_rows(named=True):
        g = r.get("group") or "默认"
        group_counts[g] = group_counts.get(g, 0) + 1

    out: list[dict[str, Any]] = [{"name": "全部", "count": df.height}]
    if "默认" in group_counts:
        out.append({"name": "默认", "count": group_counts.pop("默认")})
    else:
        out.append({"name": "默认", "count": 0})

    for g, cnt in sorted(group_counts.items(), key=lambda x: x[0]):
        out.append({"name": g, "count": cnt})
    return out


def add(symbol: str, note: str = "", group: str = "默认") -> list[dict[str, Any]]:
    p = _path()
    df = _load_df()
    grp = group or "默认"
    # 若同一分组已存在该 symbol，先过滤掉，之后重新插入到最前面
    df = df.filter(~((pl.col("symbol") == symbol) & (pl.col("group") == grp)))

    new_row = pl.DataFrame({
        "symbol": [symbol],
        "added_at": [datetime.utcnow().isoformat(timespec="seconds")],
        "note": [note],
        "group": [grp],
    })
    out = pl.concat([new_row, df], how="diagonal_relaxed")
    out.write_parquet(p)
    return out.to_dicts()


def batch_upsert_grouped(records: list[dict[str, str]]) -> int:
    """批量更新分组自选记录（用于板块核心股票一键导入）。"""
    if not records:
        return 0
    p = _path()
    df = _load_df()
    now_iso = datetime.utcnow().isoformat(timespec="seconds")

    # 找出本次更新涉及的板块分组
    update_groups = {r.get("group", "默认") for r in records}

    # 保留不属于更新分组中的历史数据（如用户自己的“默认”分组标的）
    if not df.is_empty():
        preserved = df.filter(~pl.col("group").is_in(list(update_groups)))
    else:
        preserved = pl.DataFrame(schema=SCHEMA)

    new_df = pl.DataFrame({
        "symbol": [r["symbol"] for r in records],
        "added_at": [now_iso for _ in records],
        "note": [r.get("note", "") for r in records],
        "group": [r.get("group", "默认") for r in records],
    })

    out = pl.concat([preserved, new_df], how="diagonal_relaxed")
    out.write_parquet(p)
    return len(records)


def remove(symbol: str, group: str | None = None) -> list[dict[str, Any]]:
    p = _path()
    df = _load_df()
    if df.is_empty():
        return []
    if group and group not in ("", "全部"):
        df = df.filter(~((pl.col("symbol") == symbol) & (pl.col("group") == group)))
    else:
        df = df.filter(pl.col("symbol") != symbol)
    df.write_parquet(p)
    return df.to_dicts()


def move_to_top(symbol: str, group: str | None = None) -> list[dict[str, Any]]:
    p = _path()
    df = _load_df()
    if df.is_empty():
        return []
    cond = (pl.col("symbol") == symbol)
    if group and group not in ("", "全部"):
        cond = cond & (pl.col("group") == group)

    target = df.filter(cond)
    if target.is_empty():
        return df.to_dicts()
    rest = df.filter(~cond)
    out = pl.concat([target, rest], how="diagonal_relaxed")
    out.write_parquet(p)
    return out.to_dicts()


def clear(group: str | None = None) -> int:
    """清空自选列表（支持清空全部或指定分组）。返回移除的数量。"""
    p = _path()
    df = _load_df()
    if df.is_empty():
        return 0
    if group and group not in ("", "全部"):
        remaining = df.filter(pl.col("group") != group)
        count = df.height - remaining.height
        remaining.write_parquet(p)
        return count

    count = df.height
    pl.DataFrame(schema=SCHEMA).write_parquet(p)
    return count


def fetch_quotes(symbols: list[str], capset: CapabilitySet, timeout_s: float = 8.0) -> list[dict]:
    """拉取实时行情。

    优先用 quote.batch;否则降级为 quote.by_symbol 单股请求。
    timeout_s: 单批次请求超时(秒)，防止 API 卡死阻塞整个请求。
    """
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

    if not symbols:
        return []

    tf = get_client()
    quotes: list[dict] = []

    # 走 batch
    if capset.has(Cap.QUOTE_BATCH):
        batch_size = resolve_limit(capset, Cap.QUOTE_BATCH, default_batch=50).batch
    elif capset.has(Cap.QUOTE_BY_SYMBOL):
        batch_size = resolve_limit(capset, Cap.QUOTE_BY_SYMBOL, default_batch=5).batch
    else:
        # 无任何实时行情能力(none/free 档走 free-api 服务器,不提供实时行情)
        # 提前返回空,避免发起注定失败的请求
        return []

    chunks = chunked(symbols, batch_size)

    # 用线程池为每个批次加超时保护
    pool = ThreadPoolExecutor(max_workers=1)
    for chunk in chunks:
        try:
            future = pool.submit(tf.quotes.get, symbols=chunk, as_dataframe=True)
            raw = future.result(timeout=timeout_s)
            if raw is None or len(raw) == 0:
                continue
            df = pl.from_pandas(raw)
            rename_map = {
                "last_price": "price",
                "ext.change_pct": "pct",
                "ext.name": "name",
            }
            df = df.rename({k: v for k, v in rename_map.items() if k in df.columns})
            quotes.extend(df.to_dicts())
        except FuturesTimeout:
            logger.warning("quote fetch timeout (%.1fs) for %d symbols", timeout_s, len(chunk))
            break  # 超时后不再尝试后续批次
        except Exception as e:  # noqa: BLE001
            logger.warning("quote fetch failed for %d symbols: %s", len(chunk), e)
    pool.shutdown(wait=False)

    return quotes
