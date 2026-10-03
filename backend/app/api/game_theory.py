# -*- coding: utf-8 -*-
"""博弈派分析 API 端点。"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/game-theory", tags=["game-theory"])


def _get_engine(request: Request):
    return getattr(request.app.state, "game_theory_engine", None)


@router.get("/temperature")
async def get_temperature(request: Request):
    """全市场博弈温度计"""
    engine = _get_engine(request)
    if not engine:
        return JSONResponse({"error": "博弈引擎未初始化"}, status_code=503)
    return engine.get_temperature()


@router.get("/fear-pool")
async def get_fear_pool(request: Request, limit: int = 20):
    """散户恐惧区 · 潜在买入池（散户怕、机构买）"""
    engine = _get_engine(request)
    if not engine:
        return JSONResponse({"error": "博弈引擎未初始化"}, status_code=503)
    return engine.get_fear_pool(limit)


@router.get("/danger-list")
async def get_danger_list(request: Request, limit: int = 20):
    """散户拥挤区 · 危险规避清单（散户疯、机构跑）"""
    engine = _get_engine(request)
    if not engine:
        return JSONResponse({"error": "博弈引擎未初始化"}, status_code=503)
    return engine.get_danger_list(limit)


@router.get("/stock/{symbol}")
async def get_stock_score(request: Request, symbol: str):
    """单股博弈评分详情"""
    engine = _get_engine(request)
    if not engine:
        return JSONResponse({"error": "博弈引擎未初始化"}, status_code=503)
    result = engine.get_stock_score(symbol)
    if result is None:
        return JSONResponse({"error": f"未找到 {symbol} 的博弈评分"}, status_code=404)
    return result


@router.get("/report")
async def get_report(request: Request):
    """AI 每日博弈报告"""
    engine = _get_engine(request)
    if not engine:
        return JSONResponse({"error": "博弈引擎未初始化"}, status_code=503)
    return engine.get_report()


@router.get("/history")
async def get_history(request: Request, days: int = 30):
    """博弈温度历史趋势"""
    engine = _get_engine(request)
    if not engine:
        return JSONResponse({"error": "博弈引擎未初始化"}, status_code=503)
    return engine.get_temperature_history(days)


@router.get("/status")
async def get_status(request: Request):
    """博弈引擎运行状态"""
    engine = _get_engine(request)
    if not engine:
        return JSONResponse({"error": "博弈引擎未初始化"}, status_code=503)
    return engine.get_status()


@router.post("/trigger")
async def trigger_analysis(request: Request):
    """手动触发一次全量博弈分析"""
    engine = _get_engine(request)
    if not engine:
        return JSONResponse({"error": "博弈引擎未初始化"}, status_code=503)

    import asyncio
    asyncio.create_task(engine.run_full_analysis())
    return {"status": "triggered", "message": "博弈分析已触发，数据采集中(约1-2分钟)..."}
