# -*- coding: utf-8 -*-
"""板块驱动归因 —— 把「为什么这个板块动」拆成 消息面 / 政策产业 / 盘面题材 / 外围指数。

设计约束(与 CONTRIBUTING 的数据契约一致):
  - **只用真实数据**: 快讯来自 NewsService 的多源合并池(带标题/时间/链接), 外围来自本地
    美股/港股指数 parquet, 盘面来自 rps_rotation 的当日列。某个维度没有证据就不出现,
    不用占位文案凑满四个格子 —— 卡片宁可只有 2 个维度, 也不编一个维度。
  - **不做伪归因**: 消息面/政策产业的文本只允许是「真实快讯标题」(数据路径) 或
    「AI 在给定快讯池内选中的条目」(AI 路径的 flash_ids), 不允许凭空生成新闻标题。
    外部传入的 flash_ids 一律回池校验, 越界/类型不对的直接丢弃。
  - **权重可解释**: 是各维度原始证据强度归一化后的份额(最大余额法取整, 合计恰好 100),
    不是拍出来的数字。AI 给的权重同样过校验与归一化, 全为 0 时退回数据派生权重。

输出契约(板块简报卡片的驱动字段, 由 sector_brief 挂到每张卡上):
  headline: str | None                     一句话驱动摘要
  drivers:  [{key,label,weight,text}]      key ∈ news/policy/market/overseas, weight 合计 100
  flash:    [{id,time,title,url,source,direction,category}]  该板块的关联快讯(最多 4 条)
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 维度定义: key → 中文标签。顺序即卡片上的展示顺序。
DRIVER_LABELS: dict[str, str] = {
    "news": "消息面",
    "policy": "政策产业",
    "market": "盘面题材",
    "overseas": "外围指数",
}
DRIVER_ORDER: tuple[str, ...] = ("news", "policy", "market", "overseas")

# 政策/产业口径词: 命中即归到「政策产业」而不是「公司消息面」
POLICY_WORDS: tuple[str, ...] = (
    "政策", "规划", "国务院", "发改委", "工信部", "财政部", "央行", "证监会", "国资委",
    "试点", "补贴", "专项资金", "产业基金", "基金", "条例", "管理办法", "征求意见", "标准",
    "十五五", "重大专项", "部署", "印发", "实施方案", "税收优惠", "部委", "省级", "市政府",
    "监管", "通知", "会议", "行动方案", "目录",
)

# 板块名里的通用后缀: 生成检索词时先剥掉, 否则「概念」两个字会在任何快讯里命中
_GENERIC_SUFFIXES: tuple[str, ...] = ("概念", "板块", "行业", "指数", "主题", "产业链")
# 单独出现即不能算相关的通用词: 「设备」这种词能把任何采购新闻拉进半导体设备
_GENERIC_TOKENS: frozenset[str] = frozenset(
    {"设备", "行业", "公司", "市场", "相关", "龙头", "概念", "板块", "指数", "主题", "产业链"}
)
_FLASH_LIMIT = 4
# 命中判定阈值: 板块名 6 / 主干 5 / 三字词 4 / 二字片段 2 / 成分股名义题 6、正文 4。
# 阈值 4 → 标题必须出现板块主干或三字以上片段(二字片段单独出现不够)。
# 实测过不设限时「南非赛车冠军遭枪杀」会被拉进「汽车芯片」、德国大选新闻会被拉进
# 「国家大基金持股」——旧口径把正文也当证据, 二字片段也算独立命中。
_MATCH_THRESHOLD = 4
# 正文只用于识别成分股名(新闻正文提到个股才是真催化); 板块词只看标题, 不看正文
_CONTENT_SCAN_CHARS = 120
# 单个板块当日均值超过该幅度基本是停牌哨兵污染, 不能当「同类联动」展示
_PEER_MAX_MOVE = 0.15


def is_policy_text(text: str) -> bool:
    """是否属于政策/产业类快讯(与公司消息面区分)。"""
    return any(word in text for word in POLICY_WORDS)


def sector_tokens(name: str) -> list[str]:
    """板块名的检索词: 全名 + 去掉通用后缀的主干 + 主干里的 2/3 字 n-gram。

    长词优先, 便于调用方按命中长度给分。
    """
    base = str(name or "").strip()
    if not base:
        return []
    for suffix in _GENERIC_SUFFIXES:
        if len(base) > len(suffix) and base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    tokens: set[str] = {str(name).strip()} if len(str(name).strip()) >= 2 else set()
    for size in (3, 2):
        if len(base) >= size:
            for start in range(len(base) - size + 1):
                tokens.add(base[start : start + size])
    if len(base) >= 2:
        tokens.add(base)
    return sorted(
        (t for t in tokens if t not in _GENERIC_TOKENS or t == str(name).strip()),
        key=len,
        reverse=True,
    )


def _match_score(
    title: str,
    full_name: str,
    base: str,
    tokens: list[str],
    member_names: list[str],
    content: str = "",
) -> tuple[int, list[str]]:
    """快讯与板块的相关度: 板块名 > 主干 > 三字/首尾词 > 内部二字词; 成分股名单独加权。

    板块词只扫标题 —— 正文顺带提到「芯片」的宏观言论不是这个板块的催化;
    成分股名在正文里出现仍然算数(正文写公司才是真公告)。
    返回 (分数, 命中词), 命中词用于日志与测试排查误匹配。
    """
    score = 0
    hits: list[str] = []
    if title:
        if full_name and full_name in title:
            score += 6
            hits.append(full_name)
        for token in tokens:
            if token == full_name or token not in title:
                continue
            if token == base:
                score += 5
            elif len(token) >= 3:
                # 三字词(如「半导体」于「半导体设备」)单独出现即算命中
                score += 4
            else:
                # 二字片段只能当佐证: 「国家」于「国家大基金持股」、「商业」于「商业航天」
                # 单独命中就是噪声(实测能把德国大选新闻拉进大基金持股板块)
                score += 2
            hits.append(token)
    for member in member_names:
        if not member:
            continue
        if member in title:
            score += 6
            hits.append(member)
        elif content and member in content[:_CONTENT_SCAN_CHARS]:
            score += 4
            hits.append(f"{member}(正文)")
    return score, hits


def _news_text(item: dict) -> str:
    return f"{item.get('title') or ''} {str(item.get('content') or '')[:180]}"


def _news_title_text(item: dict) -> str:
    return str(item.get("title") or "")


def match_news_scored(
    items: list[dict],
    sector_name: str,
    member_names: list[str],
    *,
    limit: int = _FLASH_LIMIT,
) -> list[dict]:
    """按相关度挑出与板块相关的快讯(相关度优先, 同分取更新的)。"""
    full_name = str(sector_name or "").strip()
    tokens = sector_tokens(sector_name)
    base = tokens[0] if tokens else full_name
    for suffix in _GENERIC_SUFFIXES:
        if len(base) > len(suffix) and base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    members = [str(m) for m in member_names if m]
    scored: list[tuple[int, str, dict, list[str]]] = []
    for item in items or []:
        score, hits = _match_score(
            _news_title_text(item),
            full_name,
            base,
            tokens,
            members,
            str(item.get("content") or ""),
        )
        if score < _MATCH_THRESHOLD:
            continue
        scored.append((score, str(item.get("time") or ""), item, hits))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    from app.services.flash_classifier import classify_direction

    out: list[dict] = []
    for score, _time, item, hits in scored[:limit]:
        text = _news_text(item)
        out.append({
            "id": item.get("id"),
            "time": item.get("time"),
            "title": item.get("title"),
            "url": item.get("url") or "",
            "source": item.get("source") or "",
            "direction": classify_direction(text),
            "category": "policy" if is_policy_text(text) else "news",
            "_score": score,
            "_hits": hits,
        })
    return out


_OVERSEAS_MAX_AGE_DAYS = 3


def _date_text(value: Any) -> str:
    text = str(value or "").strip()
    return text[:10] if len(text) >= 10 else text


def _parse_day(value: Any):
    from datetime import date

    text = _date_text(value)
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def overseas_snapshot(data_dir) -> list[dict]:
    """外围指数快照(本地美股/港股指数 parquet), 带各自的数据日期。

    单位统一成小数制: index_sync_market.get_market_index_quotes 返回的是**百分数**
    (2.89 表示 +2.89%, -0.43 表示 -0.43%), 这里一律 /100, 不靠绝对值猜单位
    —— 否则 -0.43% 会被当成 -43% 展示出去。
    没同步过指数数据时返回空列表: 调用方据此不展示「外围指数」维度, 而不是显示 0%。
    """
    from app.services.index_sync_market import get_market_index_quotes

    out: list[dict] = []
    for market, label in (("us", "美股"), ("hk", "港股")):
        try:
            quotes = get_market_index_quotes(market, data_dir)
        except Exception as exc:  # 单个市场读失败不影响另一个
            logger.debug("外围指数 %s 快照失败: %s", market, exc)
            continue
        for quote in quotes or []:
            pct = quote.get("change_pct")
            day = _date_text(quote.get("date"))
            if pct is None or not day:
                continue
            if not (_finite_price(quote.get("last_price")) > 0):
                continue  # 无收盘价的哨兵行不参与
            out.append({
                "market": market,
                "market_label": label,
                "name": quote.get("name") or quote.get("symbol"),
                "change_pct": float(pct) / 100.0,
                "date": day,
            })
    return out


def _finite_price(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _pct_text(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value * 100:+.2f}%"


def _anchor_stock(card: dict, direction: str) -> dict | None:
    """卡片方向的代表性个股: 利好取领涨股, 利空取跌幅最大的成分股。

    利空卡片的 leader 字段仍是板块涨幅最高的成分股, 直接叫「领跌」会把一只上涨的
    股票写成领跌(实测过), 所以利空改看关联标的里跌幅居首的那只。
    """
    if direction == "bearish":
        stocks = card.get("stocks") or []
        return stocks[0] if stocks else None
    anchor = card.get("leader") or None
    return anchor if (anchor or {}).get("name") else None


def _peers(latest_col: list, name: str, direction: str, limit: int = 2) -> list[tuple[str, float]]:
    """当日同档板块: 利好取涨幅最高者, 利空取紧跟其后的 2 个。

    利空不用绝对最差的那几个 —— 板块均值被停牌哨兵(-100% 成分股)污染后会出现
    假跌停板块(实测「网约车 -6.11%」), 同档邻居才是可信的同期弱势。
    """
    ordered = [
        (str(row[0]), float(row[1]))
        for row in latest_col
        if len(row) >= 2 and row[1] is not None and abs(float(row[1])) <= _PEER_MAX_MOVE
    ]
    names = [row[0] for row in ordered]
    if direction == "bearish" and name in names:
        candidates = ordered[names.index(name) + 1 : names.index(name) + 1 + limit]
    else:
        candidates = sorted(
            (row for row in ordered if row[0] != name), key=lambda row: row[1], reverse=True
        )[:limit]
    return candidates


def market_text(card: dict, matrix: dict, days: int, direction: str) -> tuple[str, float] | None:
    """盘面题材维度: 板块自身涨幅/领涨股 + 当日涨幅榜前列 + 窗口累计。

    返回 (文案, 原始强度分); 行情缺失(无矩阵列)时返回 None。
    """
    name = str(card.get("name") or "")
    latest_col = (matrix.get("columns") or {}).get((matrix.get("dates") or [None])[0]) or []
    if not latest_col and card.get("change_pct") is None:
        return None

    verb = "领跌" if direction == "bearish" else "领涨"
    lead_order = "居前" if direction == "bullish" else "同档偏弱"
    peers = _peers(latest_col, name, direction)

    parts = [f"当日板块均值 {_pct_text(card.get('change_pct'))}"]
    anchor = _anchor_stock(card, direction) or {}
    if anchor.get("name"):
        parts.append(f"{anchor['name']} {_pct_text(anchor.get('change_pct'))} {verb}")
    if peers:
        label = f"当日涨幅{lead_order}" if direction == "bullish" else f"同档偏弱（{lead_order}）"
        parts.append(f"{label} {peers[0][0]} {_pct_text(peers[0][1])}")
        if len(peers) > 1:
            parts.append(f"{peers[1][0]} {_pct_text(peers[1][1])}")
    if card.get("window_pct") is not None:
        parts.append(f"近 {days} 日累计 {_pct_text(card.get('window_pct'))}")

    avg_pct = abs(float(card.get("change_pct") or 0.0))
    raw = min(5.0, max(1.0, avg_pct / 0.01))  # 1% 板块均涨幅 ≈ 1 分, 5 分封顶
    window_pct = card.get("window_pct")
    if window_pct is not None and (window_pct > 0) == (avg_pct > 0):
        raw += 0.5  # 当日与窗口同向 → 趋势延续性更强
    return "，".join(parts), min(5.5, raw)


def overseas_text(snapshot: list[dict], direction: str, as_of: Any = None) -> tuple[str, float] | None:
    """外围指数维度: 只采信与简报数据日同期(≤3 天)的指数, 否则不出现。

    本地指数 parquet 可能很久没同步(实测有滞后一个月的港股指数)。
    拿月前的数据当「隔夜」是假消息面, 所以过期数据直接不要; 与板块方向一致/背离如实标注。
    """
    if not snapshot:
        return None
    reference = _parse_day(as_of)
    if reference is None:
        from datetime import date as _date

        reference = _date.today()
    fresh: list[dict] = []
    for quote in snapshot:
        day = _parse_day(quote.get("date"))
        if day is None:
            continue
        age = (reference - day).days
        if 0 <= age <= _OVERSEAS_MAX_AGE_DAYS:
            fresh.append(quote)
    if not fresh:
        return None

    us = [q for q in fresh if q["market"] == "us"]
    hk = [q for q in fresh if q["market"] == "hk"]
    picks = ([q for q in us if q["name"] in ("纳斯达克", "纳斯达克100")] or us)[:1]
    picks += ([q for q in hk if q["name"] == "恒生科技指数"] or hk)[:1]
    if not picks:
        return None

    age = (reference - _parse_day(picks[0]["date"])).days
    prefix = "隔夜" if age <= 2 else f"{_date_text(picks[0]['date'])[5:]} 收盘"
    text = f"{prefix} " + "、".join(f"{q['name']} {_pct_text(q['change_pct'])}" for q in picks)
    anchor = picks[0]["change_pct"]
    aligned = anchor > 0 if direction == "bullish" else anchor < 0
    text += "，外围风险偏好与板块方向一致" if aligned and anchor != 0 else "，外围与板块方向不一致或持平"
    # 有数据即给基础分; 方向一致再加分(风险偏好共振)
    return text, 3.0 if aligned and anchor != 0 else 1.5


def _weights(raw: dict[str, float]) -> dict[str, int]:
    """证据强度 → 整数权重(最大余额法, 合计恰好 100)。"""
    positive = {key: value for key, value in raw.items() if value and value > 0}
    total = sum(positive.values())
    if total <= 0:
        return {}
    exact = {key: value / total * 100 for key, value in positive.items()}
    floors = {key: int(value) for key, value in exact.items()}
    remainder = 100 - sum(floors.values())
    for key in sorted(exact, key=lambda k: exact[k] - floors[k], reverse=True)[:remainder]:
        floors[key] += 1
    return floors


def _news_driver_text(items: list[dict], limit: int = 2) -> str:
    """数据路径的消息面文案: 直接引用真实快讯(来源 + 时间), 不做二次创作。"""
    parts: list[str] = []
    for item in items[:limit]:
        stamp = str(item.get("time") or "")
        clock = stamp[5:16] if len(stamp) >= 16 else stamp
        source = item.get("source") or ""
        prefix = f"{source} {clock}：" if source or clock else ""
        parts.append(f"{prefix}{str(item.get('title') or '').strip()}")
    return "；".join(parts)


def build_drivers(
    card: dict,
    *,
    pool: list[dict] | None,
    matrix: dict,
    days: int,
    direction: str,
    overseas: list[dict] | None = None,
    member_names: list[str] | None = None,
    as_of: str | None = None,
) -> dict:
    """数据派生的驱动分解: {headline, drivers, flash}。

    这是 AI 不可用时的降级路径, 也是 AI 路径的底座(未覆盖的板块直接用它)。
    """
    matched = match_news_scored(pool or [], card.get("name") or "", member_names or [], limit=8)
    news_items = [item for item in matched if item["category"] == "news"]
    policy_items = [item for item in matched if item["category"] == "policy"]

    raw: dict[str, float] = {}
    texts: dict[str, str] = {}
    if news_items:
        raw["news"] = 2.0 * min(len(news_items), 3)
        texts["news"] = _news_driver_text(news_items)
    if policy_items:
        raw["policy"] = 2.0 * min(len(policy_items), 2)
        texts["policy"] = _news_driver_text(policy_items)
    market = market_text(card, matrix, days, direction)
    if market:
        raw["market"], texts["market"] = market[1], market[0]
    overseas_driver = overseas_text(overseas or [], direction, as_of)
    if overseas_driver:
        raw["overseas"], texts["overseas"] = overseas_driver[1], overseas_driver[0]

    weights = _weights(raw)
    drivers = [
        {"key": key, "label": DRIVER_LABELS[key], "weight": weights[key], "text": texts[key]}
        for key in DRIVER_ORDER
        if weights.get(key)
    ]

    flash = [
        {key: item[key] for key in ("id", "time", "title", "url", "source", "direction", "category")}
        for item in matched[:_FLASH_LIMIT]
    ]
    if matched:
        logger.debug(
            "板块 %s 关联快讯: %s",
            card.get("name"),
            [(item["title"][:24], item["_hits"]) for item in matched],
        )
    return {"headline": data_headline(card, matched, direction), "drivers": drivers, "flash": flash}


def data_headline(card: dict, matched: list[dict], direction: str) -> str:
    """数据路径标题: 有消息就引用消息, 没有就陈述行情事实, 不编因果。"""
    name = str(card.get("name") or "")
    trend = "利好" if direction == "bullish" else "利空"
    if matched:
        top = matched[0]
        title = str(top.get("title") or "").strip().rstrip("。")
        source_label = "政策面" if top.get("category") == "policy" else "消息面"
        return f"{title}，{source_label}{trend}{name}"
    anchor = _anchor_stock(card, direction) or {}
    if anchor.get("name"):
        verb = "领跌" if direction == "bearish" else "领涨"
        return f"{name} 当日板块均值 {_pct_text(card.get('change_pct'))}，{anchor['name']} {_pct_text(anchor.get('change_pct'))} {verb}"
    return f"{name} 当日板块均值 {_pct_text(card.get('change_pct'))}，暂无明确消息面催化"


def flash_from_ids(pool: list[dict], ids: list[Any], *, limit: int = _FLASH_LIMIT) -> list[dict]:
    """把 AI 选中的快讯序号回池校验(越界/非整数一律丢弃, 不信任模型给的任何内容)。"""
    from app.services.flash_classifier import classify_direction

    out: list[dict] = []
    seen: set[int] = set()
    for raw in ids or []:
        try:
            index = int(raw)
        except (TypeError, ValueError):
            continue
        if index in seen or not 0 <= index < len(pool):
            continue
        seen.add(index)
        item = pool[index]
        text = _news_text(item)
        out.append({
            "id": item.get("id"),
            "time": item.get("time"),
            "title": item.get("title"),
            "url": item.get("url") or "",
            "source": item.get("source") or "",
            "direction": classify_direction(text),
            "category": "policy" if is_policy_text(text) else "news",
        })
        if len(out) >= limit:
            break
    return out


def parse_ai_drivers(raw: Any) -> list[dict]:
    """校验 AI 返回的驱动分解: key 合法 + 权重 0-100 的整数 + 文案非空。

    返回归一化后的 drivers(合计 100); 权重全为 0 或结构非法时返回 [], 由调用方退回数据派生权重。
    """
    if not isinstance(raw, list):
        return []
    collected: dict[str, dict] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if key not in DRIVER_LABELS or key in collected:
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        try:
            weight = round(float(item.get("weight") or 0))
        except (TypeError, ValueError):
            weight = 0
        collected[key] = {"key": key, "label": DRIVER_LABELS[key], "weight": max(0, min(100, weight)), "text": text[:200]}
    if not collected:
        return []
    weights = _weights({key: float(item["weight"]) for key, item in collected.items()})
    if not weights:
        return []
    return [{**collected[key], "weight": weights[key]} for key in DRIVER_ORDER if key in weights]


def select_pool_for_ai(pool: list[dict], cards: list[dict], limit: int = 120) -> list[dict]:
    """给 AI 挑快讯: 与卡片相关的排前面, 其余按时间新到旧补齐。

    一天的多源快讯有几百条, 其中大部分是海外宏观与个股公告; 把「与本次板块相关」的
    条目优先放进清单, AI 才不会在无关新闻里翻找 —— 同时限制 prompt 体积。
    返回的顺序就是引用编号, 调用方必须拿同一份列表回池解析 flash_ids。
    """
    if not pool:
        return []
    contexts = [
        (str(card.get("name") or ""), [s.get("name") for s in card.get("stocks") or []])
        for card in cards
    ]
    scored: list[tuple[int, str, dict]] = []
    for item in pool:
        best = 0
        for name, members in contexts:
            tokens = sector_tokens(name)
            base = tokens[0] if tokens else ""
            for suffix in _GENERIC_SUFFIXES:
                if len(base) > len(suffix) and base.endswith(suffix):
                    base = base[: -len(suffix)]
                    break
            score, _hits = _match_score(
                _news_title_text(item),
                name,
                base,
                tokens,
                [m for m in members if m],
                str(item.get("content") or ""),
            )
            best = max(best, score)
            if best >= _MATCH_THRESHOLD:
                break
        scored.append((best, str(item.get("time") or ""), item))
    scored.sort(key=lambda row: (row[0] > 0, row[0], row[1]), reverse=True)
    return [row[2] for row in scored[:limit]]


def pool_for_prompt(pool: list[dict], limit: int = 120) -> str:
    """把快讯池渲染成带序号的清单(序号即 AI 可用 flash_ids 引用的下标)。"""
    lines = []
    for index, item in enumerate(pool[:limit]):
        stamp = str(item.get("time") or "")[5:16]
        body = str(item.get("content") or "").replace("\n", " ")[:80]
        lines.append(f"[{index}] {stamp} {item.get('source') or ''} | {item.get('title') or ''} | {body}")
    return "\n".join(lines)


def format_driver_brief(drivers: list[dict]) -> str:
    """把驱动分解压成一行(供 AI 参考数据, 也便于日志排查)。"""
    return " / ".join(f"{d['label']}{d['weight']}%" for d in drivers) if drivers else "—"
