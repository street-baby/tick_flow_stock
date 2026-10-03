# -*- coding: utf-8 -*-
"""新闻与「明天炒什么」题材催化前瞻 API 路由。"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from typing import Any, List, Optional
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from app.services.news_service import NewsService, flash_feed
from app.services.sector_brief import (
    SectorBriefAIError,
    build_sector_brief,
    narrate_sector_brief,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/news", tags=["news"])


class CatalystItem(BaseModel):
    id: Optional[str] = None
    date: Optional[str] = None
    date_label: Optional[str] = None
    tag: str
    title: str
    summary: str
    sector_change_pct: Optional[float] = 0.0
    stocks: Optional[List[dict]] = []


class AIGenerateRequest(BaseModel):
    target_date: Optional[str] = None
    prompt: Optional[str] = "结合当日全天重大产业政策、全球科技突破、央视与财联社/新浪快讯及主力资金热点，深度提炼出下一个交易日最具爆发潜力的3~5个前瞻主线题材，给出核心逻辑与对应A股龙头受益股。"


class MorningBriefGenerateRequest(BaseModel):
    target_date: Optional[str] = None
    prompt: Optional[str] = "请根据隔夜外盘（美股纳指、半导体、大宗商品）、夜间重大政策与今晨早报，生成今日开盘前瞻研判、情绪基调、早盘核心关注题材与竞价操作策略。"


def _get_news_service(request: Request) -> NewsService:
    data_dir = request.app.state.repo.store.data_dir
    return NewsService(data_dir=data_dir)


def _flash_live_meta(request: Request) -> dict:
    """快讯新鲜度元信息: 池子最后更新时间 + 抓取节奏。

    前端用它显示「实时更新 · 刚刚 / 12 秒前」, 而不是盲猜数据新旧。
    """
    poller = getattr(request.app.state, "news_poller", None)
    interval = poller.interval if poller is not None else 0.0
    return {
        **NewsService.flash_meta(),
        "poll_interval_seconds": round(float(interval or 0.0), 1),
    }


@router.get("/tomorrow")
def get_tomorrow_catalysts(
    request: Request,
    keyword: str = Query("", description="搜索关键词/题材/股票"),
    date: str = Query("", description="日期过滤 YYYY-MM-DD"),
):
    """获取「明天炒什么」前瞻题材列表与核心受益股（含智兔实时行情数据）。"""
    svc = _get_news_service(request)
    items = svc.get_tomorrow_catalysts(keyword=keyword, date_filter=date)
    return {"items": items, "total": len(items)}


@router.post("/tomorrow")
def save_catalyst(
    item: CatalystItem,
    request: Request,
):
    """保存或编辑前瞻题材项。"""
    svc = _get_news_service(request)
    saved = svc.save_catalyst(item.dict())
    return {"status": "ok", "item": saved}


@router.delete("/tomorrow/{item_id}")
def delete_catalyst(
    item_id: str,
    request: Request,
):
    """删除前瞻题材项。"""
    svc = _get_news_service(request)
    ok = svc.delete_catalyst(item_id)
    return {"status": "ok" if ok else "error"}


@router.get("/flash")
def get_live_flash(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
):
    """获取 7x24 实时财经快讯(服务端滚动累积, 不只是一个 50 条的滑动窗口)。"""
    svc = _get_news_service(request)
    items = svc.fetch_live_flash(limit=limit)
    return {"items": items, "total": len(items), **_flash_live_meta(request)}


class SectorBriefNarrateRequest(BaseModel):
    kind: str = "concept"
    top_n: int = 5


@router.get("/sector-brief")
def get_sector_brief(
    request: Request,
    kind: str = Query("concept", pattern="concept|industry", description="维度: concept 概念 / industry 行业"),
    top_n: int = Query(5, ge=3, le=10, description="利好/利空各取前 N 个板块"),
):
    """板块简报: 由真实行情选出利好/利空板块(含四维归因/关联快讯/关联标的)。

    只读缓存里的 AI 文案, 不触发 LLM 调用; ai_status 表明当前状态:
    cached(有当日文案) / missing(未生成) / unavailable(无 AI 或数据为空)。
    快讯池来自 NewsService(多源合并, 进程内缓存), 池子为空时只出盘面/外围维度。
    """
    repo = request.app.state.repo
    return build_sector_brief(repo, kind=kind, top_n=top_n, news_service=_get_news_service(request))


@router.post("/sector-brief/narrate")
async def narrate_sector_brief_api(
    req: SectorBriefNarrateRequest,
    request: Request,
):
    """为当日板块简报生成 AI 驱动归因文案(同一交易日命中缓存不重复调用)。

    AI 未配置 / 调用失败 / 返回无法解析 → 502, 前端降级显示数据派生归因。
    """
    repo = request.app.state.repo
    try:
        return await narrate_sector_brief(
            repo,
            kind=req.kind,
            top_n=req.top_n,
            news_service=_get_news_service(request),
        )
    except SectorBriefAIError as exc:
        logger.warning("板块简报 AI 文案不可用: %s", exc)
        raise HTTPException(status_code=502, detail=f"AI 板块研判生成失败: {exc}") from exc


@router.get("/flash-tagged")
def get_flash_tagged(
    request: Request,
    limit: int = Query(200, ge=1, le=300),
):
    """7x24 快讯 + 利好/利空方向标签 + 关联板块/标的。

    返回里带 updated_at / poll_interval_seconds —— 前端据此显示「实时更新」状态。
    """
    from app.services.flash_classifier import load_lexicon, tag_flash_items

    svc = _get_news_service(request)
    items = svc.fetch_live_flash(limit=limit)
    lexicon = load_lexicon(request.app.state.repo)
    tagged = tag_flash_items(items, lexicon)
    return {"items": tagged, "total": len(tagged), **_flash_live_meta(request)}


@router.get("/live-status")
def get_news_live_status(request: Request):
    """7x24 快讯实时抓取状态: 抓取节奏/累计新增/连续失败数与最近错误。

    无 NewsPoller(未启动或已关闭)时退化为只报滚动池现状 —— 此时快讯靠
    读取路径的兜底同步抓取, 仍然是「不断更新」, 只是节奏跟请求走。
    """
    poller = getattr(request.app.state, "news_poller", None)
    if poller is not None:
        return poller.get_status()
    return {
        "running": False,
        "enabled": False,
        "interval_seconds": 0.0,
        "stored": len(flash_feed),
        "latest_flash_time": flash_feed.latest_time(),
        **_flash_live_meta(request),
    }


@router.get("/morning-brief")
def get_morning_brief(
    request: Request,
):
    """获取今日早盘开盘前瞻精要。"""
    svc = _get_news_service(request)
    brief = svc.get_morning_brief()
    return {"brief": brief}


@router.post("/morning-brief/ai-generate")
async def ai_generate_morning_brief(
    req: MorningBriefGenerateRequest,
    request: Request,
):
    """通过 AI 整合隔夜外盘与最新新闻生成早盘开盘前瞻。"""
    from app.services.ai_provider import generate_ai_text

    svc = _get_news_service(request)
    target_date = req.target_date or date.today().strftime("%Y-%m-%d")

    # 获取全天及早盘新闻
    news_items = svc.fetch_akshare_daily_news(target_date=target_date)
    news_text = "\n".join([f"- [{n.get('source')}] {n.get('title')}: {n.get('content')[:120]}" for n in news_items[:30]])

    system_prompt = """你是一位资深的A股顶级操盘手与晨会首席宏观策略分析师。
