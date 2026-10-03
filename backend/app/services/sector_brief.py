# -*- coding: utf-8 -*-
"""板块简报 service —— 利好/利空板块 + 驱动归因(消息面/政策产业/盘面题材/外围指数)。

复用的现有资产(不新增数据源, 不平行实现板块聚合):
  - market_overview_builder._dimension_rank: 当日板块聚合(均涨幅/涨跌家数/成交额/领涨股/成分股)
  - rps_rotation.build_rps_rotation: N 个交易日板块涨幅排名矩阵 → 排名变化/热度/窗口累计
  - repository.get_enriched_latest / get_name_map: 当日个股 enrich(change_pct/amount/名称)
  - sector_drivers: 驱动分解与关联快讯(快讯池 + 外围指数快照 + 当日列)

输出契约(供前端 /news 资讯页消费):
  {
    "as_of": "2026-09-19" | null,
    "kind": "concept" | "industry",
    "member_count": 387,
    "days": 7,
    "bullish": [ <卡片>, ... ],          # 涨幅领先
    "bearish": [ <卡片>, ... ],          # 跌幅领先
    "generated_at": "2026-09-19T15:32:10+08:00",
    "ai_status": "cached" | "generated" | "missing" | "unavailable",
    "ai_generated_at": str | null,
    "ai_configured": bool,
  }
  卡片字段: name / change_pct(小数制) / rank / prev_rank / rank_change / heat(0-100) /
            count / up_count / down_count / amount(元) / leader / stocks(最多 3 只) /
            window_pct(窗口累计涨幅) / logic_stats(数据派生文案) /
            headline(一句话驱动摘要) / drivers(四维归因, 权重合计 100) /
            flash(关联快讯) / ai_logic(AI 文案, 未生成时 null)

AI 文案:
  - narrate_sector_brief() 一次 LLM 调用批量产出各板块的 headline / logic / drivers / flash_ids,
    落盘 data/user_data/sector_brief_ai.json, key = "<最新交易日>|<kind>|v2";
    同一交易日命中缓存直接复用, 不重复消耗 token。
  - AI 只能在我给你的快讯清单里选 flash_ids, 回池校验失败的编号一律丢弃
    (越界/非法一律不用, 绝不拿模型编的标题当新闻)。
  - AI 未配置 / 调用失败 / 无法解析 → 抛 SectorBriefAIError, 由 API 转 502;
    GET 接口完全不依赖 AI, 始终返回数据派生的归因与快讯。
"""
from __future__ import annotations

import json
import logging
import math
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

from app.services.market_overview_builder import _dimension_rank
from app.services.rps_rotation import build_rps_rotation
from app.services.sector_drivers import (
    _anchor_stock,
    build_drivers,
    flash_from_ids,
    format_driver_brief,
    overseas_snapshot,
    parse_ai_drivers,
    pool_for_prompt,
    select_pool_for_ai,
)

logger = logging.getLogger(__name__)

# 结果缓存: 板块聚合是 polars/parquet 操作, 但 rps 矩阵本身已有 120s 缓存,
# 这里只缓存拼装结果, TTL 取 60s 与 overview 的量级一致。
_CACHE_TTL = 60.0
_cache: dict[str, dict] = {}
_cache_ts: dict[str, float] = {}
# 跨线程读写锁: FastAPI 线程池读, 数据刷新线程 invalidate (与 api/overview.py 同模式)
_CACHE_LOCK = threading.RLock()

