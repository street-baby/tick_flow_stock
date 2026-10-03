# -*- coding: utf-8 -*-
"""快讯打标 —— 为 7x24 财经快讯补「利好/利空方向 + 关联板块 + 关联标的」。

名称与词典来源全部是现有资产, 不新增数据源:
  - 板块名: rps_rotation 的维度全集(概念 / 行业二级), 与板块简报同一口径
  - 标的名: repository.get_name_map (股票 + ETF + 指数)

实现要点:
  - 名称匹配用「一次编译的 alternation 正则」而不是逐名 `in` 扫描:
    4000+ 标的名 × 200 条快讯直接 `in` 是百万级子串比较, 正则在 C 层完成同一件事。
    名称按长度降序排列, 保证同一起点优先命中更长的板块名
    (避免「芯片」抢占「国产芯片概念」)。
  - 只扫描标题 + 正文前 _TEXT_SCAN_CHARS 字; 索引按 TTL 缓存并加锁, 不进实时热路径。
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Iterable

logger = logging.getLogger(__name__)

# 文本扫描上限: 快讯全文常达数千字, 打标只需要判断方向与命中实体, 不必全扫
_TEXT_SCAN_CHARS = 200
# 标的简称的最大匹配数量: 命中过多时说明文本里有通用词, 只保留最长匹配
_MAX_MATCHES = 5
# 板块名最短 2 字(如「券商」「光刻」); 标的名最短 3 字, 2 字简称
# (如「中兴」这类前缀词)误命中率过高
_MIN_SECTOR_LEN = 2
_MIN_STOCK_LEN = 3
_LEXICON_TTL = 600.0

# 方向词典: 只看明确表态产业/公司基本面的词, 不含"关注/跟踪"等中性词
BULLISH_WORDS = (
    "涨停", "大涨", "上涨", "中标", "签约", "获批", "批准", "涨价", "提价", "上调",
    "超预期", "创新高", "新高", "突破", "量产", "投产", "扩产", "满产", "订单",
    "回购", "增持", "分红", "扭亏", "盈利", "预增", "增长", "增长超", "放量",
    "利好", "受益", "补贴", "政策支持", "降准", "降息", "获批上市", "合作",
    "首次覆盖", "买入", "推荐", "看好", "景气", "回暖", "复苏", "缺口", "涨价函",
)
BEARISH_WORDS = (
    "跌停", "大跌", "下跌", "减持", "清仓", "亏损", "预亏", "爆雷", "退市", "停牌",
    "处罚", "罚款", "立案", "调查", "问询", "下调", "降价", "低于预期", "不及预期",
    "终止", "取消", "解禁", "质押", "违约", "逾期", "诉讼", "召回", "停产",
    "利空", "承压", "下滑", "萎缩", "裁员", "关停", "制裁", "关税", "卖出", "风险",
)


# 词典预编译: 方向判定在每条快讯上要跑一轮, 用正则让 C 层完成
_BULLISH_PATTERN = re.compile("|".join(re.escape(w) for w in BULLISH_WORDS))
_BEARISH_PATTERN = re.compile("|".join(re.escape(w) for w in BEARISH_WORDS))


class FlashLexicon:
    """预编译的匹配索引(板块名 + 标的名)。"""

    __slots__ = ("sector_names", "sector_pattern", "stock_name_count", "stock_pattern", "symbol_by_name")

    def __init__(
        self,
        sector_pattern: re.Pattern | None,
        stock_pattern: re.Pattern | None,
        symbol_by_name: dict[str, str],
        sector_names: tuple[str, ...],
        stock_name_count: int,
    ) -> None:
        self.sector_pattern = sector_pattern
        self.stock_pattern = stock_pattern
        self.symbol_by_name = symbol_by_name
        self.sector_names = sector_names
        self.stock_name_count = stock_name_count


_lexicon: FlashLexicon | None = None
_lexicon_ts: float = 0.0
_LEXICON_LOCK = threading.RLock()


def invalidate_cache() -> None:
    """清空索引缓存(概念/行业维度或标的维表刷新后调用)。"""
    global _lexicon, _lexicon_ts
    with _LEXICON_LOCK:
        _lexicon = None
        _lexicon_ts = 0.0


def _compile_names(names: Iterable[str]) -> re.Pattern | None:
    """把名称集合编译成单个正则; 长度降序保证长名优先命中。"""
    unique = {str(name).strip() for name in names if str(name).strip()}
    if not unique:
        return None
    ordered = sorted(unique, key=len, reverse=True)
    try:
        return re.compile("|".join(re.escape(name) for name in ordered))
    except re.error as exc:  # 名称来自数据, 异常时退化为不匹配
        logger.warning("快讯词典编译失败: %s", exc)
        return None


def build_lexicon(sector_names: Iterable[str], name_map: dict[str, str]) -> FlashLexicon:
    """由板块名集合与 {symbol: name} 构建匹配索引(纯函数, 便于测试)。"""
    sectors = tuple(
        sorted({str(n).strip() for n in sector_names if len(str(n).strip()) >= _MIN_SECTOR_LEN}, key=len, reverse=True)
    )
    symbol_by_name: dict[str, str] = {}
    for symbol, name in (name_map or {}).items():
        text = str(name or "").strip()
        if len(text) < _MIN_STOCK_LEN:
            continue
        # 同名标的取代码序最小的一个, 保证结果稳定可复现
        if text not in symbol_by_name or str(symbol) < symbol_by_name[text]:
            symbol_by_name[text] = str(symbol)
    return FlashLexicon(
        sector_pattern=_compile_names(sectors),
        stock_pattern=_compile_names(symbol_by_name.keys()),
        symbol_by_name=symbol_by_name,
        sector_names=sectors,
        stock_name_count=len(symbol_by_name),
    )


def _sector_names(repo, days: int = 7) -> set[str]:
    """概念 + 行业(二级)维度全集, 与板块简报使用同一矩阵口径。"""
    from app.services.rps_rotation import build_rps_rotation

    names: set[str] = set()
    for kind, level in (("concept", None), ("industry", 2)):
        try:
            matrix = build_rps_rotation(repo, days=days, kind=kind, level=level)
        except Exception as exc:  # 单维度失败不影响另一维度
            logger.debug("快讯词典获取 %s 维度失败: %s", kind, exc)
            continue
        dates = matrix.get("dates") or []
        if not dates:
            continue
        for name, _pct in matrix.get("columns", {}).get(dates[0]) or []:
            names.add(str(name))
    return names


def load_lexicon(repo) -> FlashLexicon:
    """按 TTL 缓存加载匹配索引(概念/行业维度是 snapshot, 不需高频重建)。"""
    global _lexicon, _lexicon_ts
    now = time.time()
    with _LEXICON_LOCK:
        if _lexicon is not None and (now - _lexicon_ts) < _LEXICON_TTL:
            return _lexicon

    try:
        name_map = repo.get_name_map(None) or {}
    except Exception as exc:  # 无名称索引时仍可做方向与板块打标
        logger.warning("快讯词典获取标的名称失败: %s", exc)
        name_map = {}
    lexicon = build_lexicon(_sector_names(repo), name_map)

    with _LEXICON_LOCK:
        _lexicon = lexicon
        _lexicon_ts = now
    return lexicon


def _match_names(pattern: re.Pattern | None, text: str, limit: int = _MAX_MATCHES) -> list[str]:
    if pattern is None or not text:
        return []
    seen: list[str] = []
    for match in pattern.finditer(text):
        name = match.group(0)
        if name not in seen:
            seen.append(name)
        if len(seen) >= limit:
            break
    return seen


def classify_direction(text: str) -> str:
    """利好 / 利空 / 中性: 命中词多的一方胜出, 平局(含 0 命中)为中性。"""
    if not text:
        return "neutral"
    bull = len(_BULLISH_PATTERN.findall(text))
    bear = len(_BEARISH_PATTERN.findall(text))
    if bull > bear:
        return "bullish"
    if bear > bull:
        return "bearish"
    return "neutral"


def tag_flash_items(items: list[dict], lexicon: FlashLexicon) -> list[dict]:
    """给每条快讯补 direction / sectors / symbols(不改原对象)。"""
    out: list[dict] = []
    for item in items or []:
        title = str(item.get("title") or "")
        content = str(item.get("content") or "")
        text = f"{title} {content[:_TEXT_SCAN_CHARS]}".strip()
        sectors = _match_names(lexicon.sector_pattern, text)
        symbols = [
            {"name": name, "symbol": lexicon.symbol_by_name.get(name)}
            for name in _match_names(lexicon.stock_pattern, text)
        ]
        out.append(
            {
                **item,
                "direction": classify_direction(text),
                "sectors": sectors,
                "symbols": symbols,
            }
        )
    return out