请根据提供的隔夜市场要闻与最新早盘快讯，生成一份精准干练的【今日早盘开盘前瞻·盘前必读】。
必须严格输出标准的 JSON 对象（不要输出 markdown 代码块以外的多余文字），格式如下：
{
  "sentiment": "情绪基调（例如：结构分化 · 聚焦核心 / 强势进攻 / 谨慎防守）",
  "sentiment_color": "amber",
  "headline": "一句话提炼今晨最大看点（如：隔夜美股半导体大涨，国内低空与储能政策共振）",
  "overnight_summary": "隔夜外盘走势（美股三大指数、芯片股、黄金原油大宗、汇率）精要（100字）",
  "core_focus": [
    {"tag": "主线1", "desc": "驱动要点与开盘关注方向"},
    {"tag": "主线2", "desc": "驱动要点与开盘关注方向"},
    {"tag": "主线3", "desc": "驱动要点与开盘关注方向"}
  ],
  "opening_tactics": "今日竞价与开盘操作建议（80字）"
}
"""
    user_message = f"请为 {target_date} 开盘生成早盘前瞻分析：\n\n【最新抓取的财经要闻参考】：\n{news_text}"

    try:
        raw_reply = await generate_ai_text(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.3,
            max_tokens=2000,
        )
    except Exception as e:
        logger.warning("AI 早盘前瞻生成失败: %s", e)
        raise HTTPException(status_code=502, detail=f"AI 服务调用失败: {e}")

    # 解析 JSON
    json_match = re.search(r"\{.*\}", raw_reply, re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group(0))
            parsed["date"] = target_date
            saved = svc.save_morning_brief(parsed)
            return {"status": "ok", "brief": saved}
        except Exception as e:
            logger.warning("解析 AI 返回 JSON 失败: %s", e)

    return {"status": "partial", "raw": raw_reply}


@router.post("/ai-generate")
async def ai_generate_tomorrow(
    req: AIGenerateRequest,
    request: Request,
):
    """调用 AI 智能分析指定日期 (如20号) 全天重大新闻，提炼生成「明天炒什么」前瞻题材。"""
    from app.services.ai_provider import generate_ai_text

    svc = _get_news_service(request)
    target_date = req.target_date or date.today().strftime("%Y-%m-%d")
    next_date = (date.fromisoformat(target_date) + timedelta(days=1)).strftime("%Y-%m-%d")

    # 通过 AKShare + 7x24 抓取该日期所有全天新闻
    news_items = svc.fetch_akshare_daily_news(target_date=target_date)
    news_text = "\n".join([f"- [{n.get('source')}] {n.get('title')}: {n.get('content')[:140]}" for n in news_items[:35]])

    system_prompt = f"""你是一位资深的A股顶级游资与量化题材策略专家。
