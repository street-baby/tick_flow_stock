"""龙虎榜 API 路由 (Dragon & Tiger List API Router)"""

from __future__ import annotations

from typing import Any, Dict, List
from fastapi import APIRouter, Query

from app.services.longhubang_service import lhb_service

router = APIRouter(prefix="/api/lhb", tags=["LongHuBang"])


@router.get("/daily")
def get_daily_lhb() -> Dict[str, Any]:
    """今日/最新交易日龙虎榜详情，包含分类归类与汇总。"""
    return lhb_service.get_daily_lhb()


@router.get("/stock-stats")
def get_stock_stats(days: int = Query(default=5, description="统计天数: 5, 10, 30, 60")) -> List[Dict[str, Any]]:
    """个股上榜统计 (近 5/10/30/60 日)。"""
    return lhb_service.get_stock_stats(days=days)


@router.get("/branch-stats")
def get_branch_stats(days: int = Query(default=5, description="统计天数: 5, 10, 30, 60")) -> List[Dict[str, Any]]:
    """营业部上榜统计 (近 5/10/30/60 日)。"""
    return lhb_service.get_branch_stats(days=days)


@router.get("/institution-stats")
def get_institution_stats(days: int = Query(default=5, description="统计天数: 5, 10, 30, 60")) -> List[Dict[str, Any]]:
    """机构席位追踪统计 (近 5/10/30/60 日)。"""
    return lhb_service.get_institution_stats(days=days)


@router.get("/institution-details")
def get_institution_details() -> List[Dict[str, Any]]:
    """机构席位成交明细流水。"""
    return lhb_service.get_institution_details()