_AI_FILE_NAME = "sector_brief_ai.json"
# AI 输出结构版本: v1 只有 logic, v2 增加 headline/drivers/flash_ids。
# 写进缓存 key, 结构升级后旧缓存自然失效, 不会被当成新结构解析。
_AI_SCHEMA = "v2"
# 喂给模型的快讯条数上限: 一整套(两边各 5 个板块 + 清单)要 1 万 token 上下,
# 推理型模型(实测 deepseek 系)会在推理上把输出预算烧完而吐不出正文,
# 所以清单要瘦, 失败时再拆成单边请求。
# 每边单独一次请求(利好/利空各 5 个板块 + 24 条相关快讯)。
# 实测当前配置的推理型模型要对 5 个板块烧掉约 9k 推理 token, 才轮到正文;
# 一次性丢 10 个板块 + 60 条快讯会在推理上耗尽预算而吐不出正文(实测 max_tokens=8000 仍 0 字)。
# 这个预算对非推理模型没有副作用 —— 只按实际输出计费。
_AI_POOL_LIMIT = 24
_AI_MAX_TOKENS = 16000
# 推理模型耗时长, 单次调用给足超时(默认 180s 对 9k 推理 token 不够)
_AI_TIMEOUT = 420.0
_AI_SIDES: tuple[str, ...] = ("bullish", "bearish")
# 单卡片最多展示的关联标的不超过 3 只, 热度/文案都用同一组数据派生
_STOCK_LIMIT = 3
# 板块成分股少于该数量时剔除: 1~2 只成分股的"板块"是噪声, 容易霸榜
_MIN_MEMBERS = 3
_DEFAULT_DAYS = 7


class SectorBriefAIError(RuntimeError):
    """AI 文案不可用(未配置 / 调用失败 / 返回无法解析)。"""


