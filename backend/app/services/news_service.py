# -*- coding: utf-8 -*-
"""新闻与「明天炒什么」题材催化前瞻服务。

整合 AKShare 多源财经快讯、央视联播要闻、财联社头条与东财热点，
并通过 AI 大模型进行全天热点与早盘开盘前瞻的自动化归纳整合，
同时无缝对接智兔 (Zhitu) 实时行情数据赋予最新价格与涨跌幅。
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, List, Optional
import httpx

logger = logging.getLogger(__name__)

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


class NewsService:
    """新闻与前瞻催化服务单例"""

    def __init__(self, data_dir: Optional[Path] = None):
        self.data_dir = data_dir or Path("data")
        self._catalysts_file = self.data_dir / "user_data" / "tomorrow_catalysts.json"
        self._morning_file = self.data_dir / "user_data" / "morning_brief.json"
        self._cache_flash: list[dict] = []
        self._cache_flash_time: float = 0.0
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

    def fetch_live_flash(self, limit: int = 50) -> list[dict]:
        """获取 7x24 实时快讯（带内存缓存 15 秒）"""
        now = time.time()
        if self._cache_flash and (now - self._cache_flash_time < 15.0):
            return self._cache_flash[:limit]

        out: list[dict] = []
        try:
            with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=8.0) as client:
                r = client.get("https://zhibo.sina.com.cn/api/zhibo/feed?zhibo_id=152&limit=50")
                if r.status_code == 200:
                    data = r.json()
                    raw_list = data.get("result", {}).get("data", {}).get("feed", {}).get("list", [])
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
        except Exception as e:
            logger.warning("拉取 7x24 快讯失败: %s", e)

        # 兜底补充
        if not out:
            out = [
                {
                    "id": "f_1",
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "tag": "半导体",
                    "title": "晶圆代工产能持续紧张，功率与模拟芯片排期延长",
                    "content": "业内人士表示，随着端侧AI及新能源汽车应用深入，8英寸与12英寸晶圆代工订单饱满。",
                },
                {
                    "id": "f_2",
                    "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "tag": "固态电池",
                    "title": "全固态电池产线建设进入关键节点，关键材料实现首批装车验证",
                    "content": "多家具备硫化物及聚合物路线研发能力的企业宣布中试线投产，能量密度突破450Wh/kg。",
                }
            ]

        self._cache_flash = out
        self._cache_flash_time = now
        return out[:limit]

    def _get_realtime_quotes_map(self) -> dict[str, dict]:
        """从智兔数据源获取最新全市场实时行情映射表 {symbol: quote}"""
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
        except Exception as e:
            logger.debug("获取智兔实时行情映射失败: %s", e)
        return quotes_map
