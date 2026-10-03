# -*- coding: utf-8 -*-
"""五分钟涨速排行榜服务 (基于智兔数服 Zhitu API)。

通过智兔数服全市场实时快照，提取并计算全市场股票的 5 分钟涨速 (fm)、实时涨速 (zs)、
量比、换手率与涨跌幅，筛选前 50 只涨速最猛的核心标的。
内置防 429 智能缓存保护与磁盘持久化兜底，保证低延迟与高可用。
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, List, Optional

import polars as pl

from app.config import settings
from app.plugins.zhitu.client import ZhituClient, to_standard_code

logger = logging.getLogger(__name__)

# 内存缓存与刷新间隔 (秒)
_CACHE_TTL = 10.0
_cache_lock = threading.Lock()
_mem_cache: Optional[dict[str, Any]] = None
_last_fetch_time: float = 0.0


def _cache_file_path() -> Path:
    p = settings.data_dir / "user_data" / "zhitu_speed_rank_cache.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _load_disk_cache() -> Optional[dict[str, Any]]:
    p = _cache_file_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            logger.debug("读取 speed_rank 磁盘缓存失败: %s", e)
    return None


def _save_disk_cache(data: dict[str, Any]) -> None:
    p = _cache_file_path()
    try:
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.debug("写入 speed_rank 磁盘缓存失败: %s", e)


def _load_meta_map() -> dict[str, tuple[str, str]]:
    """加载股票名称与同花顺行业映射: {symbol: (name, industry)}"""
    meta_map: dict[str, tuple[str, str]] = {}

    # 1. 行业表
    hy_path = settings.data_dir / "ext_data" / "ext_hy_ths" / "part.parquet"
    if hy_path.exists():
        try:
            df = pl.read_parquet(hy_path)
            for row in df.iter_rows(named=True):
                sym = row.get("symbol")
                if not sym:
                    continue
                name = row.get("股票简称") or ""
                hy = row.get("所属同花顺行业") or ""
                l1 = hy.split("-")[0].strip() if hy else ""
                meta_map[sym] = (name, l1)
        except Exception as e:
            logger.debug("读取 ext_hy_ths 失败: %s", e)

    # 2. 补充 instruments 表名称
    inst_path = settings.data_dir / "instruments" / "instruments.parquet"
    if inst_path.exists():
        try:
            df_inst = pl.read_parquet(inst_path)
            for row in df_inst.iter_rows(named=True):
                sym = row.get("symbol")
                if not sym:
                    continue
                name = row.get("name") or ""
                if sym not in meta_map:
                    meta_map[sym] = (name, "")
                elif not meta_map[sym][0]:
                    meta_map[sym] = (name, meta_map[sym][1])
        except Exception as e:
            logger.debug("读取 instruments 失败: %s", e)

    return meta_map


def get_speed_rank_top50(
    limit: int = 50,
    sort_by: str = "speed_5m",
    min_amount: float = 0.0,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """获取全市场 5 分钟涨速排行榜 (Top 50)。

    sort_by: 'speed_5m' (5分钟涨速) | 'speed' (当前实时涨速)
    min_amount: 最低成交额过滤 (元)
    """
    global _mem_cache, _last_fetch_time

    now = time.time()
    raw_data: Optional[list[dict]] = None

    with _cache_lock:
        # 1. 如果内存缓存有效且非强制刷新，直接使用缓存
        if not force_refresh and _mem_cache is not None and (now - _last_fetch_time) < _CACHE_TTL:
            raw_data = _mem_cache.get("raw")

        # 2. 缓存失效，从智兔拉取
        if raw_data is None:
            zc = ZhituClient()
            data = zc.get_json("/hs/public/realall")
            if data and isinstance(data, list) and len(data) > 0:
                raw_data = data
                _mem_cache = {"raw": raw_data, "time": now}
                _last_fetch_time = now
            else:
                # 3. 若触发 429 避让或网络波动，优先降级使用历史缓存或磁盘缓存
                if _mem_cache and "raw" in _mem_cache:
                    raw_data = _mem_cache["raw"]
                else:
                    disk_data = _load_disk_cache()
                    if disk_data and "rows" in disk_data:
                        return disk_data

    if not raw_data:
        # 兜底返回空或旧磁盘
        disk = _load_disk_cache()
        if disk:
            return disk
        return {"as_of": None, "total": 0, "source": "zhitu", "rows": []}

    meta_map = _load_meta_map()
    parsed_rows: list[dict[str, Any]] = []
    latest_time_str = ""

    for r in raw_data:
        dm = r.get("dm")
        if not dm:
            continue
        symbol = to_standard_code(str(dm))

        # 过滤非标准或者未上市/停牌 (价格为0)
        p = float(r.get("p") or 0.0)
        if p <= 0:
            continue

        cje = float(r.get("cje") or 0.0)
        if min_amount > 0 and cje < min_amount:
            continue

        fm = float(r.get("fm") or 0.0)  # 5分钟涨速 %
        zs = float(r.get("zs") or 0.0)  # 实时涨速 %
        pc = float(r.get("pc") or 0.0)  # 当日涨幅 %
        ud = float(r.get("ud") or 0.0)  # 涨跌额
        lb = float(r.get("lb") or 0.0)  # 量比
        hs = float(r.get("hs") or 0.0)  # 换手率 %
        zf = float(r.get("zf") or 0.0)  # 振幅 %
        sz = float(r.get("sz") or 0.0)  # 总市值
        lt = float(r.get("lt") or 0.0)  # 流通市值
        t_str = r.get("t") or ""
        if t_str and t_str > latest_time_str:
            latest_time_str = t_str

        name, ind = meta_map.get(symbol, ("", ""))

        parsed_rows.append({
            "symbol": symbol,
            "name": name or symbol,
            "industry": ind,
            "price": p,
            "change_pct": pc,
            "change_amount": ud,
            "speed_5m": fm,
            "speed": zs,
            "volume_ratio": lb,
            "turnover_rate": hs,
            "amount": cje,
            "amplitude": zf,
            "total_mv": sz,
            "float_mv": lt,
            "time": t_str,
        })

    # 排序
    sort_key = "speed" if sort_by == "speed" else "speed_5m"
    parsed_rows.sort(key=lambda x: x.get(sort_key) or -999.0, reverse=True)

    # 取前 limit 名
    top_rows = parsed_rows[:limit]

    # 添加排名序号
    for rank, row in enumerate(top_rows, 1):
        row["rank"] = rank

    result = {
        "as_of": latest_time_str or time.strftime("%Y-%m-%d %H:%M:%S"),
        "total": len(top_rows),
        "source": "zhitu",
        "rows": top_rows,
    }

    # 异步或顺带落盘持久化
    if top_rows:
        _save_disk_cache(result)

    return result
