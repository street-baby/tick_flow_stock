# -*- coding: utf-8 -*-
"""博弈派 AI 分析引擎 (Game Theory Analysis Engine)。

核心哲学：不预测价格，只量化「人」。
散户扎堆 = 危险（主力出货对象），散户恐慌/不敢买 = 机会（主力吸筹位置）。

架构：
  GameTheoryCollector  — 多源数据采集（东财人气/千股千评/雪球/龙虎榜/融资融券）
  GameTheoryScorer     — 个股博弈评分（恐惧指数 / 拥挤指数）
  MarketGameThermometer — 全市场散户情绪温度计（0°冰点 ↔ 100°沸腾）
  GameTheoryAIAnalyst  — AI 深度博弈解读 + 每日博弈报告
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional
import zoneinfo

logger = logging.getLogger(__name__)

SHANGHAI_TZ = zoneinfo.ZoneInfo("Asia/Shanghai")


def _bj_now() -> datetime:
    return datetime.now(SHANGHAI_TZ)


def _bj_now_str() -> str:
    return _bj_now().strftime("%Y-%m-%d %H:%M:%S")


def _bj_today_str() -> str:
    return _bj_now().date().strftime("%Y-%m-%d")


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        f = float(v)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


# ═══════════════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════════════

@dataclass
class StockGameScore:
    """单股博弈评分"""
    symbol: str
    name: str = ""
    close: float = 0.0
    change_pct: float = 0.0
    # 核心评分
    fear_index: float = 0.0        # 散户恐惧指数 (0-100) 越高=越恐慌=机会
    greed_index: float = 0.0       # 散户拥挤指数 (0-100) 越高=越疯狂=危险
    game_signal: str = "neutral"   # strong_buy / buy / neutral / caution / danger
    # 细分维度得分
    vol_shrink_score: float = 0.0
    turnover_cold_score: float = 0.0
    inst_buy_score: float = 0.0
    margin_decrease_score: float = 0.0
    hot_rank_cold_score: float = 0.0
    xq_cold_score: float = 0.0
    # 反指标诱空得分 (散户恐慌割肉 = 机会)
    ma_breakdown_trap_score: float = 0.0    # 假破MA20/MA60诱空挖坑
    kdj_panic_score: float = 0.0            # KDJ极端恐慌超卖(J负值)
    panic_pinbar_score: float = 0.0         # 恐慌急跌探底神针(长下影)
    macd_dead_trap_score: float = 0.0       # MACD洗盘假死叉诱空
    # 反指标诱多得分 (散户追高 = 危险)
    bull_trap_score: float = 0.0            # 高位MACD金叉诱多出货
    kdj_greed_score: float = 0.0            # KDJ极度超买高潮(J>95)
    breakout_trap_score: float = 0.0        # 假突破冲高回落诱多
    hot_rank_surge_score: float = 0.0
    xq_tweet_surge_score: float = 0.0
    turnover_hot_score: float = 0.0
    margin_increase_score: float = 0.0
    inst_sell_score: float = 0.0
    vol_spike_no_gain_score: float = 0.0
    # 信号原因
    signal_reasons: list[str] = field(default_factory=list)
    # 额外技术与筹码数据
    hot_rank: int = 0
    xq_follow: int = 0
    xq_tweet: int = 0
    inst_net_amount: float = 0.0
    margin_change_pct: float = 0.0
    turnover_rate: float = 0.0
    vol_ratio_5d: float = 0.0
    attention_index: float = 0.0
    inst_participation: float = 0.0
    amount: float = 0.0              # 成交额 (元)
    amplitude: float = 0.0           # 日内振幅 (%)
    kdj_j: float = 50.0              # KDJ J值
    rsi_6: float = 50.0              # RSI 6日值
    macd_hist: float = 0.0           # MACD 柱状值


@dataclass
class MarketTemperature:
    """全市场博弈温度"""
    temperature: float = 50.0
    zone: str = "warm"
    zone_label: str = "温和"
    limit_up_score: float = 0.0
    consecutive_score: float = 0.0
    margin_score: float = 0.0
    lhb_inst_score: float = 0.0
    crowd_score: float = 0.0
    limit_up_count: int = 0
    limit_down_count: int = 0
    seal_rate: float = 0.0
    max_consecutive: int = 0
    margin_total: float = 0.0
    margin_change: float = 0.0
    inst_net_total: float = 0.0
    date: str = ""
    updated_at: str = ""


@dataclass
class GameTheoryReport:
    """AI 博弈日报"""
    date: str = ""
    market_summary: str = ""
    strategy_advice: str = ""
    fear_pool: list[dict] = field(default_factory=list)
    danger_list: list[dict] = field(default_factory=list)
    temperature: float = 50.0
    zone: str = "warm"
    updated_at: str = ""


# ═══════════════════════════════════════════════════════════════════
# GameTheoryCollector — 多源数据采集
# ═══════════════════════════════════════════════════════════════════

class GameTheoryCollector:
    """采集全维度博弈数据快照"""

    def __init__(self):
        self._hot_rank_cache: list[dict] = []
        self._xq_follow_cache: list[dict] = []
        self._xq_tweet_cache: list[dict] = []
        self._comment_cache: list[dict] = []
        self._lhb_detail_cache: list[dict] = []
        self._lhb_inst_cache: list[dict] = []
        self._margin_total_cache: list[dict] = []
        self._last_collect_time: str = ""

    async def collect_all(self, enriched_data: Optional[list[dict]] = None) -> dict[str, Any]:
        """聚合全维度博弈数据快照。在线程池中运行阻塞 AKShare 调用。"""
        loop = asyncio.get_event_loop()
        snapshot: dict[str, Any] = {
            "collect_time": _bj_now_str(),
            "date": _bj_today_str(),
        }

        tasks = {
            "hot_rank": loop.run_in_executor(None, self._fetch_hot_rank),
            "xq_follow": loop.run_in_executor(None, self._fetch_xq_follow),
            "xq_tweet": loop.run_in_executor(None, self._fetch_xq_tweet),
            "comment": loop.run_in_executor(None, self._fetch_comment),
            "lhb_detail": loop.run_in_executor(None, self._fetch_lhb_detail),
            "lhb_inst": loop.run_in_executor(None, self._fetch_lhb_inst),
            "margin": loop.run_in_executor(None, self._fetch_margin_total),
        }

        results = {}
        for key, task in tasks.items():
            try:
                results[key] = await asyncio.wait_for(task, timeout=60)
            except Exception as e:
                logger.warning("采集 %s 失败: %s", key, e)
                results[key] = []

        self._hot_rank_cache = results.get("hot_rank", [])
        self._xq_follow_cache = results.get("xq_follow", [])
        self._xq_tweet_cache = results.get("xq_tweet", [])
        self._comment_cache = results.get("comment", [])
        self._lhb_detail_cache = results.get("lhb_detail", [])
        self._lhb_inst_cache = results.get("lhb_inst", [])
        self._margin_total_cache = results.get("margin", [])
        self._last_collect_time = _bj_now_str()

        snapshot.update(results)
        snapshot["enriched"] = enriched_data or []

        logger.info(
            "博弈数据采集完成: 人气排名=%d, 雪球关注=%d, 雪球讨论=%d, "
            "千股千评=%d, 龙虎榜=%d, 机构统计=%d, 融资融券=%d",
            len(self._hot_rank_cache), len(self._xq_follow_cache),
            len(self._xq_tweet_cache), len(self._comment_cache),
            len(self._lhb_detail_cache), len(self._lhb_inst_cache),
            len(self._margin_total_cache),
        )
        return snapshot

    def _fetch_hot_rank(self) -> list[dict]:
        # 1. 优先直连东财人气榜接口 (毫秒级响应、不被限流)
        try:
            import httpx
            url = "https://emappdata.eastmoney.com/stockrank/getAllCurrentList"
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Content-Type": "application/json",
            }
            payload = {"appId": "appId01", "globalId": "786e4c21-70dc-435a-93bb-38", "pageNo": 1, "pageSize": 100}
            with httpx.Client(timeout=8.0) as client:
                r = client.post(url, json=payload, headers=headers)
                if r.status_code == 200:
                    data = r.json()
                    items = data.get("data") or []
                    if items:
                        rows = []
                        for it in items:
                            sc = str(it.get("sc", ""))
                            rk = int(it.get("rk", 0))
                            rows.append({
                                "rank": rk,
                                "code": sc,
                                "symbol": self._xq_to_symbol(sc),
                                "name": "",
                                "close": 0.0,
                                "change_pct": 0.0,
                            })
                        return rows
        except Exception as e:
            logger.debug("直连东财人气榜接口失败，降级至AKShare: %s", e)

        # 2. 备选：AKShare
        try:
            import akshare as ak
            df = ak.stock_hot_rank_em()
            if df is not None and not df.empty:
                rows = []
                for _, r in df.iterrows():
                    code = str(r.get("代码", ""))
                    rows.append({
                        "rank": int(r.get("当前排名", 0)),
                        "code": code, "symbol": self._to_symbol(code),
                        "name": str(r.get("股票名称", "")),
                        "close": _safe_float(r.get("最新价")),
                        "change_pct": _safe_float(r.get("涨跌幅")),
                    })
                return rows
        except Exception as e:
            logger.warning("东财人气排名采集失败: %s", e)
        return []

    def _fetch_xq_follow(self) -> list[dict]:
        try:
            import akshare as ak
            df = ak.stock_hot_follow_xq(symbol="最热门")
            rows = []
            for _, r in df.iterrows():
                code = str(r.get("股票代码", ""))
                rows.append({
                    "code": code, "symbol": self._xq_to_symbol(code),
                    "name": str(r.get("股票简称", "")),
                    "follow_count": int(_safe_float(r.get("关注", 0))),
                })
            return rows
        except Exception as e:
            logger.warning("雪球关注排行采集失败: %s", e)
            return []

    def _fetch_xq_tweet(self) -> list[dict]:
        try:
            import akshare as ak
            df = ak.stock_hot_tweet_xq(symbol="最热门")
            rows = []
            for _, r in df.iterrows():
                code = str(r.get("股票代码", ""))
                rows.append({
                    "code": code, "symbol": self._xq_to_symbol(code),
                    "name": str(r.get("股票简称", "")),
                    "tweet_count": int(_safe_float(r.get("关注", 0))),
                })
            return rows
        except Exception as e:
            logger.warning("雪球讨论排行采集失败: %s", e)
            return []

    def _fetch_comment(self) -> list[dict]:
        try:
            import akshare as ak
            df = ak.stock_comment_em()
            rows = []
            for _, r in df.iterrows():
                code = str(r.get("代码", "")).zfill(6)
                rows.append({
                    "code": code, "symbol": self._to_symbol(code),
                    "name": str(r.get("名称", "")),
                    "close": _safe_float(r.get("最新价")),
                    "change_pct": _safe_float(r.get("涨跌幅")),
                    "turnover_rate": _safe_float(r.get("换手率")),
                    "pe_ratio": _safe_float(r.get("市盈率")),
                    "main_cost": _safe_float(r.get("主力成本")),
                    "inst_participation": _safe_float(r.get("机构参与度")),
                    "composite_score": _safe_float(r.get("综合得分")),
                    "rank_change": _safe_float(r.get("上升")),
                    "current_rank": int(_safe_float(r.get("目前排名", 0))),
                    "attention_index": _safe_float(r.get("关注指数")),
                })
            return rows
        except Exception as e:
            logger.warning("东财千股千评采集失败: %s", e)
            return []

    def _fetch_lhb_detail(self) -> list[dict]:
        # 优先使用智兔 API 高速龙虎榜
        try:
            from app.services.longhubang_service import lhb_service
            daily = lhb_service.get_daily_lhb()
            stocks = daily.get("all_stocks", [])
            if stocks:
                rows = []
                for s in stocks:
                    rows.append({
                        "code": s.get("code", ""),
                        "symbol": s.get("symbol", ""),
                        "name": s.get("name", ""),
                        "date": daily.get("date", ""),
                        "interpretation": ", ".join(s.get("reasons", [])),
                        "close": _safe_float(s.get("close")),
                        "change_pct": _safe_float(s.get("change_pct")),
                        "net_amount": _safe_float(s.get("amount")),
                        "buy_amount": _safe_float(s.get("amount")),
                        "sell_amount": 0.0,
                        "total_amount": _safe_float(s.get("amount")),
                        "turnover_rate": 0.0,
                        "float_mv": 0.0,
                        "reason": ", ".join(s.get("reasons", [])),
                    })
                return rows
        except Exception as e:
            logger.debug("智兔龙虎榜获取失败: %s", e)

        # 备选：AKShare
        try:
            import akshare as ak
            for offset in [0, 1, 2]:
                target = (_bj_now().date() - timedelta(days=offset)).strftime("%Y%m%d")
                try:
                    df = ak.stock_lhb_detail_em(start_date=target, end_date=target)
                    if df is not None and not df.empty:
                        rows = []
                        for _, r in df.iterrows():
                            code = str(r.get("代码", "")).zfill(6)
                            rows.append({
                                "code": code, "symbol": self._to_symbol(code),
                                "name": str(r.get("名称", "")),
                                "date": str(r.get("上榜日", "")),
                                "interpretation": str(r.get("解读", "")),
                                "close": _safe_float(r.get("收盘价")),
                                "change_pct": _safe_float(r.get("涨跌幅")),
                                "net_amount": _safe_float(r.get("龙虎榜净买额")),
                                "buy_amount": _safe_float(r.get("龙虎榜买入额")),
                                "sell_amount": _safe_float(r.get("龙虎榜卖出额")),
                                "total_amount": _safe_float(r.get("龙虎榜成交额")),
                                "turnover_rate": _safe_float(r.get("换手率")),
                                "float_mv": _safe_float(r.get("流通市值")),
                                "reason": str(r.get("上榜原因", "")),
                            })
                        return rows
                except Exception:
                    continue
        except Exception as e:
            logger.warning("龙虎榜明细采集失败: %s", e)
        return []

    def _fetch_lhb_inst(self) -> list[dict]:
        # 优先使用智兔 API 机构席位追踪 (近5日)
        try:
            from app.services.longhubang_service import lhb_service
            insts = lhb_service.get_institution_stats(days=5)
            if insts:
                rows = []
                for r in insts:
                    rows.append({
                        "code": r.get("code", ""),
                        "symbol": r.get("symbol", ""),
                        "name": r.get("name", ""),
                        "close": 0.0,
                        "change_pct": 0.0,
                        "lhb_total_amount": 0.0,
                        "count": r.get("buy_count", 0) + r.get("sell_count", 0),
                        "inst_buy_amount": _safe_float(r.get("buy_amount", 0)) * 10000,   # 统一为元
                        "inst_buy_count": int(r.get("buy_count", 0)),
                        "inst_sell_amount": _safe_float(r.get("sell_amount", 0)) * 10000, # 统一为元
                        "inst_sell_count": int(r.get("sell_count", 0)),
                        "inst_net_amount": _safe_float(r.get("net_amount", 0)) * 10000,   # 统一为元
                    })
                return rows
        except Exception as e:
            logger.debug("智兔机构追踪获取失败: %s", e)

        # 备选：AKShare 近一月机构统计
        try:
            import akshare as ak
            df = ak.stock_lhb_jgstatistic_em(symbol="近一月")
            if df is not None and not df.empty:
                rows = []
                for _, r in df.iterrows():
                    code = str(r.get("代码", "")).zfill(6)
                    rows.append({
                        "code": code, "symbol": self._to_symbol(code),
                        "name": str(r.get("名称", "")),
                        "close": _safe_float(r.get("收盘价")),
                        "change_pct": _safe_float(r.get("涨跌幅")),
                        "lhb_total_amount": _safe_float(r.get("龙虎榜成交金额")),
                        "count": int(_safe_float(r.get("上榜次数", 0))),
                        "inst_buy_amount": _safe_float(r.get("机构买入额")),
                        "inst_buy_count": int(_safe_float(r.get("机构买入次数", 0))),
                        "inst_sell_amount": _safe_float(r.get("机构卖出额")),
                        "inst_sell_count": int(_safe_float(r.get("机构卖出次数", 0))),
                        "inst_net_amount": _safe_float(r.get("机构净买额")),
                    })
                return rows
        except Exception as e:
            logger.warning("龙虎榜机构统计采集失败: %s", e)
        return []

    def _fetch_margin_total(self) -> list[dict]:
        try:
            import akshare as ak
            end = _bj_today_str().replace("-", "")
            start = (_bj_now().date() - timedelta(days=10)).strftime("%Y%m%d")
            df = ak.stock_margin_sse(start_date=start, end_date=end)
            rows = []
            for _, r in df.iterrows():
                rows.append({
                    "date": str(r.get("信用交易日期", "")),
                    "margin_balance": _safe_float(r.get("融资余额")),
                    "margin_buy": _safe_float(r.get("融资买入额")),
                    "short_balance": _safe_float(r.get("融券余量金额")),
                    "short_sell": _safe_float(r.get("融券卖出量")),
                    "total_balance": _safe_float(r.get("融资融券余额")),
                })
            return rows
        except Exception as e:
            logger.warning("融资融券采集失败: %s", e)
            return []

    @staticmethod
    def _to_symbol(code: str) -> str:
        code = str(code).strip()
        if code.startswith(("SH", "SZ")):
            code = code[2:]
        code = code.zfill(6)
        if code.startswith(("60", "68", "90")):
            return f"{code}.SH"
        if code.startswith(("00", "30", "20")):
            return f"{code}.SZ"
        if code.startswith(("43", "83", "87", "92")):
            return f"{code}.BJ"
        return code

    @staticmethod
    def _xq_to_symbol(code: str) -> str:
        code = str(code).strip()
        if code.startswith("SH"):
            return f"{code[2:]}.SH"
        if code.startswith("SZ"):
            return f"{code[2:]}.SZ"
        return code


# ═══════════════════════════════════════════════════════════════════
# GameTheoryScorer — 个股博弈评分引擎
# ═══════════════════════════════════════════════════════════════════

class GameTheoryScorer:
    """对每只股票计算散户恐惧指数与拥挤指数"""

    def score_all(self, snapshot: dict[str, Any]) -> list[StockGameScore]:
        hot_rank_map = {r["symbol"]: r for r in snapshot.get("hot_rank", [])}
        xq_follow_map = {r["symbol"]: r for r in snapshot.get("xq_follow", [])}
        xq_tweet_map = {r["symbol"]: r for r in snapshot.get("xq_tweet", [])}
        comment_map = {r["symbol"]: r for r in snapshot.get("comment", [])}
        lhb_map = {r["symbol"]: r for r in snapshot.get("lhb_detail", [])}
        lhb_inst_map = {r["symbol"]: r for r in snapshot.get("lhb_inst", [])}

        margin_data = snapshot.get("margin", [])
        margin_change_pct = 0.0
        if len(margin_data) >= 2:
            latest = _safe_float(margin_data[-1].get("margin_balance", 0))
            prev = _safe_float(margin_data[-2].get("margin_balance", 0))
            if prev > 0:
                margin_change_pct = (latest - prev) / prev * 100

        hot_rank_top20 = set()
        hot_rank_top50 = set()
        for r in snapshot.get("hot_rank", [])[:50]:
            sym = r.get("symbol", "")
            rank = r.get("rank", 999)
            if rank <= 20:
                hot_rank_top20.add(sym)
            if rank <= 50:
                hot_rank_top50.add(sym)

        xq_tweet_top = set()
        for r in snapshot.get("xq_tweet", [])[:30]:
            xq_tweet_top.add(r.get("symbol", ""))

        enriched_map: dict[str, dict] = {}
        for r in snapshot.get("enriched", []):
            sym = r.get("symbol", "")
            if sym:
                enriched_map[sym] = r

        all_symbols: set[str] = set()
        for src in [hot_rank_map, xq_follow_map, xq_tweet_map, comment_map, lhb_map, lhb_inst_map, enriched_map]:
            all_symbols.update(src.keys())

        scores: list[StockGameScore] = []
        for sym in all_symbols:
            if not sym or "." not in sym:
                continue
            score = self._score_stock(
                sym, hot_rank_map, xq_follow_map, xq_tweet_map,
                comment_map, lhb_map, lhb_inst_map, enriched_map,
                hot_rank_top20, hot_rank_top50, xq_tweet_top, margin_change_pct,
            )
            if score:
                scores.append(score)
        return scores

    def _score_stock(
        self, symbol: str,
        hot_rank_map: dict, xq_follow_map: dict, xq_tweet_map: dict,
        comment_map: dict, lhb_map: dict, lhb_inst_map: dict, enriched_map: dict,
        hot_rank_top20: set, hot_rank_top50: set, xq_tweet_top: set,
        margin_change_pct: float,
    ) -> Optional[StockGameScore]:
        hr = hot_rank_map.get(symbol, {})
        xf = xq_follow_map.get(symbol, {})
        xt = xq_tweet_map.get(symbol, {})
        cm = comment_map.get(symbol, {})
        lhb = lhb_map.get(symbol, {})
        lhb_i = lhb_inst_map.get(symbol, {})
        enr = enriched_map.get(symbol, {})

        name = hr.get("name") or cm.get("name") or lhb.get("name") or enr.get("name", "")
        if not name:
            return None

        # 核心行情与技术指标提取
        close = _safe_float(enr.get("close") or hr.get("close") or cm.get("close"))
        open_val = _safe_float(enr.get("open") or close)
        high_val = _safe_float(enr.get("high") or close)
        low_val = _safe_float(enr.get("low") or close)
        change_pct = _safe_float(enr.get("change_pct") or hr.get("change_pct") or cm.get("change_pct"))
        if abs(change_pct) < 0.2:  # 如果是小数形式 (如 0.05 代表 5%)
            change_pct_pct = change_pct * 100
        else:
            change_pct_pct = change_pct

        amplitude = _safe_float(enr.get("amplitude"))
        turnover_rate = _safe_float(cm.get("turnover_rate") or enr.get("turnover_rate"))
        vol_ratio = _safe_float(enr.get("vol_ratio_5d", 1.0))
        amount = _safe_float(enr.get("amount", 0.0))
        ma20 = _safe_float(enr.get("ma20", 0.0))
        ma60 = _safe_float(enr.get("ma60", 0.0))
        kdj_j = _safe_float(enr.get("kdj_j", 50.0))
        rsi_6 = _safe_float(enr.get("rsi_6", 50.0))
        macd_hist = _safe_float(enr.get("macd_hist", 0.0))

        # 排除完全无资金关注的死水僵尸股 (成交额小于 2000万 且换手极低且振幅极小)
        if amount > 0 and amount < 20_000_000 and turnover_rate < 0.8 and amplitude < 0.02:
            return None

        score = StockGameScore(symbol=symbol, name=name, close=close, change_pct=change_pct_pct)
        score.turnover_rate = turnover_rate
        score.vol_ratio_5d = vol_ratio
        score.amount = amount
        score.amplitude = amplitude * 100 if amplitude < 1.0 else amplitude
        score.kdj_j = kdj_j
        score.rsi_6 = rsi_6
        score.macd_hist = macd_hist
        score.attention_index = _safe_float(cm.get("attention_index"))
        score.inst_participation = _safe_float(cm.get("inst_participation"))

        reasons_fear: list[str] = []
        reasons_greed: list[str] = []

        hl_span = high_val - low_val

        # ═══════════════════════════════════════════════════════════════
        # 🥶 恐惧面：散户看指标恐慌割肉 = 主力诱空挖坑吃筹（绝佳好位置）
        # ═══════════════════════════════════════════════════════════════

        # 1. 【反指标诱空 · 假破位诱空挖坑】(权重 30分)
        # 散户心理: 跌破20日线或60日线时，技术派散户教科书式止损盘狂涌割肉！
        # 主力动作: 盘中故意砸穿支撑逼出止损单，随后大单在低位扫货收复，或留长下影线。
        if ma20 > 0 and low_val > 0:
            broke_ma20 = (low_val < ma20) and (close >= ma20 * 0.985)
            recovered = (close > low_val * 1.012)
            if broke_ma20 and recovered:
                score.ma_breakdown_trap_score = 30
                reasons_fear.append("跌破MA20诱空洗盘(技术派散户止损割肉，主力低位收复)")
            elif low_val < ma20 and close >= ma20 * 0.97:
                score.ma_breakdown_trap_score = 15
                reasons_fear.append("MA20生命线假摔诱空测试")

        # 2. 【反指标模式 · KDJ 极度恐慌超卖区】(权重 25分)
        # 散户心理: KDJ J线跌入负值或个位数，RSI极度冰点，散户心态彻底崩溃，以为深不见底割在最底部！
        # 主力动作: 恐慌宣泄达到极致，空头动能衰竭，主力准备随时点火暴力反弹。
        if kdj_j <= 5.0 or rsi_6 <= 26.0:
            if kdj_j <= 0.0:
                score.kdj_panic_score = 25
                reasons_fear.append(f"KDJ极端恐慌超卖(J={kdj_j:.1f}跌入负值)，散户绝望割肉不敢买")
            elif kdj_j <= 5.0:
                score.kdj_panic_score = 20
                reasons_fear.append(f"KDJ极度恐慌超卖(J={kdj_j:.1f})，散户恐慌不敢买的好位置")
            elif rsi_6 <= 26.0:
                score.kdj_panic_score = 15
                reasons_fear.append(f"RSI短线恐慌超跌(RSI={rsi_6:.1f})")

        # 3. 【恐慌砸盘探底神针 / 日内大跳水通吃割肉盘】(权重 25分)
        # 散户心理: 日内大幅跳水(-3%~-6%)，散户以为要奔跌停仓皇割肉。
        # 主力动作: 盘中急跌诱发恐慌踩踏，随后主力大单逆势通吃恐慌盘拉起，留下长长下影线。
        if hl_span > 0 and (score.amplitude >= 3.5 or amplitude >= 0.035):
            lower_shadow = close - low_val
            shadow_ratio = lower_shadow / hl_span
            if shadow_ratio >= 0.55 and close >= open_val * 0.985:
                score.panic_pinbar_score = 25
                reasons_fear.append(f"日内恐慌砸盘探底神针(长下影占{int(shadow_ratio*100)}%)，恐慌盘被主力通吃")
            elif shadow_ratio >= 0.40:
                score.panic_pinbar_score = 15
                reasons_fear.append(f"日内探底回升长下影(下影占{int(shadow_ratio*100)}%)，恐慌盘被吸收")

        # 4. 【反指标诱空 · MACD 水下洗盘假死叉】(权重 20分)
        # 散户心理: 教科书死记“MACD死叉必跌”，散户一见死叉慌忙挂单抛售。
        # 主力动作: 在洗盘末端故意划出微幅死叉骗线，股价缩量抗跌不深跌，吃掉死叉割肉盘。
        if -0.20 < macd_hist < 0.0:
            if vol_ratio <= 0.85 and abs(change_pct) < 0.025:
                score.macd_dead_trap_score = 20
                reasons_fear.append("反指标MACD假死叉诱空(散户看死叉割肉，主力缩量抵抗收筹)")
            elif vol_ratio <= 1.0:
                score.macd_dead_trap_score = 10
                reasons_fear.append("MACD死叉诱空坑")

        # 5. 【洗盘衰竭缩至地量 / 浮筹出清】(权重 15分)
        if 0 < vol_ratio <= 0.55 and (amount >= 25_000_000 or turnover_rate >= 1.0):
            score.vol_shrink_score = 15
            reasons_fear.append("洗盘缩至5日地量(散户浮筹洗净，主力随时点火)")

        # 6. 【龙虎榜机构逆向吞并散户恐慌盘】(权重 20分)
        inst_net = _safe_float(lhb_i.get("inst_net_amount", 0))
        score.inst_net_amount = inst_net
        if inst_net > 0:
            inst_net_wan = inst_net / 10000 if inst_net > 100000 else inst_net
            if inst_net_wan > 3000:
                score.inst_buy_score = 20
                reasons_fear.append(f"散户恐慌割肉，龙虎榜机构逆势扫货{inst_net_wan/10000:.1f}亿")
            elif inst_net_wan > 1000:
                score.inst_buy_score = 12
                reasons_fear.append(f"散户恐慌抛售，机构逆势净买入{inst_net_wan:.0f}万")

        # 7. 散户关注度与人气盲区
        hot_rank_val = int(hr.get("rank", 0))
        score.hot_rank = hot_rank_val
        if hot_rank_val == 0:
            score.hot_rank_cold_score = 10
        elif hot_rank_val > 200:
            score.hot_rank_cold_score = 5

        xq_tweet_val = int(xt.get("tweet_count", 0))
        score.xq_tweet = xq_tweet_val
        score.xq_follow = int(xf.get("follow_count", 0))

        score.fear_index = min(100, (
            score.ma_breakdown_trap_score
            + score.kdj_panic_score
            + score.panic_pinbar_score
            + score.macd_dead_trap_score
            + score.vol_shrink_score
            + score.inst_buy_score
            + score.hot_rank_cold_score
        ))

        # ═══════════════════════════════════════════════════════════════
        # 🔥 贪婪面：散户看指标追高扎堆 = 主力诱多出货（极度危险区）
        # ═══════════════════════════════════════════════════════════════

        # 1. 【高位 MACD 假金叉诱多出货】(权重 25分)
        if macd_hist > 0 and macd_hist < 0.25 and turnover_rate > 15:
            if hl_span > 0 and (close - low_val) / hl_span < 0.45 and (score.amplitude >= 4.0 or amplitude >= 0.04):
                score.bull_trap_score = 25
                reasons_greed.append("高位MACD金叉诱多冲高回落，散户看指标追涨高位接盘")
            else:
                score.bull_trap_score = 15
                reasons_greed.append("高位MACD金叉诱多")

        # 2. 【KDJ 极度超买高潮】(权重 20分)
        if kdj_j >= 95.0:
            score.kdj_greed_score = 20
            reasons_greed.append(f"KDJ极度超买高潮(J={kdj_j:.1f})，散户亢奋追涨随时大跳水")
        elif kdj_j >= 85.0:
            score.kdj_greed_score = 10

        # 3. 【假突破长上影诱多】(权重 20分)
        if hl_span > 0 and (score.amplitude >= 4.5 or amplitude >= 0.045):
            upper_shadow = high_val - max(open_val, close)
            if upper_shadow / hl_span >= 0.50:
                score.breakout_trap_score = 20
                reasons_greed.append("假突破诱多收长上影，散户看阳线追高被套山顶")

        # 4. 【东财人气榜飙升 + 换手率狂热】(权重 25分)
        if symbol in hot_rank_top20 and turnover_rate > 18:
            score.hot_rank_surge_score = 25
            reasons_greed.append(f"东财人气Top{hot_rank_val}散户蜂拥扎堆，换手率高达{turnover_rate:.1f}%")
        elif symbol in hot_rank_top50 and turnover_rate > 12:
            score.hot_rank_surge_score = 15
            reasons_greed.append(f"东财人气Top{hot_rank_val}散户追逐高换手")

        # 5. 【雪球舆论发酵狂热】(权重 20分)
        if xq_tweet_val > 50000:
            score.xq_tweet_surge_score = 20
            reasons_greed.append(f"雪球讨论量{xq_tweet_val}(舆论发酵)")
        elif xq_tweet_val > 20000:
            score.xq_tweet_surge_score = 15
        elif xq_tweet_val > 5000:
            score.xq_tweet_surge_score = 8

        if turnover_rate > 25:
            score.turnover_hot_score = 15
            reasons_greed.append(f"换手率{turnover_rate:.1f}%(筹码剧烈换手)")
        elif turnover_rate > 15:
            score.turnover_hot_score = 10
        elif turnover_rate > 10:
            score.turnover_hot_score = 5

        if margin_change_pct > 0.5:
            score.margin_increase_score = 15
        elif margin_change_pct > 0.2:
            score.margin_increase_score = 10
        elif margin_change_pct > 0:
            score.margin_increase_score = 5

        if inst_net < 0:
            inst_net_abs = abs(inst_net)
            inst_abs_wan = inst_net_abs / 10000 if inst_net_abs > 100000 else inst_net_abs
            if inst_abs_wan > 5000:
                score.inst_sell_score = 15
                reasons_greed.append(f"龙虎榜机构净卖出{inst_abs_wan/10000:.1f}亿(主力出逃)")
            elif inst_abs_wan > 2000:
                score.inst_sell_score = 10
            elif inst_abs_wan > 0:
                score.inst_sell_score = 5

        if vol_ratio >= 2.0 and abs(change_pct) < 2.0:
            score.vol_spike_no_gain_score = 10
            reasons_greed.append(f"天量({vol_ratio:.1f}x)滞涨(涨幅仅{change_pct:.1f}%)")
        elif vol_ratio >= 1.5 and abs(change_pct) < 1.5:
            score.vol_spike_no_gain_score = 5

        score.margin_change_pct = margin_change_pct
        score.greed_index = min(100, (
            score.hot_rank_surge_score + score.xq_tweet_surge_score + score.turnover_hot_score
            + score.margin_increase_score + score.inst_sell_score + score.vol_spike_no_gain_score
        ))

        score.signal_reasons = reasons_fear + reasons_greed
        if score.fear_index >= 70 and score.greed_index <= 20:
            score.game_signal = "strong_buy"
        elif score.fear_index >= 50 and score.greed_index <= 30:
            score.game_signal = "buy"
        elif score.greed_index >= 70 and score.fear_index <= 20:
            score.game_signal = "danger"
        elif score.greed_index >= 50 and score.fear_index <= 30:
            score.game_signal = "caution"
        else:
            score.game_signal = "neutral"
        return score


# ═══════════════════════════════════════════════════════════════════
# MarketGameThermometer — 全市场温度计
# ═══════════════════════════════════════════════════════════════════

class MarketGameThermometer:
    ZONES = [
        (15, "ice", "🥶 极寒冰点"),
        (30, "cold", "❄️ 偏冷谨慎"),
        (55, "warm", "🌤️ 温和适中"),
        (75, "hot", "🔥 偏热警惕"),
        (100, "boiling", "🌋 极热沸腾"),
    ]

    def compute(self, snapshot: dict[str, Any], scores: list[StockGameScore],
                market_overview: Optional[dict] = None) -> MarketTemperature:
        temp = MarketTemperature(date=_bj_today_str(), updated_at=_bj_now_str())

        if market_overview:
            limit_up = market_overview.get("limit_up_count", 0)
            seal_rate = _safe_float(market_overview.get("seal_rate", 0.5))
            temp.limit_up_count = limit_up
            temp.seal_rate = seal_rate
            temp.limit_up_score = self._scale(limit_up, 20, 120) * 0.6 + self._scale(seal_rate * 100, 40, 80) * 0.4
            temp.limit_down_count = market_overview.get("limit_down_count", 0)
        else:
            temp.limit_up_score = 50

        max_consec = market_overview.get("max_consecutive", 0) if market_overview else 0
        temp.max_consecutive = max_consec
        temp.consecutive_score = self._scale(max_consec, 2, 8)

        margin_data = snapshot.get("margin", [])
        if len(margin_data) >= 2:
            latest = _safe_float(margin_data[-1].get("margin_balance", 0))
            prev = _safe_float(margin_data[-2].get("margin_balance", 0))
            if prev > 0:
                change_pct = (latest - prev) / prev * 100
                temp.margin_total = latest
                temp.margin_change = change_pct
                temp.margin_score = self._scale(change_pct, -0.5, 0.5)
        else:
            temp.margin_score = 50

        inst_data = snapshot.get("lhb_inst", [])
        total_inst_net = sum(_safe_float(r.get("inst_net_amount", 0)) for r in inst_data)
        temp.inst_net_total = total_inst_net
        temp.lhb_inst_score = self._scale(-total_inst_net / 1e8, -5, 5)

        hot_rank = snapshot.get("hot_rank", [])
        if hot_rank:
            top20_symbols = set(r.get("symbol", "") for r in hot_rank[:20])
            top20_turnovers = [s.turnover_rate for s in scores if s.symbol in top20_symbols and s.turnover_rate > 0]
            if top20_turnovers:
                avg_turnover = sum(top20_turnovers) / len(top20_turnovers)
                temp.crowd_score = self._scale(avg_turnover, 3, 20)
            else:
                temp.crowd_score = 50
        else:
            temp.crowd_score = 50

        temp.temperature = round(
            temp.limit_up_score * 0.25 + temp.consecutive_score * 0.15
            + temp.margin_score * 0.20 + temp.lhb_inst_score * 0.20
            + temp.crowd_score * 0.20, 1)
        temp.temperature = max(0, min(100, temp.temperature))

        for threshold, zone, label in self.ZONES:
            if temp.temperature <= threshold:
                temp.zone = zone
                temp.zone_label = label
                break
        return temp

    @staticmethod
    def _scale(value: float, low: float, high: float) -> float:
        if high <= low:
            return 50.0
        return max(0, min(100, (value - low) / (high - low) * 100))


# ═══════════════════════════════════════════════════════════════════
# GameTheoryAIAnalyst — AI 博弈解读
# ═══════════════════════════════════════════════════════════════════

class GameTheoryAIAnalyst:
    async def generate_report(self, temperature: MarketTemperature,
                              fear_pool: list[StockGameScore], danger_list: list[StockGameScore],
                              snapshot: dict[str, Any]) -> GameTheoryReport:
        report = GameTheoryReport(
            date=_bj_today_str(), temperature=temperature.temperature,
            zone=temperature.zone, updated_at=_bj_now_str(),
        )
        report.fear_pool = [asdict(s) for s in fear_pool[:8]]
        report.danger_list = [asdict(s) for s in danger_list[:8]]

        fear_text = "\n".join(
            f"  {i+1}. {s.name}({s.symbol}) 恐惧指数={s.fear_index} 信号={', '.join(s.signal_reasons[:3])}"
            for i, s in enumerate(fear_pool[:5])
        )
        danger_text = "\n".join(
            f"  {i+1}. {s.name}({s.symbol}) 拥挤指数={s.greed_index} 信号={', '.join(s.signal_reasons[:3])}"
            for i, s in enumerate(danger_list[:5])
        )

        system_prompt = """你是一位精通散户行为博弈论的A股首席策略师。