def _finite(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _jsonable(value: Any) -> Any:
    """把结果里可能混进来的非 JSON 安全值收干净(dict/list 递归)。

    两类值在真实路径上都出现过, 而且后果比看起来重:
      - 非有限数(NaN / Inf): starlette 的 JSONResponse 用 allow_nan=False,
        序列化直接抛错 → 整条接口 500;
      - polars / numpy 标量(json 不认 numpy.float64): 同样抛 TypeError。

    一旦这种值进了 60s 结果缓存, 接口会持续 500 直到进程重启(重建才恢复)。
    在出口统一收干净, 比要求每个构造点自觉更可靠。
    """
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        # 含 numpy.float64(float 子类): 统一收成原生 float,
        # 非有限数 → None(starlette 的 JSONResponse 开了 allow_nan=False)
        number = float(value)
        return number if math.isfinite(number) else None
    item = getattr(value, "item", None)  # numpy / polars 标量
    if callable(item):
        try:
            return _jsonable(item())
        except Exception:  # noqa: BLE001
            return value
    isoformat = getattr(value, "isoformat", None)  # date / datetime
    if callable(isoformat):
        try:
            return isoformat()
        except Exception:  # noqa: BLE001
            return value
    return value


def invalidate_cache() -> None:
    """清空板块简报结果缓存(数据管道完成后调用, 避免返回旧数据)。"""
    with _CACHE_LOCK:
        _cache.clear()
        _cache_ts.clear()


# ================================================================
# 数据装配
# ================================================================

def _dimension_rows(repo, df: pl.DataFrame) -> list[dict]:
    """把最新 enriched 转成 _dimension_rank 需要的行(dict), 缺 name 时补中文名。

    无行情哨兵行必须剔除: 停牌/无数据的标的在 enriched 里是 close=0、amount=0、
    change_pct=-1.0, 直接聚合会把板块均值算成 -100% 并带出一堆假的"跌停标的",
    让利空榜单完全失真(该哨兵同样是看板 topLosers 的现存问题)。
    """
    cols = [c for c in ("symbol", "name", "change_pct", "amount", "close") if c in df.columns]
    if not cols:
        return []
    rows = [row for row in df.select(cols).to_dicts() if (_finite(row.get("close")) or 0.0) > 0]
    if rows and not rows[0].get("name"):
        symbols = [str(r.get("symbol")) for r in rows if r.get("symbol")]
        try:
            name_map = repo.get_name_map(symbols)
        except Exception as exc:  # 名称只是展示字段, 失败不应中断简报
            logger.debug("板块简报获取标的名称失败: %s", exc)
            name_map = {}
        for row in rows:
            row["name"] = name_map.get(str(row.get("symbol")), row.get("symbol"))
    return rows


def _rank_map(matrix: dict) -> dict[str, tuple[int | None, int]]:
    """{板块: (窗口起点排名, 最新排名)}。

    起点列缺席的板块 prev_rank=None(视作新进榜单), 不凭猜测填充排名。
    """
    dates = matrix.get("dates") or []
    columns = matrix.get("columns") or {}
    if not dates:
        return {}
    latest = columns.get(dates[0]) or []
    oldest = columns.get(dates[-1]) or []
    prev = {str(name): idx + 1 for idx, (name, _pct) in enumerate(oldest)}
    return {str(name): (prev.get(str(name)), idx + 1) for idx, (name, _pct) in enumerate(latest)}


def _heat(avg_pct: float, improvement: float | None, prev_rank: int | None) -> int:
    """热度 0-100: 60% 当日板块涨跌幅 + 40% 窗口内排名改善。

    improvement 已按卡片方向归一(利好=排名上升幅度, 利空=排名下滑幅度);
    排名信息缺失(矩阵冷启动)时取中性 0.5, 不用 0 假装跌出榜单。
    """
    pct_norm = min(1.0, abs(avg_pct) / 0.05)  # 5% 板块均涨幅即满分
    if improvement is None:
        rank_norm = 0.5
    elif prev_rank is None or prev_rank <= 1:
        # 起点排名缺失(新进榜单)或本来就在榜首: 只要有改善方向即给满分
        rank_norm = 1.0 if improvement > 0 else 0.0
    else:
        rank_norm = min(1.0, max(0.0, improvement) / (prev_rank - 1))
    return round(60.0 * pct_norm + 40.0 * rank_norm)


def _signed_pct(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:+.2f}%"


def _logic_stats(item: dict, prev_rank: int | None, cur_rank: int | None, days: int, direction: str) -> str:
    """数据派生文案: 全部数值可追溯到行情, 不用形容词代替事实。"""
    parts = [f"近 {days} 个交易日板块均值 {_signed_pct(_finite(item.get('avg_pct')))}"]
    if prev_rank and cur_rank:
        if cur_rank < prev_rank:
            parts.append(f"排名由第 {prev_rank} 位升至第 {cur_rank} 位")
        elif cur_rank > prev_rank:
            parts.append(f"排名由第 {prev_rank} 位降至第 {cur_rank} 位")
        else:
            parts.append(f"排名稳定在第 {cur_rank} 位")
    elif cur_rank:
        parts.append(f"新进榜单第 {cur_rank} 位")

    count = int(_finite(item.get("count")) or 0)
    up = int(_finite(item.get("up_count")) or 0)
    down = int(_finite(item.get("down_count")) or 0)
    if direction == "bearish":
        parts.append(f"{count} 只成分股中 {down} 只下跌、{up} 只上涨")
    else:
        parts.append(f"{count} 只成分股中 {up} 只上涨、{down} 只下跌")

    amount = _finite(item.get("amount"))
    if amount:
        parts.append(f"合计成交 {amount / 1e8:.1f} 亿")

    # 利空卡的 leader 仍是板块涨幅最高的成分股, 叫「领跌」就是假事实;
    # 利空改看关联标的里跌幅居首的那只(stocks 已按利空方向排序)
    if direction == "bearish":
        stocks = item.get("members") or []
        anchor = min(stocks, key=lambda m: _finite(m.get("change_pct")) or 0.0) if stocks else None
    else:
        anchor = item.get("leader") or None
    anchor_name = (anchor or {}).get("name")
    if anchor_name:
        verb = "领跌" if direction == "bearish" else "领涨"
        parts.append(f"{verb} {anchor_name} {_signed_pct(_finite((anchor or {}).get('change_pct')))}")
    return "，".join(parts)


def _pick_stocks(members: list[dict], direction: str) -> list[dict]:
    """关联标的: 利好取涨幅居前的 3 只, 利空取跌幅居前的 3 只。

    members 已按涨幅降序; 一侧没有符合方向的成分股时退回该侧端点,
    不让卡片出现空标的区。
    """
    picks = list(members)
    if direction == "bearish":
        losers = [m for m in members if (_finite(m.get("change_pct")) or 0.0) < 0]
        picks = list(reversed(losers)) if losers else list(reversed(members[-_STOCK_LIMIT:]))
    else:
        gainers = [m for m in members if (_finite(m.get("change_pct")) or 0.0) > 0]
        picks = gainers if gainers else members
    out = []
    for member in picks[:_STOCK_LIMIT]:
        out.append({
            "symbol": member.get("symbol"),
            "name": member.get("name") or member.get("symbol"),
            "change_pct": _finite(member.get("change_pct")),
        })
    return out


def _window_pct_map(matrix: dict) -> dict[str, float]:
    """窗口累计涨幅: 各交易日复利累乘(0.0618 = 累计 +6.18%)。

    板块在窗口内缺某天的数据时不补 0 —— 用有数据的天数累乘, 不用虚构的交易日。
    """
    cum: dict[str, float] = {}
    for date_key in matrix.get("dates") or []:
        for row in (matrix.get("columns") or {}).get(date_key) or []:
            if len(row) < 2 or row[1] is None:
                continue
            cum[str(row[0])] = cum.get(str(row[0]), 1.0) * (1.0 + float(row[1]))
    return {name: value - 1.0 for name, value in cum.items()}


def _card(
    item: dict,
    ranks: dict[str, tuple[int | None, int]],
    days: int,
    direction: str,
    window_pct: dict[str, float] | None = None,
) -> dict:
    name = str(item.get("name") or "")
    avg_pct = _finite(item.get("avg_pct")) or 0.0
    prev_rank, cur_rank = ranks.get(name, (None, None))
    rank_change = (prev_rank - cur_rank) if (prev_rank and cur_rank) else None

    if rank_change is None:
        improvement = None
    else:
        # 卡片方向上的"改善幅度": 利好=排名上升、利空=排名下滑
        improvement = rank_change if direction == "bullish" else -rank_change

    members = item.get("members") or []
    return {
        "name": name,
        "change_pct": avg_pct,
        "rank": cur_rank,
        "prev_rank": prev_rank,
        "rank_change": rank_change,
        "heat": _heat(avg_pct, improvement, prev_rank),
        "count": int(_finite(item.get("count")) or 0),
        "up_count": int(_finite(item.get("up_count")) or 0),
        "down_count": int(_finite(item.get("down_count")) or 0),
        "amount": _finite(item.get("amount")) or 0.0,
        "leader": item.get("leader"),
        "stocks": _pick_stocks(members, direction),
        "window_pct": (window_pct or {}).get(name),
        "logic_stats": _logic_stats(item, prev_rank, cur_rank, days, direction),
        # 驱动归因与关联快讯由 _attach_drivers 按最新行情/快讯挂上
        "headline": None,
        "drivers": [],
        "flash": [],
        "ai_logic": None,
    }


def _empty_brief(kind: str, latest, days: int, member_count: int = 0) -> dict:
    return {
        "as_of": latest.isoformat() if latest else None,
        "kind": kind,
        "member_count": member_count,
        "days": days,
        "bullish": [],
        "bearish": [],
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "ai_status": "missing",
        "ai_generated_at": None,
        "ai_configured": False,
    }


def _matrix_for(repo, kind: str, days: int) -> dict:
    """板块轮动矩阵(行业统一二级口径, 与看板/复盘一致)。

    rps_rotation 自带 120s 缓存, 这里的第二次调用不会重复读 parquet。
    """
    return build_rps_rotation(repo, days=days, kind=kind, level=(2 if kind == "industry" else None))


def _build_data_brief(repo, kind: str, top_n: int, days: int) -> dict:
    """纯行情数据部分(进程内 60s 缓存)。不含 AI 文案, 由上层按缓存合并。"""
    cache_key = f"{kind}|{top_n}|{days}"

    df, latest = repo.get_enriched_latest()
    if df is None or df.is_empty() or latest is None:
        # 无行情就没有可报告的交易日: as_of 留空, 不拿一个没有数据的日期冒充
        logger.info("板块简报: enriched 最新数据为空, 返回空结构")
        return _empty_brief(kind, None, days)

    cache_key = f"{cache_key}|{latest.isoformat()}"
    now = time.time()
    with _CACHE_LOCK:
        cached = _cache.get(cache_key)
        if cached is not None and (now - _cache_ts.get(cache_key, 0.0)) < _CACHE_TTL:
            return cached

    rows = _dimension_rows(repo, df)
    # 行业按二级聚合, 与看板/复盘(level=2)保持同一口径
    level = 2 if kind == "industry" else None
    rank = _dimension_rank(rows, repo, kind, limit=top_n, level=level, with_members=True)
    matrix = build_rps_rotation(repo, days=days, kind=kind, level=level)
    ranks = _rank_map(matrix)
    window = _window_pct_map(matrix)

    bullish = [
        _card(item, ranks, days, "bullish", window)
        for item in rank.get("leading", [])
        if int(_finite(item.get("count")) or 0) >= _MIN_MEMBERS
    ]
    bearish = [
        _card(item, ranks, days, "bearish", window)
        for item in rank.get("lagging", [])
        if int(_finite(item.get("count")) or 0) >= _MIN_MEMBERS
    ]

    brief = {
        "as_of": latest.isoformat(),
        "kind": kind,
        "member_count": int(matrix.get("concept_count") or 0),
        "days": days,
        "bullish": bullish,
        "bearish": bearish,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "ai_status": "missing",
        "ai_generated_at": None,
        "ai_configured": False,
    }
    with _CACHE_LOCK:
        _cache[cache_key] = brief
        _cache_ts[cache_key] = now
    return brief


# ================================================================
# 驱动归因与关联快讯(数据路径)
# ================================================================

def _attach_drivers(
    brief: dict,
    repo,
    kind: str,
    days: int,
    news_service=None,
) -> tuple[dict, list[dict]]:
    """给每张卡挂上四维归因与关联快讯, 并返回本次使用的快讯池(供 AI 引用编号)。

    快讯/外围任一来源不可用时, 对应维度直接不出现——卡片宁可少一个维度,
    也不编一个维度。任一环节异常都不能拖垮解读行情的那部分。
    """
    pool: list[dict] = []
    if news_service is not None:
        try:
            pool = news_service.fetch_news_pool() or []
        except Exception as exc:  # 快讯源全挂时仍有盘面/外围可用
            logger.warning("板块简报获取快讯池失败: %s", exc)

    try:
        overseas = overseas_snapshot(Path(repo.store.data_dir))
    except Exception as exc:
        logger.warning("板块简报获取外围指数快照失败: %s", exc)
        overseas = []

    matrix = _matrix_for(repo, kind, days)
    merged = dict(brief)
    for side in ("bullish", "bearish"):
        cards = []
        for card in brief.get(side) or []:
            member_names = [s.get("name") for s in card.get("stocks") or []]
            driver = build_drivers(
                card,
                pool=pool,
                matrix=matrix,
                days=days,
                direction=side,
                overseas=overseas,
                member_names=member_names,
                as_of=brief.get("as_of"),
            )
            cards.append({**card, **driver})
        merged[side] = cards
    return merged, pool


# ================================================================
# AI 文案(批量一次调用 + 按自然日落盘缓存)
# ================================================================

def _ai_file(data_dir: Path) -> Path:
    return Path(data_dir) / "user_data" / _AI_FILE_NAME


def _read_ai_store(data_dir: Path) -> dict:
    path = _ai_file(data_dir)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception as exc:  # 缓存损坏时重新生成, 不影响 GET
        logger.warning("板块简报 AI 缓存解析失败: %s", exc)
        return {}


def _write_ai_store(data_dir: Path, store: dict) -> None:
    path = _ai_file(data_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:  # 落盘失败只影响下次复用, 不阻断本次返回
        logger.warning("板块简报 AI 缓存写入失败: %s", exc)


def _ai_key(latest: str | None, kind: str) -> str:
    return f"{latest or 'unknown'}|{kind}|{_AI_SCHEMA}"


def _merge_narratives(brief: dict, entry: dict | None, ai_configured: bool, ai_status: str | None = None) -> dict:
    """把 AI 文案合并进卡片。ai_status 缺省按「有缓存/无缓存」推断。"""
    merged = {**brief, "ai_configured": ai_configured}
    if not entry:
        return {**merged, "ai_status": ai_status or "missing", "ai_generated_at": None}
    narratives = entry.get("sectors") or {}
    for key in ("bullish", "bearish"):
        cards = []
        for card in brief.get(key, []):
            cards.append(_apply_ai(card, narratives.get(card["name"])))
        merged[key] = cards
    return {
        **merged,
        "ai_status": ai_status or "cached",
        "ai_generated_at": entry.get("generated_at"),
    }


def _apply_ai(card: dict, narrative: dict | None) -> dict:
    """把单个板块的 AI 输出合到卡片上。

    逐字段降级: 只有合法字段才覆盖数据派生值 —— AI 只给了 logic 时,
    headline/drivers/flash 继续用数据路径的结果, 不把已算好的东西抹掉。
    """
    if not isinstance(narrative, dict):
        return card
    out = {**card, "ai_logic": narrative.get("logic") or None}
    headline = str(narrative.get("headline") or "").strip()
    if headline:
        out["headline"] = headline[:120]
    drivers = parse_ai_drivers(narrative.get("drivers"))
    if drivers:
        out["drivers"] = drivers
    flash = narrative.get("flash")
    if isinstance(flash, list) and flash:
        out["flash"] = flash
    return out


def _ai_configured() -> bool:
    try:
        from app.services.ai_provider import ai_configured

        return bool(ai_configured())
    except Exception as exc:  # 检测失败按未配置处理, 由前端提示
        logger.debug("板块简报检测 AI 配置失败: %s", exc)
        return False


def build_sector_brief(
    repo,
    kind: str = "concept",
    top_n: int = 5,
    days: int = _DEFAULT_DAYS,
    news_service=None,
) -> dict:
    """读取板块简报(GET 路径): 行情 + 驱动归因 + 已缓存的 AI 文案, 不触发 LLM 调用。

    news_service 缺省为 None → 快讯池为空, 只出盘面/外围两个维度(测试与离线场景用),
    不在这儿自行新建 NewsService, 避免读取路径意外打上游。
    """
    kind = "industry" if kind == "industry" else "concept"
    top_n = max(3, min(10, int(top_n)))
    # rps 矩阵自身把窗口夹在 [7, 30] 个交易日, 这里保持同一区间
    days = max(7, min(30, int(days)))

    brief = _build_data_brief(repo, kind, top_n, days)
    brief, _pool = _attach_drivers(brief, repo, kind, days, news_service)
    data_dir = Path(repo.store.data_dir)
    store = _read_ai_store(data_dir)
    entry = store.get(_ai_key(brief.get("as_of"), kind))
    # 出口统一收干净: 非有限数 / numpy 标量进了结果就整条 500(且会被缓存固定住)
    return _jsonable(_merge_narratives(brief, entry, _ai_configured()))


_SYSTEM_PROMPT = """你是一位专注 A 股题材轮动的研究分析师。读者已经看过行情数据，需要你解释这些板块为什么动。

## 归因维度（固定四个，不得新增、改名或调换 key）
- news（消息面）：公司或产业的真实事件——量产、订单、中标、涨价、扩产、公告
- policy（政策产业）：政策文件、部委规划、产业基金、试点、补贴、标准
- market（盘面题材）：资金与行情本身——板块涨幅、排名变化、成交额、领涨股、关联题材联动
- overseas（外围指数）：隔夜美股/港股、大宗商品与汇率的方向

## 红线（务必遵守）
- **只能引用我给你的快讯清单里的事件**，并用编号在 flash_ids 里引用。清单里没有的公司、数字、文件名称一个字都不能编。
- **绝对不输出**任何买卖、加减仓、跟踪、规避、追高、低吸、观望等交易指令或倾向性措辞。
- 不编造股票名称或代码，只能引用我提供的数据。
- 某个维度没有证据就**不要输出该维度**——宁可只给两个维度，也不编一个维度凑满四个。
- 利空板块不要写「领涨」：要看跌幅居前的成分股与相对弱势，不能把上涨说成利好。

## 输出规范
只输出一个 JSON 数组，不要 markdown 代码块、不要解释文字。数组每项对应我给你的每个板块，顺序保持一致：
[{
  "name": "板块名（必须与我给的完全一致）",
  "headline": "一句话驱动摘要，40 字内，说清主要驱动与方向",
  "logic": "2~3 句驱动逻辑，60~120 字",
  "drivers": [{"key": "news", "weight": 40, "text": "该维度的一句话证据（60 字内）"}],
  "flash_ids": [3, 7]
}]
- drivers 的 weight 是整数百分比，同一板块各维度合计尽量为 100；text 只能复述快讯清单或行情数据里的事实，不要写编号。
- flash_ids 只能填清单里出现过的编号，最多 4 个，且必须与这个板块真正相关；不确定就留空数组。
- logic 写法：第一句说数据事实（涨幅/排名/涨跌家数），第二句说驱动，第三句（可选）说分歧或持续性。数据不支持时直说"信号不足"。
- 不要在回复里写推理过程或任何解释，直接输出最终 JSON 数组。"""


def _build_user_message(
    brief: dict,
    days: int,
    pool: list[dict] | None = None,
    sides: tuple[str, ...] = ("bullish", "bearish"),
) -> str:
    lines = [f"以下是最新交易日 {brief.get('as_of')} 的板块数据（涨幅为小数制，0.0431 = +4.31%，窗口 {days} 个交易日）：", ""]
    labels = {"bullish": "利好板块（涨幅领先）", "bearish": "利空板块（跌幅领先）"}
    for side in sides:
        lines.append(f"### {labels.get(side, side)}")
        for card in brief.get(side, []):
            # 利空卡片给「跌幅居前的成分股」而不是板块涨幅最高的那只:
            # 否则模型会在一张利空卡上写出「领涨 苏垦农发 +2.80%」这种自相矛盾的句子
            anchor = _anchor_stock(card, side) or {}
            anchor_label = "跌幅居前" if side == "bearish" else "领涨股"
            lines.append(
                f"- {card['name']}：当日均值 {_signed_pct(card.get('change_pct'))}，"
                f"当天排名 {card.get('rank') or '—'}（窗口起点 {card.get('prev_rank') or '—'}），"
                f"近 {days} 日累计 {_signed_pct(card.get('window_pct'))}，"
                f"{card.get('count')} 只成分股（{card.get('up_count')} 涨 / {card.get('down_count')} 跌），"
                f"成交 {(card.get('amount') or 0) / 1e8:.1f} 亿，"
                f"{anchor_label}：{anchor.get('name') or '—'} "
                f"{_signed_pct(anchor.get('change_pct'))}，"
                f"数据派生归因：{format_driver_brief(card.get('drivers') or [])}"
            )
        lines.append("")

    pool = pool or []
    if pool:
        lines.append("### 快讯清单（flash_ids 只能引用这里的编号）")
        lines.append(pool_for_prompt(pool, limit=_AI_POOL_LIMIT))
    else:
        lines.append("### 快讯清单\n（本次无可用快讯：不要输出 news / policy 维度，flash_ids 留空）")
    return "\n".join(lines)


def _parse_narratives(raw: str) -> dict[str, dict]:
    """从 AI 回复里解析 {板块名: {headline, logic, drivers, flash_ids}}。容忍 markdown 代码块包裹。

    logic 为空即丢弃该项(与 v1 一致): 没有正文的板块不值得占位。
    drivers 在这里只做语法级清洗, 语义校验与权重归一化交给 sector_drivers.parse_ai_drivers。
    """
    if not raw:
        return {}
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        logger.warning("板块简报未在 AI 返回中找到 JSON 数组 | raw[:300]=%s", raw[:300])
        return {}
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        # 原始返回截断入日志: 解析失败时不给证据就无法定位是模型跑偏还是链路问题
        logger.warning("板块简报解析 AI 返回失败: %s | raw[:300]=%s", exc, raw[:300])
        return {}
    if not isinstance(parsed, list):
        return {}
    out: dict[str, dict] = {}
    for item in parsed:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        logic = str(item.get("logic") or "").strip()
        if not name or not logic:
            continue
        drivers = item.get("drivers")
        flash_ids = item.get("flash_ids")
        out[name] = {
            "headline": str(item.get("headline") or "").strip(),
            "logic": logic,
            "drivers": drivers if isinstance(drivers, list) else [],
            "flash_ids": flash_ids if isinstance(flash_ids, list) else [],
        }
    return out


async def narrate_sector_brief(
    repo,
    kind: str = "concept",
    top_n: int = 5,
    days: int = _DEFAULT_DAYS,
    news_service=None,
) -> dict:
    """生成(或复用)当日 AI 驱动归因文案。

    同一交易日已生成过就直接复用缓存, 不重复消耗 token;
    模型选中的快讯编号在此时就回池解析成真实条目(时间/标题/链接)写入缓存,
    后续 GET 直接读落盘结果, 不依赖当时的内存池 —— 池子变了也不会张冠李戴。
    AI 不可用 / 调用失败 / 返回无法解析 → 抛 SectorBriefAIError(API 转 502)。
    """
    kind = "industry" if kind == "industry" else "concept"
    top_n = max(3, min(10, int(top_n)))
    days = max(7, min(30, int(days)))

    data_dir = Path(repo.store.data_dir)
    brief = _build_data_brief(repo, kind, top_n, days)
    latest = brief.get("as_of")
    if not latest or not (brief.get("bullish") or brief.get("bearish")):
        # 没有可解读的板块: 不是错误, 也没有调用 AI 的意义
        logger.info("板块简报 AI 文案跳过: 无板块数据")
        return _jsonable(_merge_narratives(brief, None, _ai_configured(), ai_status="unavailable"))

    brief, pool = _attach_drivers(brief, repo, kind, days, news_service)
    # 喂给模型的快讯清单: 每边各自按相关度取(引用编号与该边的清单一一对应)
    ai_pools = {
        side: select_pool_for_ai(pool, brief.get(side) or [], limit=_AI_POOL_LIMIT)
        for side in _AI_SIDES
    }
    store = _read_ai_store(data_dir)
    cached = store.get(_ai_key(latest, kind))
    if cached:
        return _jsonable(_merge_narratives(brief, cached, True, ai_status="cached"))

    from app.services.ai_provider import ai_configured, generate_ai_text

    if not ai_configured():
        raise SectorBriefAIError("未配置 AI 模型，无法生成板块研判文案")

    # 逐边请求: 单边失败不影响另一边(另一边正常写入, 失败的板块继续用数据派生归因)
    narratives: dict[str, dict] = {}
    empty_side = False
    fail_reason: str | None = None
    for side in _AI_SIDES:
        if not brief.get(side):
            continue
        side_pool = ai_pools.get(side) or []
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _build_user_message(brief, days, side_pool, (side,)),
            },
        ]
        try:
            raw = await generate_ai_text(
                messages,
                temperature=0.3,
                max_tokens=_AI_MAX_TOKENS,
                timeout=_AI_TIMEOUT,
            )
        except Exception as exc:  # 单边失败不阻断另一边
            fail_reason = str(exc)
            logger.warning("板块简报 AI %s 边调用失败: %s", side, exc)
            continue
        if not raw.strip():
            empty_side = True
            logger.warning("板块简报 AI %s 边返回空内容（可能推理耗尽输出预算）", side)
            continue
        parsed = _parse_narratives(raw)
        if not parsed:
            fail_reason = "AI 返回内容无法解析为板块文案"
            logger.warning("板块简报 AI %s 边返回无法解析 | raw[:300]=%s", side, raw[:300])
            continue
        # 回池解析 flash_ids: 越界/非整数一律丢弃, 模型给的标题与链接概不采信
        for name, item in parsed.items():
            if name in narratives:
                continue
            narratives[name] = {**item, "flash": flash_from_ids(side_pool, item["flash_ids"])}

    if not narratives:
        if empty_side:
            raise SectorBriefAIError(
                "AI 只返回了推理内容、没有产出正文（模型可能在推理上耗尽了输出预算，"
                "可换用非推理模型或稍后重试）"
            )
        raise SectorBriefAIError(fail_reason or "AI 板块研判生成失败")
    entry = {
        "kind": kind,
        "as_of": latest,
        "status": "generated",
        "schema": _AI_SCHEMA,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "sectors": narratives,
    }
    store[_ai_key(latest, kind)] = entry
    _write_ai_store(data_dir, store)
    logger.info(
        "板块简报 AI 文案已生成: %s 个板块, 快讯池 %s 条(每边喂入 %s 条)",
        len(narratives),
        len(pool),
        _AI_POOL_LIMIT,
    )
    return _jsonable(_merge_narratives(brief, entry, True, ai_status="generated"))
