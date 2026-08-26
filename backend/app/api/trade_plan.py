"""短线趋势资金共振交易系统 API 路由。

提供:
- 市场环境与仓位门控查询
- 每日开盘执行计划
- 持仓管理与分级止盈止损提示
- 一键下单/平仓与复盘日志
- 系统交易参数配置
"""
from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Body, Query, Request
from pydantic import BaseModel

from app.services.trading_system import TradingSystemService

router = APIRouter(prefix="/api/trade-plan", tags=["trade_plan"])


def _get_service(request: Request) -> TradingSystemService:
    data_dir = request.app.state.repo.store.data_dir
    return TradingSystemService(data_dir)


class PositionCreateReq(BaseModel):
    symbol: str
    name: str | None = None
    buy_price: float
    shares: int
    stop_loss_price: float
    tp_1r: float | None = None
    tp_15r: float | None = None
    tp_2r: float | None = None
    entry_strategy: str | None = "短线共振"
    notes: str | None = ""


class PositionCloseReq(BaseModel):
    symbol: str
    sell_price: float
    sell_shares: int | None = None
    reason: str | None = "主动止盈/止损"


@router.get("/market-gate")
def get_market_gate(request: Request):
    """获取当前市场环境、评分、总仓位限制及回撤熔断状态。"""
    srv = _get_service(request)
    return srv.get_market_gate()


@router.get("/daily")
def get_daily_plan(request: Request):
    """生成今日开盘执行计划 (含买入理由、仓位测算、防追高预警、分级止盈目标)。"""
    srv = _get_service(request)
    return srv.generate_daily_trade_plan()


@router.get("/positions")
def get_positions(request: Request):
    """获取当前持仓列表与实时分级止盈止损动作预警。"""
    srv = _get_service(request)
    return srv.get_active_positions()


@router.post("/positions")
def add_position(request: Request, req: PositionCreateReq):
    """一键执行买入计划 / 手动录入持仓。"""
    srv = _get_service(request)
    return srv.add_position(req.model_dump())


@router.post("/positions/close")
def close_position(request: Request, req: PositionCloseReq):
    """平仓（全部或部分）并记录交易复盘日志。"""
    srv = _get_service(request)
    return srv.close_position(
        symbol=req.symbol,
        sell_price=req.sell_price,
        sell_shares=req.sell_shares,
        reason=req.reason or "主动止盈/止损",
    )


@router.get("/history")
def get_trade_history(request: Request):
    """获取交易复盘日志与胜率、盈亏比等统计指标。"""
    srv = _get_service(request)
    return srv.get_trade_history()


@router.get("/settings")
def get_settings(request: Request):
    """获取系统交易与风控参数配置。"""
    srv = _get_service(request)
    return srv.get_settings()


@router.post("/settings")
def update_settings(request: Request, settings: dict[str, Any] = Body(...)):
    """更新系统交易与风控参数配置。"""
    srv = _get_service(request)
    return srv.save_settings(settings)


@router.get("/custom")
def get_custom_plans(request: Request):
    """获取所有自定义买入计划。"""
    srv = _get_service(request)
    return srv.get_custom_plans()


@router.post("/custom")
def save_custom_plan(request: Request, plan: dict[str, Any] = Body(...)):
    """新增或更新一条用户自定义开盘买入计划。"""
    srv = _get_service(request)
    return srv.save_custom_plan(plan)


@router.delete("/custom/{symbol}")
def delete_custom_plan(request: Request, symbol: str):
    """删除一条自定义开盘买入计划。"""
    srv = _get_service(request)
    return srv.delete_custom_plan(symbol)


@router.get("/quote-lookup")
def lookup_stock_quote(
    request: Request,
    symbol: str = Query(..., description="股票代码，如 601579.SH"),
    buy_price: float | None = Query(None, description="自定义计划买入价"),
    stop_loss_pct: float | None = Query(None, description="自定义止损比例，如 0.05"),
):
    """根据股票代码实时获取最新价格，并自动测算买入价、止损价、算仓股数与止盈阶梯。"""
    srv = _get_service(request)
    return srv.lookup_stock_plan_preview(
        symbol=symbol,
        custom_buy_price=buy_price,
        custom_stop_loss_pct=stop_loss_pct,
    )


@router.get("/ai-copilot")
def get_ai_market_copilot(request: Request):
    """获取 AI 看盘决策大脑：大盘研判 + 板块共振 + 竞价抢筹 + 最高盈利期望标的 + 实时追进动态 + 动态调仓建议。"""
    srv = _get_service(request)
    return srv.get_ai_market_copilot()


@router.get("/tail-market")
def get_tail_market_plan(request: Request):
    """获取 14:30 尾盘极高胜率选股策略 (胜率 86.3% · 回撤 1.0%) 选股与执行计划。"""
    srv = _get_service(request)
    return srv.get_tail_market_plan()