你的核心信念：不预测市场方向，只分析「人」—— 散户扎堆=危险，散户恐慌=机会。
请基于以下博弈数据，输出严格 JSON（不含 markdown 代码块）：
{
  "market_summary": "今日市场博弈格局总结（80-120字，分析散户情绪偏恐惧还是贪婪，机构资金在做什么）",
  "strategy_advice": "明日博弈策略建议（80-120字，应该关注恐惧区的什么方向，规避拥挤区的什么方向）"
}"""

        user_prompt = f"""【市场博弈温度】{temperature.temperature}° ({temperature.zone_label})
涨停={temperature.limit_up_count}家, 跌停={temperature.limit_down_count}家, 封板率={temperature.seal_rate*100:.0f}%, 连板高度={temperature.max_consecutive}
融资余额变化={temperature.margin_change:+.2f}%, 龙虎榜机构净额={temperature.inst_net_total/10000:.0f}万

【散户恐惧区 · 潜在机会池】:
{fear_text or '  暂无突出标的'}

【散户拥挤区 · 危险信号】:
{danger_text or '  暂无突出标的'}"""

        try:
            from app.services.ai_provider import generate_ai_text
            import re as _re
            raw = await generate_ai_text(
                [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                temperature=0.3, max_tokens=1000,
            )
            match = _re.search(r"\{.*\}", raw, _re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
                report.market_summary = parsed.get("market_summary", "")
                report.strategy_advice = parsed.get("strategy_advice", "")
        except Exception as e:
            logger.warning("AI 博弈报告生成失败: %s", e)

        if not report.market_summary:
            report.market_summary = self._fallback_summary(temperature)
        if not report.strategy_advice:
            report.strategy_advice = self._fallback_advice(temperature)
        return report

    def _fallback_summary(self, temp: MarketTemperature) -> str:
        if temp.temperature >= 70:
            return f"市场散户情绪偏热({temp.temperature:.0f}°)，涨停{temp.limit_up_count}家、连板高度{temp.max_consecutive}板，人气股换手率偏高，散户追涨意愿强烈。龙虎榜机构整体呈净卖出态势，需警惕高位派发风险。"
        elif temp.temperature <= 30:
            return f"市场散户情绪偏冷({temp.temperature:.0f}°)，涨停仅{temp.limit_up_count}家，成交量整体萎缩。散户参与意愿低迷，但龙虎榜显示部分机构在低位逆向吸筹，恐惧区存在博弈机会。"
        return f"市场散户情绪温和({temp.temperature:.0f}°)，涨停{temp.limit_up_count}家，结构性分化明显。部分板块散户拥挤度偏高需注意，同时低位缩量蓄势股有机构资金介入。"

    def _fallback_advice(self, temp: MarketTemperature) -> str:
        if temp.temperature >= 70:
            return "散户情绪偏热，宜降低仓位，回避人气排名Top20且换手率>15%的过热股。优先关注恐惧区的地量蓄势标的，等待散户恐慌后的错杀机会。"
        elif temp.temperature <= 30:
            return "散户恐慌情绪蔓延，反而是博弈买入的好时机。重点关注恐惧区中有机构逆向买入的低位缩量股，在竞价确认主力意图后果断介入。"
        return "市场情绪适中，可适度参与博弈。关注恐惧区中机构参与度提升的标的，同时严格回避拥挤区高换手率、高人气但业绩空洞的题材股。"


# ═══════════════════════════════════════════════════════════════════
# GameTheoryEngine — 引擎总控
# ═══════════════════════════════════════════════════════════════════

class GameTheoryEngine:
    def __init__(self, data_dir: Optional[Path] = None, repo: Optional[Any] = None):
        self.data_dir = data_dir or Path("data")
        self.repo = repo
        self._report_file = self.data_dir / "user_data" / "game_theory_report.json"
        self._history_file = self.data_dir / "user_data" / "game_theory_history.json"
        self._scores_file = self.data_dir / "user_data" / "game_theory_scores.json"
        self._status_file = self.data_dir / "user_data" / "game_theory_status.json"
        self.collector = GameTheoryCollector()
        self.scorer = GameTheoryScorer()
        self.thermometer = MarketGameThermometer()
        self.ai_analyst = GameTheoryAIAnalyst()
        self._latest_report: Optional[GameTheoryReport] = None
        self._latest_temperature: Optional[MarketTemperature] = None
        self._latest_scores: list[StockGameScore] = []
        self._is_running: bool = False
        self._last_run_time: str = ""
        self._load_persisted()

    def _get_enriched_records(self) -> list[dict]:
        try:
            if self.repo is None:
                from app.tickflow.repository import DataStore, KlineRepository
                store = DataStore(data_dir=self.data_dir)
                self.repo = KlineRepository(store)
            df, _ = self.repo.get_enriched_latest_asset("stock")
            if df is not None:
                name_map = self.repo.get_name_map() if hasattr(self.repo, "get_name_map") else {}
                records = df.to_dicts()
                for r in records:
                    sym = r.get("symbol", "")
                    if not r.get("name") and sym in name_map:
                        r["name"] = name_map[sym]
                return records
        except Exception as e:
            logger.warning("获取 enriched 历史指标数据失败: %s", e)
        return []

    def _load_persisted(self) -> None:
        try:
            if self._report_file.exists():
                data = json.loads(self._report_file.read_text(encoding="utf-8"))
                self._latest_report = GameTheoryReport(**{
                    k: v for k, v in data.items() if k in GameTheoryReport.__dataclass_fields__
                })
                self._latest_temperature = MarketTemperature(
                    temperature=data.get("temperature", 50), zone=data.get("zone", "warm"),
                )
        except Exception as e:
            logger.debug("加载博弈报告缓存失败: %s", e)
        try:
            if self._scores_file.exists():
                raw = json.loads(self._scores_file.read_text(encoding="utf-8"))
                self._latest_scores = [
                    StockGameScore(**{k: v for k, v in s.items() if k in StockGameScore.__dataclass_fields__})
                    for s in raw[:300]
                ]
        except Exception as e:
            logger.debug("加载博弈评分缓存失败: %s", e)

    async def run_full_analysis(self, enriched_data: Optional[list[dict]] = None,
                                market_overview: Optional[dict] = None) -> GameTheoryReport:
        if self._is_running:
            logger.warning("博弈分析已在运行中，跳过")
            return self._latest_report or GameTheoryReport(date=_bj_today_str(), updated_at=_bj_now_str())

        self._is_running = True
        try:
            logger.info("🎯 开始博弈派全量分析...")
            if not enriched_data:
                enriched_data = self._get_enriched_records()
                logger.info("已自动加载全市场 Enriched 指标: %d 只标的", len(enriched_data))

            snapshot = await self.collector.collect_all(enriched_data)
            scores = self.scorer.score_all(snapshot)
            logger.info("博弈评分完成: %d 只股票", len(scores))
            temperature = self.thermometer.compute(snapshot, scores, market_overview)
            logger.info("市场温度: %.1f° (%s)", temperature.temperature, temperature.zone_label)

            fear_pool = sorted(
                [s for s in scores if s.fear_index >= 35 and s.greed_index <= 35 and (s.amount >= 20_000_000 or s.turnover_rate >= 1.0)],
                key=lambda s: s.fear_index, reverse=True,
            )
            danger_list = sorted(
                [s for s in scores if s.greed_index >= 35 and s.fear_index <= 35 and (s.amount >= 20_000_000 or s.turnover_rate >= 1.0)],
                key=lambda s: s.greed_index, reverse=True,
            )

            report = await self.ai_analyst.generate_report(temperature, fear_pool, danger_list, snapshot)
            self._latest_report = report
            self._latest_temperature = temperature
            self._latest_scores = scores
            self._last_run_time = _bj_now_str()
            self._persist(report, temperature, scores)

            logger.info("✅ 博弈分析完成: 温度=%.1f° 恐惧池=%d只 危险清单=%d只",
                        temperature.temperature, len(fear_pool), len(danger_list))
            return report
        except Exception as e:
            logger.error("博弈分析异常: %s", e, exc_info=True)
            return self._latest_report or GameTheoryReport(
                date=_bj_today_str(), updated_at=_bj_now_str(),
                market_summary="博弈分析暂时不可用，请稍后重试。",
            )
        finally:
            self._is_running = False

    def _persist(self, report: GameTheoryReport, temp: MarketTemperature, scores: list[StockGameScore]) -> None:
        try:
            self._report_file.parent.mkdir(parents=True, exist_ok=True)
            self._report_file.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("持久化博弈报告失败: %s", e)
        try:
            notable = sorted([s for s in scores if s.fear_index >= 30 or s.greed_index >= 30],
                             key=lambda s: max(s.fear_index, s.greed_index), reverse=True)
            self._scores_file.write_text(
                json.dumps([asdict(s) for s in notable[:300]], ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("持久化博弈评分失败: %s", e)
        try:
            history = []
            if self._history_file.exists():
                history = json.loads(self._history_file.read_text(encoding="utf-8"))
            today = _bj_today_str()
            history = [h for h in history if h.get("date") != today]
            history.append(asdict(temp))
            history = history[-60:]
            self._history_file.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("持久化温度历史失败: %s", e)

    def get_report(self) -> dict:
        if self._latest_report:
            return asdict(self._latest_report)
        return {"date": _bj_today_str(), "updated_at": "", "market_summary": "尚未运行博弈分析"}

    def get_temperature(self) -> dict:
        if self._latest_temperature:
            return asdict(self._latest_temperature)
        return asdict(MarketTemperature(date=_bj_today_str(), updated_at=_bj_now_str()))

    def get_fear_pool(self, limit: int = 20) -> list[dict]:
        pool = sorted(
            [s for s in self._latest_scores if s.fear_index >= 35 and s.greed_index <= 35 and (s.amount >= 20_000_000 or s.turnover_rate >= 1.0)],
            key=lambda s: s.fear_index, reverse=True,
        )
        return [asdict(s) for s in pool[:limit]]

    def get_danger_list(self, limit: int = 20) -> list[dict]:
        danger = sorted(
            [s for s in self._latest_scores if s.greed_index >= 35 and s.fear_index <= 35 and (s.amount >= 20_000_000 or s.turnover_rate >= 1.0)],
            key=lambda s: s.greed_index, reverse=True,
        )
        return [asdict(s) for s in danger[:limit]]

    def get_stock_score(self, symbol: str) -> Optional[dict]:
        for s in self._latest_scores:
            if s.symbol == symbol:
                return asdict(s)
        return None

    def get_temperature_history(self, days: int = 30) -> list[dict]:
        try:
            if self._history_file.exists():
                history = json.loads(self._history_file.read_text(encoding="utf-8"))
                return history[-days:]
        except Exception:
            pass
        return []

    def get_status(self) -> dict:
        return {
            "is_running": self._is_running,
            "last_run_time": self._last_run_time,
            "temperature": self._latest_temperature.temperature if self._latest_temperature else None,
            "zone": self._latest_temperature.zone if self._latest_temperature else None,
            "zone_label": self._latest_temperature.zone_label if self._latest_temperature else None,
            "fear_pool_count": len(self.get_fear_pool(100)),
            "danger_list_count": len(self.get_danger_list(100)),
            "total_scored": len(self._latest_scores),
            "beijing_time": _bj_now_str(),
        }
