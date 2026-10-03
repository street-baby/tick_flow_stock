# -*- coding: utf-8 -*-
"""新闻与「明天炒什么」题材催化前瞻服务。

整合 AKShare 多源财经快讯、央视联播要闻、财联社头条与东财热点，
并通过 AI 大模型进行全天热点与早盘开盘前瞻的自动化归纳整合，
同时无缝对接智兔 (Zhitu) 实时行情数据赋予最新价格与涨跌幅。
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from collections.abc import Iterable
from datetime import date, datetime, time as dt_time, timedelta
from pathlib import Path
from typing import Any, List, Optional
import httpx

logger = logging.getLogger(__name__)

# 多源快讯合并池: 板块归因需要「足够长的候选集」(单源最新 20 条覆盖不到交易日的催化)
_POOL_TTL = 300.0

# 7x24 快讯滚动池: 上游每次只回最近 50 条, 靠「每次请求现拉一次」的旧做法页面
# 永远只看得到那个 50 条的滑动窗口。这里由服务端按固定节奏持续抓取累积,
# 前端读的是连续时间线, 而不是一个不断被覆盖的窗口。
_FLASH_STORE_CAP = 800
_FLASH_RETENTION_HOURS = 48
# 池子超过这个时间没被更新时的兜底同步刷新(没有 poller 的场景: 测试 / CLI)
_FLASH_REFRESH_TTL = 15.0
# 落盘节流: 每条新快讯都写盘会打满磁盘, 但丢进程会损失几分钟时间线
_FLASH_SAVE_MIN_INTERVAL = 60.0

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://finance.sina.com.cn/",
}


def _clean_text(s: str) -> str:
    if not s:
        return ""
    # 去除 HTML 标签与多余空白
    cleaned = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", cleaned).strip()


def _coerce_dt(value: Any, date_part: Any = None) -> Optional[datetime]:
    """把各源五花八门的时间字段统一成 datetime。

    已见形态: 东财/富途/同花顺/新浪给字符串 "2026-09-20 23:01:24",
    财联社给 date(发布日期) + time(发布时间) 两列。解析不了就返回 None(调用方丢弃)。
    """
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        # 财联社形态: 日期在 value, 时间在 date_part
        clock = date_part if isinstance(date_part, dt_time) else dt_time.min
        return datetime.combine(value, clock)
    if isinstance(value, dt_time):
        base = date_part if isinstance(date_part, date) else date.today()
        return datetime.combine(base, value)
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _news_title(title: Any, content: str) -> str:
    """标题缺失时从正文里取「【…】」或首句, 不把空标题的条目丢掉。"""
    text = _clean_text(str(title or ""))
    if text:
        return text
    if content.startswith("【") and "】" in content:
        return content[1 : content.index("】")].strip()
    return content[:48].strip()


def _news_id(source: str, title: str) -> str:
    return hashlib.sha1(f"{source}|{title}".encode()).hexdigest()[:12]


# 同一事件在不同源里的标题前缀: 财联社「X月X日电，」、「据…报道，」
_TITLE_LEAD = re.compile(r"^(?:财联社\d{1,2}月\d{1,2}日电[，,：:]?|据[^，,]{0,10}报道[，,]?)")
# 新浪把标题包在【】里: 方括号本身要去掉, 但括号里的字是标题正文, 不能一起删
_TITLE_BRACKETS = re.compile(r"[【】\[\]]")
_TITLE_MIN_OVERLAP = 12


def _title_key(title: str) -> str:
    """归一化标题: 去源前缀、去方括号与标点空白, 用于识别同一事件的多源重复。"""
    text = _TITLE_LEAD.sub("", str(title or "").strip())
    text = _TITLE_BRACKETS.sub("", text)
    return re.sub(r"[\s\W_]+", "", text)


def _same_story(key: str, kept: list[str]) -> bool:
    """同一事件的判定: 归一化后互为前缀/包含(长度足够时)。"""
    if len(key) < _TITLE_MIN_OVERLAP:
        return key in kept
    return any(key in other or other in key for other in kept)


def _iso(ts: float | None) -> str | None:
    """epoch 秒 → 本地 'YYYY-MM-DD HH:MM:SS'(0 / None → None)。"""
    if not ts:
        return None
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _normalize_flash(raw: Any) -> dict | None:
    """上游快讯 → 池子统一结构。缺 id 时按来源+标题派生, 避免同一事件反复入库。"""
    if not isinstance(raw, dict):
        return None
    title = _clean_text(str(raw.get("title") or ""))
    content = _clean_text(str(raw.get("content") or ""))
    if not title and not content:
        return None
    ident = str(raw.get("id") or "").strip()
    if not ident:
        ident = _news_id(str(raw.get("source") or raw.get("tag") or "快讯"), title or content[:32])
    item: dict = {
        "id": ident,
        "time": str(raw.get("time") or "").strip(),
        "tag": str(raw.get("tag") or "").strip(),
        "title": title or content[:48],
        "content": content,
        "url": str(raw.get("url") or "").strip(),
    }
    if raw.get("is_fallback"):
        item["is_fallback"] = True
    return item


class FlashFeed:
    """进程级 7x24 快讯滚动池 — 去重 / 排序 / 截断 / 落盘。

    线程安全: poller 线程持续写, 请求线程(可能多个)读。
    只存真实抓回来的条目 —— 上游不可用时的兜底示例文案不进池子(否则会被
    当成资讯长期留在时间线里)。
    """

    def __init__(self, cap: int = _FLASH_STORE_CAP, retention_hours: int = _FLASH_RETENTION_HOURS) -> None:
        self._cap = cap
        self._retention_hours = retention_hours
        self._lock = threading.RLock()
        self._items: list[dict] = []
        self._ids: set[str] = set()
        self._updated_at: float = 0.0
        self._attempt_at: float = 0.0
        self._saved_at: float = 0.0
        self._last_error: str | None = None

    # ── 读 ──
    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    @property
    def updated_at(self) -> float:
        """最近一次成功拿到上游内容的时刻(0 = 从未成功)。"""
        with self._lock:
            return self._updated_at

    @property
    def attempt_at(self) -> float:
        """最近一次抓取尝试的时刻(含失败)。"""
        with self._lock:
            return self._attempt_at

    @property
    def last_error(self) -> str | None:
        with self._lock:
            return self._last_error

    def items(self, limit: int | None = None) -> list[dict]:
        """按时间倒序快照; limit=None 返回整个池子。"""
        with self._lock:
            if limit is None or limit >= len(self._items):
                return list(self._items)
            return self._items[: max(0, limit)]

    def latest_time(self) -> str | None:
        with self._lock:
            return str(self._items[0].get("time")) if self._items else None

    def clear(self) -> None:
        with self._lock:
            self._items = []
            self._ids = set()
            self._updated_at = 0.0
            self._attempt_at = 0.0
            self._last_error = None

    # ── 写 ──
    def merge(self, rows: Iterable[Any]) -> list[dict]:
        """并入一批上游快讯, 返回本次新增条目(时间倒序)。只在抓取成功时调用。"""
        moment = time.time()
        added: list[dict] = []
        with self._lock:
            self._attempt_at = moment
            self._updated_at = moment
            self._last_error = None
            for raw in rows or []:
                item = _normalize_flash(raw)
                if item is None or item["id"] in self._ids:
                    continue
                self._ids.add(item["id"])
                self._items.append(item)
                added.append(item)
            self._trim(moment)
        added.sort(key=lambda it: str(it.get("time") or ""), reverse=True)
        return added

    def note_failure(self, error: str) -> None:
        """抓取失败: 记尝试时刻与原因, 不动 updated_at(前端据此知道数据没在刷新)。"""
        with self._lock:
            self._attempt_at = time.time()
            self._last_error = str(error)[:200]

    def _trim(self, moment: float) -> None:
        cutoff = moment - self._retention_hours * 3600
        kept: list[dict] = []
        for item in self._items:
            parsed = _coerce_dt(item.get("time"))
            # 解析不出时间的条目留着(宁可见到, 也不悄悄丢), 只是排序时靠后
            if parsed is not None and parsed.timestamp() < cutoff:
                continue
            kept.append(item)
        kept.sort(key=lambda it: str(it.get("time") or ""), reverse=True)
        if len(kept) > self._cap:
            kept = kept[: self._cap]
        self._items = kept
        self._ids = {str(it["id"]) for it in kept}

    # ── 落盘 ──
    def load(self, path: Path) -> int:
        """从磁盘恢复池子(进程重启后快讯时间线不断档)。返回当前池内条数。"""
        try:
            if not path.exists():
                return 0
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("读取快讯池失败(%s): %s", path, exc)
            return 0
        if not isinstance(raw, list):
            return 0
        with self._lock:
            for item in raw:
                normalized = _normalize_flash(item)
                if normalized is None or normalized["id"] in self._ids:
                    continue
                self._ids.add(normalized["id"])
                self._items.append(normalized)
            self._trim(time.time())
            return len(self._items)

    def save(self, path: Path, *, force: bool = False) -> bool:
        """把池子写盘(默认节流 60s)。写临时文件再替换, 避免读到写了一半的 JSON。"""
        moment = time.time()
        with self._lock:
            if not force and (moment - self._saved_at) < _FLASH_SAVE_MIN_INTERVAL:
                return False
            payload = json.dumps(self._items, ensure_ascii=False)
            self._saved_at = moment
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(path)
            return True
        except Exception as exc:
            logger.warning("写入快讯池失败(%s): %s", path, exc)
            return False


# 进程级单例 —— NewsService 是按请求构造的, 池子必须放模块级才能共享
flash_feed = FlashFeed()
_FLASH_LOAD_LOCK = threading.RLock()
_flash_loaded_path: Path | None = None

class NewsService:
    """新闻与前瞻催化服务单例"""

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or Path("data")
        self._catalysts_file = self.data_dir / "user_data" / "tomorrow_catalysts.json"
        self._morning_file = self.data_dir / "user_data" / "morning_brief.json"
        self._flash_file = self.data_dir / "user_data" / "flash_feed.json"
        self._ensure_files()

    def _ensure_files(self) -> None:
        self._catalysts_file.parent.mkdir(parents=True, exist_ok=True)
        if not self._catalysts_file.exists():
            default_data = self._get_initial_catalysts()
            try:
                self._catalysts_file.write_text(json.dumps(default_data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as e:
                logger.warning("初始化 tomorrow_catalysts.json 失败: %s", e)

        if not self._morning_file.exists():
            default_morning = self._get_initial_morning_brief()
            try:
                self._morning_file.write_text(json.dumps(default_morning, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as e:
                logger.warning("初始化 morning_brief.json 失败: %s", e)

    def _get_initial_catalysts(self) -> list[dict]:
        """预置经典前瞻催化数据"""
        today_str = date.today().strftime("%Y-%m-%d")
        next_day_str = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
        prev_day_str = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")

        return [
            {
                "id": "cat_001",
                "date": next_day_str,
                "date_label": f"{next_day_str} 下一个交易日",
                "tag": "铝箔",
                "title": "行业供需拐点已至！高附加值电池铝箔迎量价齐升窗口",
                "summary": "受益于储能与动力电池出货量强劲增长，龙头企业满负荷运转，海外订单饱满。海外头部车企追加采购协议，行业加工费企稳回升预期强烈。",
                "sector_change_pct": 2.17,
                "stocks": [
                    {"symbol": "601609.SH", "name": "金田股份"},
                    {"symbol": "000563.SZ", "name": "陕国投A"},
                    {"symbol": "300252.SZ", "name": "金信诺"},
                ],
            },
            {
                "id": "cat_002",
                "date": next_day_str,
                "date_label": f"{next_day_str} 下一个交易日",
                "tag": "空悬/低空",
                "title": "SK海力士满产扩产！低空飞行与车载传感器迎来全面爆发",
                "summary": "高端智能电动汽车搭载空气悬架与激光雷达渗透率快速攀升，核心部件国产替代进入提速期。头部厂商获得多款主流车型定点，订单规模超百亿元。",
                "sector_change_pct": -1.37,
                "stocks": [
                    {"symbol": "002139.SZ", "name": "拓邦股份"},
                    {"symbol": "002869.SZ", "name": "金溢科技"},
                    {"symbol": "002405.SZ", "name": "四维图新"},
                ],
            },
            {
                "id": "cat_003",
                "date": next_day_str,
                "date_label": f"{next_day_str} 下一个交易日",
                "tag": "存储芯片",
                "title": "AI算力爆发带动HBM与DDR5涨价潮！三季度排单全面饱和",
                "summary": "国际存储大厂加速向先进节点制程切换，通用与特种DRAM现货价格持续上扬。国内龙头封测与接口芯片厂商三季度稼动率保持95%以上，盈利弹性显著增强。",
                "sector_change_pct": -1.95,
                "stocks": [
                    {"symbol": "002185.SZ", "name": "华天科技"},
                    {"symbol": "002236.SZ", "name": "大华股份"},
                    {"symbol": "002409.SZ", "name": "雅克科技"},
                ],
            },
            {
                "id": "cat_004",
                "date": next_day_str,
                "date_label": f"{next_day_str} 下一个交易日",
                "tag": "先进封装",
                "title": "台积电CoWoS与Chiplet产能紧缺，国产先进封装链迎扩产红利",
                "summary": "AI芯片需求推动CoWoS封装供不应求，供应链积极布局2.5D/3D先进封装工艺。封装材料与测试设备核心供应商迎来密集交付周期。",
                "sector_change_pct": -0.44,
                "stocks": [
                    {"symbol": "603259.SH", "name": "药明康德"},
                    {"symbol": "603995.SH", "name": "甬金股份"},
                    {"symbol": "603990.SH", "name": "麦迪科技"},
                ],
            },
            {
                "id": "cat_005",
                "date": next_day_str,
                "date_label": f"{next_day_str} 下一个交易日",
                "tag": "同步电感",
                "title": "多模态大模型带动算力中心供电升级，高频电感迎来技术迭代",
                "summary": "新一代AI服务器功耗大幅提升，要求供电架构升级至更高频、更低损耗的芯片电感。头部企业已进入国际顶级算力芯片供应链，实现小批量试产并批量供货。",
                "sector_change_pct": 1.30,
                "stocks": [
                    {"symbol": "601579.SH", "name": "会稽山"},
                    {"symbol": "002612.SZ", "name": "朗姿股份"},
                ],
            },
            {
                "id": "cat_006",
                "date": today_str,
                "date_label": f"{today_str} 当日催化",
                "tag": "铜箔",
                "title": "可转债规模刷新！高频高速PCB与超薄铜箔需求双击",
                "summary": "算力交换机与高速背板对低粗糙度、高抗剥离强度铜箔需求旺盛，海外大厂扩产节奏放缓，国内龙头份额持续提升。",
                "sector_change_pct": 1.48,
                "stocks": [
                    {"symbol": "301376.SZ", "name": "致尚科技"},
                    {"symbol": "002871.SZ", "name": "伟隆股份"},
                ],
            },
            {
                "id": "cat_007",
                "date": today_str,
                "date_label": f"{today_str} 当日催化",
                "tag": "电路",
                "title": "半导体级高多层板及HDI出货量攀升，产能利用率达到历史高位",
                "summary": "汽车智能化与服务器高算力板需求强劲，高价值量产品占比提升显著带动毛利率改善。",
                "sector_change_pct": 0.95,
                "stocks": [
                    {"symbol": "002879.SZ", "name": "长缆科技"},
                    {"symbol": "600667.SH", "name": "太极实业"},
                ],
            },
            {
                "id": "cat_008",
                "date": prev_day_str,
                "date_label": f"{prev_day_str} 历史前瞻",
                "tag": "贵金属",
                "title": "中东地缘局势扰动叠加降息预期强化，避险资产受资金青睐",
                "summary": "国际金价高位震荡，全球央行持续净购金，黄金及贵金属采选冶炼企业业绩稳步释放。",
                "sector_change_pct": 1.55,
                "stocks": [
                    {"symbol": "600547.SH", "name": "山东黄金"},
                    {"symbol": "000657.SZ", "name": "中钨高新"},
                ],
            },
        ]

    def _get_initial_morning_brief(self) -> dict:
        """预置早盘开盘前瞻精要"""
        today_str = date.today().strftime("%Y-%m-%d")
        return {
            "date": today_str,
            "updated_at": datetime.now().strftime("%Y-%m-%d 08:35:00"),
            "sentiment": "结构分化 · 聚焦核心",
            "sentiment_color": "amber",
            "headline": "隔夜外盘芯片与AI链全线爆发，国内政策加码低空与先进制造",
            "overnight_summary": "美股三大指数集体收涨，纳指涨超1.2%，费城半导体指数大涨2.4%。国际原油小幅回调，COMEX黄金站稳高位，离岸人民币汇率保持平稳。",
            "core_focus": [
                {"tag": "存储/算力", "desc": "美股存储与AI芯片领涨，关注国内算力芯片与先进封装开盘承接"},
                {"tag": "低空经济", "desc": "多地低空空域管理新规落地，核心整机与激光雷达龙头催化明显"},
                {"tag": "电网/特高压", "desc": "迎峰度夏用电负荷创新高，超导及变压器出口链有望获资金青睐"}
            ],
            "opening_tactics": "今日集合竞价重点关注昨日首板及大成交突破个股的高开溢价与封单承接；对于高位无承接连板股注意冲高分化风险，以回踩低吸和趋势突破为主。",
        }

    def get_morning_brief(self) -> dict:
        """获取最新今日早盘前瞻"""
        try:
            if self._morning_file.exists():
                return json.loads(self._morning_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("读取 morning_brief.json 失败: %s", e)
        return self._get_initial_morning_brief()

    def save_morning_brief(self, data: dict) -> dict:
        """保存早盘前瞻"""
        data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._morning_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return data

    def fetch_akshare_daily_news(self, target_date: str = "") -> list[dict]:
        """通过 AKShare 聚合指定日期全天重大新闻、央视要闻、东财热点与财联社快讯"""
        if not target_date:
            target_date = date.today().strftime("%Y-%m-%d")

        compact_date = target_date.replace("-", "")
        news_items: list[dict] = []

        # 1. AKShare CCTV 联播要闻
        try:
            import akshare as ak
            cctv_df = ak.news_cctv(date=compact_date)
            if not cctv_df.empty:
                for _, row in cctv_df.iterrows():
                    news_items.append({
                        "source": "央视新闻/宏观政策",
                        "time": f"{target_date} 19:00",
                        "title": str(row.get("title", "")),
                        "content": str(row.get("content", "")),
                    })
        except Exception as e:
            logger.debug("AKShare news_cctv fetch failed: %s", e)

        # 2. AKShare 财联社全球要闻
        try:
            import akshare as ak
            cls_df = ak.stock_info_global_cls()
            if not cls_df.empty:
                for _, row in cls_df.iterrows():
                    news_items.append({
                        "source": "财联社/全球快讯",
                        "time": str(row.get("发布时间", f"{target_date} 12:00")),
                        "title": str(row.get("标题", "")),
                        "content": str(row.get("内容", "")),
                    })
        except Exception as e:
            logger.debug("AKShare stock_info_global_cls fetch failed: %s", e)

        # 3. AKShare 东方财富热点题材
        try:
            import akshare as ak
            hot_df = ak.stock_hot_keyword_em()
            if not hot_df.empty:
                for _, row in hot_df.iterrows():
                    concept = row.get("概念名称")
                    code = row.get("股票代码")
                    if concept:
                        news_items.append({
                            "source": "东财热点题材",
                            "time": str(row.get("时间", f"{target_date} 15:00")),
                            "title": f"热点题材聚焦: {concept} (相关代码: {code})",
                            "content": f"东财人气热度攀升，资金关注板块: {concept}",
                        })
        except Exception as e:
            logger.debug("AKShare stock_hot_keyword_em fetch failed: %s", e)

        # 4. 实时快讯补充 (Sina / EastMoney)
        flash_list = self.fetch_live_flash(limit=40)
        for f in flash_list:
            news_items.append({
                "source": f.get("tag", "财经快讯"),
                "time": f.get("time", ""),
                "title": f.get("title", ""),
                "content": f.get("content", ""),
            })

        return news_items

    def get_tomorrow_catalysts(self, keyword: str = "", date_filter: str = "") -> list[dict]:
        """获取「明天炒什么」前瞻题材列表，并注入智兔实时股票价格"""
        try:
            if self._catalysts_file.exists():
                catalysts = json.loads(self._catalysts_file.read_text(encoding="utf-8"))
            else:
                catalysts = self._get_initial_catalysts()
        except Exception as e:
            logger.warning("读取 catalysts 失败: %s", e)
            catalysts = self._get_initial_catalysts()

        # 获取智兔最新实时快照给股票赋予实时价格
        quotes_map = self._get_realtime_quotes_map()

        out: list[dict] = []
        for cat in catalysts:
            if date_filter and cat.get("date") != date_filter:
                continue
            if keyword:
                kw = keyword.lower()
                tag_match = kw in cat.get("tag", "").lower()
                title_match = kw in cat.get("title", "").lower()
                summary_match = kw in cat.get("summary", "").lower()
                stock_match = any(kw in s.get("name", "").lower() or kw in s.get("symbol", "").lower() for s in cat.get("stocks", []))
                if not (tag_match or title_match or summary_match or stock_match):
                    continue

            # 填充股票实时行情
            enriched_stocks = []
            for stk in cat.get("stocks", []):
                sym = stk.get("symbol", "")
                q = quotes_map.get(sym)
                if q:
                    enriched_stocks.append({
                        "symbol": sym,
                        "name": stk.get("name") or q.get("name") or sym,
                        "last_price": q.get("last_price"),
                        "change_pct": q.get("change_pct"),
                    })
                else:
                    enriched_stocks.append(stk)

            cat_copy = dict(cat)
            cat_copy["stocks"] = enriched_stocks
            out.append(cat_copy)

        return out

    def save_catalyst(self, item: dict) -> dict:
        """添加或更新题材催化项"""
        catalysts = self.get_tomorrow_catalysts()
        item_id = item.get("id") or f"cat_{int(time.time()*1000)}"
        item["id"] = item_id
        if not item.get("date"):
            item["date"] = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
        if not item.get("date_label"):
            item["date_label"] = f"{item['date']} 下一个交易日"

        updated = False
        for i, c in enumerate(catalysts):
            if c.get("id") == item_id:
                catalysts[i] = item
                updated = True
                break
        if not updated:
            catalysts.insert(0, item)

        self._catalysts_file.write_text(json.dumps(catalysts, ensure_ascii=False, indent=2), encoding="utf-8")
        return item

    def delete_catalyst(self, item_id: str) -> bool:
        """删除某个前瞻题材项"""
        catalysts = self.get_tomorrow_catalysts()
        new_list = [c for c in catalysts if c.get("id") != item_id]
        self._catalysts_file.write_text(json.dumps(new_list, ensure_ascii=False, indent=2), encoding="utf-8")
        return True

    def _akshare_news_rows(self, ak, func_name: str, source: str, body_col: str) -> list[dict]:
        """单个 akshare 全球快讯源的容错读取(返回统一结构)。"""
        if ak is None:
            return []
        func = getattr(ak, func_name, None)
        if func is None:
            logger.debug("快讯合并池: akshare 无 %s", func_name)
            return []
        try:
            df = func()
        except Exception as exc:  # 单源失败不影响其余来源
            logger.debug("快讯合并池 %s 拉取失败: %s", func_name, exc)
            return []
        if df is None or getattr(df, "empty", True):
            return []

        rows: list[dict] = []
        for row in df.to_dict("records"):
            content = _clean_text(str(row.get(body_col) or row.get("内容") or row.get("摘要") or ""))
            title = _news_title(row.get("标题"), content)
            if not title:
                continue
            # 各源时间列名不同: 东财/富途/同花顺 = 发布时间, 财联社 = 发布日+发布时间, 新浪 = 时间
            moment = _coerce_dt(row.get("发布时间") or row.get("时间"), row.get("发布日期"))
            if moment is None:
                continue
            rows.append({
                "id": _news_id(source, title),
                "time": moment.strftime("%Y-%m-%d %H:%M:%S"),
                "title": title,
                "content": content,
                "source": source,
                "url": str(row.get("链接") or ""),
            })
        return rows

    def fetch_news_pool(self, limit: int = 300, within_hours: int = 48) -> list[dict]:
        """多源财经快讯合并池(标题/正文/时间/来源/链接), 供板块归因与关联快讯检索。

        源: 东财全球快讯(约 200 条, 覆盖最近一天) + 富途 + 同花顺 + 财联社 + 新浪 7x24。
        单一源失败不阻塞其余来源; 结果按标题去重、时间倒序, 只留 within_hours 小时内的条目。
        进程内缓存 _POOL_TTL 秒 —— 这是读取路径, 不该每个请求都打上游。
        """
        now = time.time()
        if NewsService._pool_cache and (now - NewsService._pool_cache_ts) < _POOL_TTL:
            return NewsService._pool_cache[:limit]

        try:
            import akshare as ak
        except Exception as exc:  # 缺依赖时退化为只用站内实时快讯
            logger.warning("快讯合并池: akshare 不可用: %s", exc)
            ak = None

        items: list[dict] = []
        for source, func_name, body_col in (
            ("东方财富", "stock_info_global_em", "摘要"),
            ("富途", "stock_info_global_futu", "内容"),
            ("同花顺", "stock_info_global_ths", "内容"),
            ("财联社", "stock_info_global_cls", "内容"),
            ("新浪财经", "stock_info_global_sina", "内容"),  # 正文自带「【标题】」前缀
        ):
            items.extend(self._akshare_news_rows(ak, func_name, source, body_col))
        for flash in self.fetch_live_flash(limit=30):
            if flash.get("is_fallback"):
                continue
            moment = _coerce_dt(flash.get("time"))
            title = _news_title(flash.get("title"), str(flash.get("content") or ""))
            if moment is None or not title:
                continue
            items.append({
                "id": _news_id("新浪7x24", title),
                "time": moment.strftime("%Y-%m-%d %H:%M:%S"),
                "title": title,
                "content": _clean_text(str(flash.get("content") or "")),
                "source": "新浪7x24",
                "url": str(flash.get("url") or ""),
            })

        cutoff = datetime.now() - timedelta(hours=max(1, int(within_hours)))
        items = [it for it in items if _coerce_dt(it["time"]) and _coerce_dt(it["time"]) >= cutoff]
        items.sort(key=lambda it: it["time"], reverse=True)

        # 同一事件常被多家源以不同口吻转发(富途与财联社的标题只差一个前缀),
        # 只删完全相同的标题会让卡片上出现两条一模一样的快讯
        kept_keys: list[str] = []
        pool: list[dict] = []
        for item in items:
            key = _title_key(item["title"])
            if not key or _same_story(key, kept_keys):
                continue
            kept_keys.append(key)
            pool.append(item)

        NewsService._pool_cache = pool
        NewsService._pool_cache_ts = now
        return pool[:limit]

    # ── 7x24 快讯滚动池 ───────────────────────────────────────────────
    def _ensure_flash_feed_loaded(self) -> None:
        """首次访问时从磁盘恢复池子(每个 data_dir 只恢复一次, 不覆盖内存里已累积的)。"""
        global _flash_loaded_path
        path = self._flash_file
        with _FLASH_LOAD_LOCK:
            if _flash_loaded_path == path:
                return
            flash_feed.clear()
            flash_feed.load(path)
            _flash_loaded_path = path

    def _fetch_upstream_flash(self) -> list[dict]:
        """拉一次上游 7x24 快讯(新浪财经直播)。失败抛异常, 由调用方决定降级策略。"""
        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=8.0) as client:
            r = client.get("https://zhibo.sina.com.cn/api/zhibo/feed?zhibo_id=152&limit=50")
            r.raise_for_status()
            data = r.json()
        raw_list = data.get("result", {}).get("data", {}).get("feed", {}).get("list", []) or []

        out: list[dict] = []
        for item in raw_list:
            rich_text = item.get("rich_text") or ""
            doc_url = item.get("docurl") or ""
            create_time = item.get("create_time") or ""
            tag = item.get("tag", [{}])[0].get("name") if item.get("tag") else "要闻"
            title = rich_text.split("】", 1)[0].replace("【", "") if "【" in rich_text else ""
            body = rich_text.split("】", 1)[1] if "【" in rich_text else rich_text
            out.append({
                "id": str(item.get("id")),
                "time": create_time,
                "tag": tag or "财经",
                "title": title or _clean_text(rich_text[:30]),
                "content": _clean_text(body or rich_text),
                "url": doc_url,
            })
        return out

    def refresh_flash_store(self) -> list[dict]:
        """抓一次上游并并入滚动池, 返回本次新增条目(空列表 = 上游没新内容)。

        是否抓取由调用方决定(NewsPoller 定节奏 / 读取路径的兜底 TTL),
        读取路径不该每个请求都打上游。
        """
        self._ensure_flash_feed_loaded()
        try:
            rows = self._fetch_upstream_flash()
        except Exception as exc:  # 上游挂了不能让请求路径 500
            logger.warning("拉取 7x24 快讯失败: %s", exc)
            flash_feed.note_failure(str(exc))
            return []
        return flash_feed.merge(rows)

    def refresh_flash_from_pool(self, limit: int = 120, within_hours: int = 12) -> list[dict]:
        """降级抓取: 用多源合并池(东财/富途/同花顺/财联社/新浪)补进滚动池。

        主源(新浪 7x24 直播)被限流或改版时, 时间线不该整段停住 —— 已有的多源能力
        在这里接到池子上。返回本次新增条目(空 = 池里已经有这些)。
        """
        self._ensure_flash_feed_loaded()
        rows = self.fetch_news_pool(limit=limit, within_hours=within_hours)
        if not rows:
            return []
        now = datetime.now()
        merged: list[dict] = []
        for row in rows:
            moment = _coerce_dt(row.get("time"))
            # 各源时间列口径不一(如富途的发布时间随服务器本地时区换算, 非北京时区的
            # 机器会整体偏到未来), 而快讯不可能来自未来: 越界的一律按「刚刚」入池,
            # 保住时间线排序与「今天/昨天」分组
            if moment is None or moment > now:
                moment = now
            merged.append({
                "id": row.get("id"),
                "time": moment.strftime("%Y-%m-%d %H:%M:%S"),
                # 合并池的 source 就是池子里的 tag —— 降级条目在界面上要能看出出处
                "tag": row.get("source") or "快讯",
                "title": row.get("title"),
                "content": row.get("content"),
                "url": row.get("url"),
            })
        return flash_feed.merge(merged)

    def save_flash_store(self, *, force: bool = False) -> bool:
        """把滚动池落盘(默认节流), 让进程重启后快讯时间线不断档。"""
        return flash_feed.save(self._flash_file, force=force)

    @staticmethod
    def flash_meta() -> dict:
        """快讯新鲜度元信息 —— 前端据此显示「实时更新 · 刚刚」而不是盲猜。"""
        return {
            "updated_at": _iso(flash_feed.updated_at),
            "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def fetch_live_flash(self, limit: int = 50) -> list[dict]:
        """读取 7x24 实时快讯。

        池子(FlashFeed)由 NewsPoller 持续写入; 这里只做「池子还没热 / 太久没更新」
        时兜底同步补一次, 保证没有 poller 的场景(测试 / CLI)也能拿到数据。
        """
        self._ensure_flash_feed_loaded()
        now = time.time()
        if flash_feed.attempt_at <= 0 or (now - flash_feed.attempt_at) > _FLASH_REFRESH_TTL:
            self.refresh_flash_store()

        items = flash_feed.items(limit)
        if items:
            return items

        # 兜底示例文案。is_fallback 标记让前端能把这批跟真实快讯区分开展示,
        # 不把演示内容当资讯(也不进池子)。
        return [
            {
                "id": "f_1",
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "tag": "半导体",
                "title": "晶圆代工产能持续紧张，功率与模拟芯片排期延长",
                "content": "业内人士表示，随着端侧AI及新能源汽车应用深入，8英寸与12英寸晶圆代工订单饱满。",
                "is_fallback": True,
            },
            {
                "id": "f_2",
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "tag": "固态电池",
                "title": "全固态电池产线建设进入关键节点，关键材料实现首批装车验证",
                "content": "多家具备硫化物及聚合物路线研发能力的企业宣布中试线投产，能量密度突破450Wh/kg。",
                "is_fallback": True,
            },
        ][:limit]

    _quotes_map_cache: dict[str, dict] = {}
    _quotes_map_cache_ts: float = 0.0
    # 多源快讯合并池缓存(进程级: 归因是读取路径, 多请求共享同一份池子)
    _pool_cache: list[dict] = []
    _pool_cache_ts: float = 0.0

    def _get_realtime_quotes_map(self) -> dict[str, dict]:
        """从智兔数据源获取最新全市场实时行情映射表 {symbol: quote}（带 30 秒内存缓存）"""
        now = time.time()
        if NewsService._quotes_map_cache and (now - NewsService._quotes_map_cache_ts < 30.0):
            return NewsService._quotes_map_cache

        quotes_map: dict[str, dict] = {}
        try:
            from app.data_providers import custom as custom_sources
            provider = custom_sources.get_provider("zhitu")
            if provider:
                rows = provider.get_realtime()
                for r in rows:
                    sym = r.get("symbol")
                    if sym:
                        quotes_map[sym] = r
                if quotes_map:
                    NewsService._quotes_map_cache = quotes_map
                    NewsService._quotes_map_cache_ts = now
        except Exception as e:
            logger.debug("获取智兔实时行情映射失败: %s", e)
        return quotes_map or NewsService._quotes_map_cache
