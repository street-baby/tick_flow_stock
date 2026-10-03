# -*- coding: utf-8 -*-
"""五分钟涨速排行榜 API。"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.services.speed_rank_service import get_speed_rank_top50

router = APIRouter(prefix="/api/speed-rank", tags=["speed-rank"])


@router.get("/top50")
def speed_rank_top50(
    limit: int = Query(50, ge=1, le=100, description="返回条数 (默认50)"),
    sort_by: str = Query("speed_5m", description="排序依据: speed_5m (5分钟涨速) | speed (实时涨速)"),
    min_amount: float = Query(0.0, description="最低成交额过滤 (元)"),
    refresh: bool = Query(False, description="是否强制穿透缓存刷新"),
):
    """获取全市场五分钟涨速排行榜 (Top 50)。"""
    return get_speed_rank_top50(
        limit=limit,
        sort_by=sort_by,
        min_amount=min_amount,
        force_refresh=refresh,
    )
