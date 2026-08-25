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

from app.services.news_service import NewsService

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
    """获取 7x24 实时财经快讯。"""
    svc = _get_news_service(request)
    items = svc.fetch_live_flash(limit=limit)
    return {"items": items, "total": len(items)}


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
