"""板块核心股票（人气与辨识度）甄选与自选分类注入引擎。

从同花顺行业表 (ext_hy_ths) 提取 31 个一级行业板块，结合最新日 K enriched 行情数据，
按连板辨识度、成交额中军和高换手活跃度进行多因子综合排序，为每个行业精选 3~5 只核心代表股票。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import polars as pl

from app.config import settings
from app.services import watchlist

logger = logging.getLogger(__name__)


def _get_primary_industry(x: str | None) -> str | None:
    if not x:
        return None
    return x.split("-")[0].strip()


def select_sector_core_stocks(data_dir: Path | None = None) -> dict[str, list[dict[str, Any]]]:
    """计算 31 个行业板块的核心人气龙头股票。

    返回: { 板块名: [ { symbol, name, tag, amount, turnover_rate, consecutive_limit_ups }, ... ] }
    """
    root_data = data_dir or settings.data_dir

    # 1. 读取同花顺行业数据
    hy_path = root_data / "ext_data" / "ext_hy_ths" / "part.parquet"
    if not hy_path.exists():
        logger.warning("ext_hy_ths 不存在: %s", hy_path)
        return {}

    hy_df = pl.read_parquet(hy_path)
    if "所属同花顺行业" not in hy_df.columns:
        logger.warning("ext_hy_ths 缺少 '所属同花顺行业' 列")
        return {}

    # 2. 读取最新 enriched 日K
    enr_dates = sorted(root_data.glob("kline_daily_enriched/date=*"))
    if not enr_dates:
        logger.warning("kline_daily_enriched 无分区数据")
        return {}

    latest_date_dir = enr_dates[-1]
    enr_file = latest_date_dir / "part.parquet"
    if not enr_file.exists():
        logger.warning("kline_daily_enriched 最新日期文件不存在: %s", enr_file)
        return {}

    enr_df = pl.read_parquet(enr_file)

    # 3. 股票名称映射 (instruments 或 hy_df)
    name_map: dict[str, str] = {}
    inst_file = root_data / "instruments" / "instruments.parquet"
    if inst_file.exists():
        try:
            inst_df = pl.read_parquet(inst_file)
            name_map = dict(zip(inst_df["symbol"].to_list(), inst_df["name"].to_list()))
        except Exception as e:  # noqa: BLE001
            logger.debug("read instruments for name map failed: %s", e)

    # 补充 hy_df 中的股票简称
    if "股票简称" in hy_df.columns and "symbol" in hy_df.columns:
        for sym, sname in zip(hy_df["symbol"].to_list(), hy_df["股票简称"].to_list()):
            if sym and sname and sym not in name_map:
                name_map[sym] = sname

    # 4. 提取一级行业
    hy_df = hy_df.with_columns(
        pl.col("所属同花顺行业").map_elements(_get_primary_industry, return_dtype=pl.Utf8).alias("l1_industry")
    )

    merged = enr_df.join(hy_df.select(["symbol", "l1_industry"]), on="symbol", how="inner")
    industries = sorted([i for i in merged["l1_industry"].unique().to_list() if i])

    results: dict[str, list[dict[str, Any]]] = {}

    for ind in industries:
        ind_df = merged.filter(pl.col("l1_industry") == ind)
        # 排除 ST、*ST 和退市整理期股票
        valid_symbols = [
            s for s in ind_df["symbol"].to_list()
            if not ("ST" in name_map.get(s, "") or "退" in name_map.get(s, ""))
        ]
        ind_df = ind_df.filter(pl.col("symbol").is_in(valid_symbols))
        if ind_df.is_empty():
            continue

        selected: list[dict[str, Any]] = []
        selected_symbols: set[str] = set()

        # 因子 1: 连板高度龙头 (consecutive_limit_ups >= 1)
        zt_df = ind_df.filter(pl.col("consecutive_limit_ups") > 0).sort(
            ["consecutive_limit_ups", "amount"], descending=[True, True]
        )
        for row in zt_df.head(2).iter_rows(named=True):
            sym = row["symbol"]
            consec = row.get("consecutive_limit_ups", 0)
            tag = f"{consec}连板龙头" if consec > 1 else "首板龙头"
            selected.append({
                "symbol": sym,
                "name": name_map.get(sym, sym),
                "tag": tag,
                "amount": float(row.get("amount") or 0.0),
                "turnover_rate": float(row.get("turnover_rate") or 0.0),
                "consecutive_limit_ups": consec,
            })
            selected_symbols.add(sym)

        # 因子 2: 资金容量中军核心 (行业成交额 Top 1~3)
        amt_df = ind_df.sort("amount", descending=True)
        for row in amt_df.iter_rows(named=True):
            sym = row["symbol"]
            if sym not in selected_symbols:
                selected.append({
                    "symbol": sym,
                    "name": name_map.get(sym, sym),
                    "tag": "成交额中军",
                    "amount": float(row.get("amount") or 0.0),
                    "turnover_rate": float(row.get("turnover_rate") or 0.0),
                    "consecutive_limit_ups": row.get("consecutive_limit_ups", 0),
                })
                selected_symbols.add(sym)
            if len(selected) >= 4:
                break

        # 因子 3: 高换手弹性先锋 (成交额 > 8000万, 换手率居前)
        active_df = ind_df.filter(pl.col("amount") > 8e7).sort("turnover_rate", descending=True)
        for row in active_df.iter_rows(named=True):
            sym = row["symbol"]
            if sym not in selected_symbols:
                tr = float(row.get("turnover_rate") or 0.0)
                selected.append({
                    "symbol": sym,
                    "name": name_map.get(sym, sym),
                    "tag": f"高换手先锋({tr:.1f}%)" if tr < 100 else "高换手先锋",
                    "amount": float(row.get("amount") or 0.0),
                    "turnover_rate": tr,
                    "consecutive_limit_ups": row.get("consecutive_limit_ups", 0),
                })
                selected_symbols.add(sym)
            if len(selected) >= 5:
                break

        # 如果不满 3 只，继续用成交额补足至至少 3 只
        if len(selected) < 3:
            for row in amt_df.iter_rows(named=True):
                sym = row["symbol"]
                if sym not in selected_symbols:
                    selected.append({
                        "symbol": sym,
                        "name": name_map.get(sym, sym),
                        "tag": "核心标的",
                        "amount": float(row.get("amount") or 0.0),
                        "turnover_rate": float(row.get("turnover_rate") or 0.0),
                        "consecutive_limit_ups": row.get("consecutive_limit_ups", 0),
                    })
                    selected_symbols.add(sym)
                if len(selected) >= 3:
                    break

        results[ind] = selected[:5]

    return results


def populate_sector_watchlist(data_dir: Path | None = None) -> dict[str, Any]:
    """甄选各板块核心股票并写入自选分类列表。

    保留已有“默认”分组标的，覆盖/更新板块分类标的。
    """
    sectors_map = select_sector_core_stocks(data_dir)
    if not sectors_map:
        return {"success": False, "message": "未能甄选到板块股票，请检查行情数据或行业扩展表"}

    # 批次组装记录
    batch_records: list[dict[str, str]] = []
    for sector_name, stocks in sectors_map.items():
        for s in stocks:
            batch_records.append({
                "symbol": s["symbol"],
                "group": sector_name,
                "note": f"{sector_name}·{s['tag']}",
            })

    added_count = watchlist.batch_upsert_grouped(batch_records)
    return {
        "success": True,
        "total_sectors": len(sectors_map),
        "total_stocks_added": added_count,
        "sectors": {k: len(v) for k, v in sectors_map.items()},
    }
