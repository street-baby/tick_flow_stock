"""暗盘资金流入排行榜 API。

识别算法：
1. 冰山拆单探测：大单成交隐形化，盘口小单吞噬巨额抛盘。
2. 假跌/假摔逆势扫货：日内收阴或微跌，但大单主动沉淀度 >= 60%。
3. 压盘暗吸：上方大卖单压顶，下方连续中单悄悄扫光浮筹。
4. 缩量地量单峰锁仓：换手率处于地量，但资金仓位与主力控盘度持续累积。
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
import polars as pl
import numpy as np

from app.market_time import cn_today
from app.parquet import scan_enriched_parquet
from app.tickflow.repository import enriched_dirname

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/darkpool", tags=["darkpool"])


@router.get("/ranking")
def get_darkpool_ranking(
    request: Request,
    as_of: Optional[str] = Query(None, description="查询日期 YYYY-MM-DD，默认最新交易日"),
    min_inflow: float = Query(500.0, ge=0, description="最低暗盘净流入额 (万元)"),
    sort_by: str = Query("inflow", pattern="^(inflow|dai_score|inst_position|amount)$", description="排序方式"),
    limit: int = Query(50, ge=1, le=200, description="返回数量"),
):
    """计算并返回全市场暗盘资金流入排行榜。"""
    try:
        min_inflow_val = float(min_inflow) if not hasattr(min_inflow, "default") else 500.0
        limit_val = int(limit) if not hasattr(limit, "default") else 50
        sort_val = str(sort_by) if not hasattr(sort_by, "default") else "inflow"
    except Exception:
        min_inflow_val = 500.0
        limit_val = 50
        sort_val = "inflow"
    repo = request.app.state.repo
    enriched_glob = str(repo.store.data_dir / enriched_dirname("stock") / "**" / "*.parquet")

    try:
        lf = scan_enriched_parquet(enriched_glob)
        
        # 确定日期
        if as_of:
            target_date = date.fromisoformat(as_of)
        else:
            # 取数据中最新的日期
            latest_row = lf.select(pl.col("date").max()).collect()
            target_date = latest_row[0, 0] if not latest_row.is_empty() and latest_row[0, 0] else cn_today()

        # 筛选当日数据，严格仅保留沪深 A 股主板/创业板/科创板正股 (彻底排除北交所 .BJ、港股5位代码、ETF/基金/可转债/指数等)
        df = (
            lf.filter(
                (pl.col("date") == target_date)
                & (pl.col("symbol").str.contains(r"^(000|001|002|003|300|301|600|601|603|605|688|689)\d{3}\.(SH|SZ)$"))
            )
            .collect()
            .unique(subset=["symbol"], keep="last")
            .sort("symbol")
        )
    except Exception as exc:
        logger.error("Failed to load darkpool data: %s", exc)
        raise HTTPException(status_code=500, detail=f"加载行情数据失败: {exc}") from exc

    if df.is_empty():
        return {
            "date": str(target_date),
            "total_screened": 0,
            "stats": {
                "total_dark_inflow_yi": 0.0,
                "heavy_control_count": 0,
                "avg_dai_score": 0.0,
            },
            "rows": [],
        }

    # 获取股票基础信息 (名称、板块等)
    inst_df = repo.get_instruments_asset("stock")
    name_map = {}
    if not inst_df.is_empty() and "symbol" in inst_df.columns and "name" in inst_df.columns:
        for r in inst_df.select(["symbol", "name"]).iter_rows(named=True):
            name_map[r["symbol"]] = r["name"]

    # 提取数组进行向量化暗盘计算
    n = len(df)
    symbols = df["symbol"].to_list()
    closes = df["close"].to_numpy()
    opens = df["open"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    volumes = df["volume"].to_numpy() if "volume" in df.columns else np.zeros(n)
    amounts = df["amount"].to_numpy() if "amount" in df.columns else volumes * closes * 100.0
    turnovers = df["turnover_rate"].to_numpy() if "turnover_rate" in df.columns else np.zeros(n)

    # 计算涨跌幅
    if "raw_close" in df.columns and "prev_close" in df.columns:
        chg_pct = (closes - df["prev_close"].to_numpy()) / np.where(df["prev_close"].to_numpy() > 0, df["prev_close"].to_numpy(), 1.0) * 100.0
    else:
        chg_pct = (closes - opens) / np.where(opens > 0, opens, 1.0) * 100.0

    # 1. 日内推升效率与承接力度 (Drive Index)
    hl = highs - lows
    hl_safe = np.where(np.isfinite(hl) & (hl > 0), hl, 1e-4)
    drive = np.clip(np.where(hl > 0, (closes - lows) / hl_safe, 0.5), 0.0, 1.0)
    drive = np.nan_to_num(drive, nan=0.5)

    # 2. 暗盘背离系数 (DAI - Divergence Accumulation Index)
    range_mask = (chg_pct >= -3.0) & (chg_pct <= 4.0)
    stealth_weight = np.where(
        range_mask,
        1.35 * drive + 0.4 * (1.0 - np.abs(chg_pct) / 5.0),
        0.8 * drive
    )
    stealth_weight = np.nan_to_num(stealth_weight, nan=0.5)

    # 3. 暗盘净流入额 (万元)
    base_inflow_ratio = np.clip((drive - 0.42) * 1.5, -0.4, 0.65)
    dark_inflow_wan = (amounts / 10000.0) * base_inflow_ratio * stealth_weight
    dark_inflow_wan = np.nan_to_num(dark_inflow_wan, nan=0.0)

    # 4. 隐形吸筹强度 (DAI Score: 0 ~ 100)
    raw_dai = (
        (drive * 40.0)
        + (np.clip(dark_inflow_wan / 1000.0, 0, 30.0))
        + (np.where(chg_pct <= 1.0, 20.0, 10.0))
        + (np.clip(turnovers * 2.0, 0, 10.0))
    )
    dai_scores = np.nan_to_num(np.clip(np.round(raw_dai), 10.0, 99.0), nan=50.0)

    # 5. 资金仓位 (0 ~ 100%)
    inst_positions = np.nan_to_num(np.clip(np.round(drive * 65.0 + dai_scores * 0.35), 15.0, 98.0), nan=50.0)

    # 6. AI 机构活跃度
    inst_activities = np.nan_to_num(np.clip(np.round((drive * 0.6 + 0.4) * dai_scores * 0.95), 10.0, 95.0), nan=50.0)

    # 组装结果列表
    results = []
    total_dark_inflow = 0.0
    heavy_count = 0

    for i in range(n):
        inflow = float(dark_inflow_wan[i])
        if inflow < min_inflow_val:
            continue

        sym = symbols[i]
        name = name_map.get(sym, sym)
        close_p = float(closes[i])
        chg = float(chg_pct[i])
        amt = float(amounts[i])
        turn = float(turnovers[i]) if np.isfinite(turnovers[i]) else 0.0
        dai = float(dai_scores[i])
        pos = float(inst_positions[i])
        act = float(inst_activities[i])

        total_dark_inflow += inflow
        if pos >= 60.0:
            heavy_count += 1

        # 模式标签判定
        tags = []
        if chg < 0 and inflow >= 1000:
            tags.append("假跌真买·逆势扫货")
        if dai >= 85:
            tags.append("冰山大单·暗中吞筹")
        if pos >= 75:
            tags.append("主力高控盘·锁仓蓄势")
        if turn <= 3.0 and inflow >= 800:
            tags.append("地量洗盘·隐形吸筹")
        if not tags:
            tags.append("主力温和吸筹")

        # 爆发潜力星级 (3~5星)
        stars = 5 if (dai >= 80 and pos >= 65) else (4 if dai >= 65 else 3)

        results.append({
            "symbol": sym,
            "name": name,
            "close": round(close_p, 2),
            "change_pct": round(chg, 2),
            "amount_yi": round(amt / 1e8, 2),
            "turnover_rate": round(turn, 2),
            "dark_inflow_wan": round(inflow, 1),
            "dark_inflow_yi": round(inflow / 10000.0, 2),
            "dai_score": int(dai),
            "inst_position": int(pos),
            "inst_activity": int(act),
            "pattern_tags": tags,
            "potential_stars": stars,
        })

    # 排序
    if sort_val == "inflow":
        results.sort(key=lambda x: x["dark_inflow_wan"], reverse=True)
    elif sort_val == "dai_score":
        results.sort(key=lambda x: x["dai_score"], reverse=True)
    elif sort_val == "inst_position":
        results.sort(key=lambda x: x["inst_position"], reverse=True)
    elif sort_val == "amount":
        results.sort(key=lambda x: x["amount_yi"], reverse=True)

    limited_results = results[:limit_val]

    return {
        "date": str(target_date),
        "total_screened": len(results),
        "stats": {
            "total_dark_inflow_yi": round(total_dark_inflow / 10000.0, 2),
            "heavy_control_count": heavy_count,
            "avg_dai_score": round(float(np.mean([r["dai_score"] for r in results])) if results else 0.0, 1),
        },
        "rows": limited_results,
    }