请根据提供的 {target_date} 全天新闻热点与产业政策，深度梳理并提炼出【下一个交易日（{next_date}）最具爆发潜力的3~5个前瞻题材】。
必须严格输出标准的 JSON 数组格式（不要输出 markdown 代码块以外的多余文字），示例结构：
[
  {{
    "tag": "题材标签（如：存储芯片/低空经济/先进封装/电网设备/铜箔）",
    "title": "重磅事件或催化主标题（吸引眼球且专业）",
    "summary": "核心驱动逻辑与产业供需格局详细解读（100字左右）",
    "sector_change_pct": 2.1,
    "stocks": [
      {{"symbol": "601609.SH", "name": "金田股份"}},
      {{"symbol": "000563.SZ", "name": "陕国投A"}}
    ]
  }}
]
"""
    user_message = f"{req.prompt}\n\n【{target_date} 全天热点要闻参考】：\n{news_text}"

    try:
        raw_reply = await generate_ai_text(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.3,
            max_tokens=2500,
        )
    except Exception as e:
        logger.warning("AI 前瞻分析生成失败: %s", e)
        raise HTTPException(status_code=502, detail=f"AI 服务调用失败: {e}")

    # 解析 JSON
    json_match = re.search(r"\[\s*\{.*\}\s*\]", raw_reply, re.DOTALL)
    if json_match:
        try:
            parsed = json.loads(json_match.group(0))
            for it in parsed:
                it["date"] = next_date
                it["date_label"] = f"{next_date} 下一个交易日"
                svc.save_catalyst(it)
            return {"status": "ok", "items": parsed, "raw": raw_reply}
        except Exception as e:
            logger.warning("解析 AI 返回 JSON 失败: %s", e)

    return {"status": "partial", "items": [], "raw": raw_reply}


def _get_catalyst_scheduler(request: Request):
    sched = getattr(request.app.state, "catalyst_scheduler", None)
    if not sched:
        from app.services.catalyst_scheduler import TomorrowCatalystScheduler
        data_dir = request.app.state.repo.store.data_dir
        sched = TomorrowCatalystScheduler(data_dir=data_dir)
        request.app.state.catalyst_scheduler = sched
    return sched


@router.get("/status")
def get_catalyst_scheduler_status(request: Request):
    """获取明天炒什么题材前瞻调度器的自动运行状态。"""
    sched = _get_catalyst_scheduler(request)
    return sched.get_status()


@router.post("/trigger-now")
async def trigger_catalyst_analysis_now(
    request: Request,
    mode: str = Query("30min", description="模式: '30min' 滚动分析 或 '2355' 全天终极汇总"),
):
    """即刻触发一次滚动分析或全天终极汇总。"""
    sched = _get_catalyst_scheduler(request)
    if mode == "2355":
        res = await sched.run_2355_daily_synthesis(force=True)
    else:
        res = await sched.run_30min_cycle(force=True)
    return res

