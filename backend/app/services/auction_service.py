# -*- coding: utf-8 -*-
"""9:25 集合竞价抢筹选股服务。

筛选规则：
1. 市场范围：全市场 A 股，自动剔除北交所 (.BJ / 43/83/87/92)、ST / *ST 个股、新股 (<30天)；
2. 板块筛选：创业板 (300/301) 和科创板 (688/689) 支持动态勾选包含或排除；
3. 竞价高开：高开幅度 >= 1.5%（可配置区间，如 1.5% ~ 8.0%）；
4. 前一日形态：小阴小阳蓄势（实体振幅 <= 2.5%），若实体 <= 0.8% 标记为「⭐ 极致十字星」；
5. 市值区间：总市值 / 流通市值在 10 亿 ~ 200 亿 之间；
6. 实时联动：9:25 自动调用智兔全市场实时行情计算竞价高开与抢筹评分，并支持历史回溯。
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta
from typing import Any, List, Optional
import polars as pl

from app.parquet import scan_enriched_parquet
from app.tickflow.repository import KlineRepository

logger = logging.getLogger(__name__)


def _classify_board(symbol: str) -> str:
    if symbol.startswith("688") or symbol.startswith("689"):
        return "科创板"
    if symbol.startswith("300") or symbol.startswith("301"):
        return "创业板"
    if symbol.startswith("600") or symbol.startswith("601") or symbol.startswith("603") or symbol.startswith("605") or symbol.endswith(".SH"):
        return "沪主板"
    if symbol.startswith("000") or symbol.startswith("001") or symbol.startswith("002") or symbol.startswith("003") or symbol.endswith(".SZ"):
        return "深主板"
    return "主板"


class AuctionService:
    def __init__(self, repo: KlineRepository) -> None:
        self.repo = repo

    def run_auction_screener(
        self,
        as_of: Optional[date] = None,
        min_gap_pct: float = 1.5,
        max_gap_pct: float = 9.9,
        min_mv: float = 10.0,
        max_mv: float = 200.0,
        max_prev_body_pct: float = 2.5,
        include_chinext: bool = True,
        include_star: bool = True,
        only_doji: bool = False,
        use_realtime: bool = True,
    ) -> dict:
        """执行 9:25 集合竞价抢筹策略选股"""
        t0_start = time.perf_counter()

        enriched_dir = self.repo.store.data_dir / "kline_daily_enriched"
        lf = scan_enriched_parquet(str(enriched_dir / "**" / "*.parquet"))

        # 获取可用交易日
        dates_series = lf.select("date").unique().sort("date").collect()["date"]
        all_dates = [d for d in dates_series.to_list() if isinstance(d, date)]

        if not all_dates:
            return {"as_of": str(as_of or date.today()), "total": 0, "rows": [], "elapsed_ms": 0.0}

        target_date = as_of or all_dates[-1]

        # 确定 T0, T1, T2 日期 (T2 用于计算 T-1 日真实涨跌幅)
        t0_date = target_date
        t1_candidates = [d for d in all_dates if d < t0_date]
        if not t1_candidates:
            t1_date = t0_date
            t2_date = t0_date
        else:
            t1_date = t1_candidates[-1]
            t2_candidates = [d for d in all_dates if d < t1_date]
            t2_date = t2_candidates[-1] if t2_candidates else t1_date

        # 读取 T-1 日与 T-2 日行情
        df_t1 = lf.filter(pl.col("date") == t1_date).collect()
        df_t2 = lf.filter(pl.col("date") == t2_date).collect()
        if df_t1.is_empty():
            return {"as_of": str(t0_date), "t1_date": str(t1_date), "total": 0, "rows": [], "elapsed_ms": 0.0}

        # 尝试读取 T0 实时行情（智兔 / 内存最新）
        df_t0: Optional[pl.DataFrame] = None
        is_live = False

        if use_realtime and (as_of is None or as_of == all_dates[-1] or as_of == date.today()):
            try:
                from app.data_providers import custom as custom_sources
                provider = custom_sources.get_provider("zhitu")
                if provider:
                    records = provider.get_realtime()
                    if records:
                        df_t0 = pl.DataFrame(records)
                        is_live = True
            except Exception as e:
                logger.debug("获取智兔实时竞价行情失败，回退 parquet: %s", e)

        if df_t0 is None or df_t0.is_empty():
            df_t0 = lf.filter(pl.col("date") == t0_date).collect()

        if df_t0.is_empty():
            return {"as_of": str(t0_date), "t1_date": str(t1_date), "total": 0, "rows": [], "elapsed_ms": 0.0}

        # 提取标的维表（用于名称与股本）
        df_inst = self.repo.get_instruments_asset("stock")

        # 统一字段
        if "open" not in df_t0.columns and "last_price" in df_t0.columns:
            df_t0 = df_t0.with_columns(pl.col("last_price").alias("open"))

        cols_t0 = ["symbol", "open", "close", "high", "low", "volume", "amount"]
        avail_t0 = [c for c in cols_t0 if c in df_t0.columns]
        df_t0_sub = df_t0.select(avail_t0)

        t1_cols = [
            "symbol",
            pl.col("open").alias("open_prev"),
            pl.col("close").alias("close_prev"),
            pl.col("high").alias("high_prev"),
            pl.col("low").alias("low_prev"),
            pl.col("volume").alias("volume_prev"),
            pl.col("amount").alias("amount_prev"),
        ]
        if "consecutive_limit_ups" in df_t1.columns:
            t1_cols.append(pl.col("consecutive_limit_ups").alias("consec_limit_ups_prev"))
        if "consecutive_limit_downs" in df_t1.columns:
            t1_cols.append(pl.col("consecutive_limit_downs").alias("consec_limit_downs_prev"))

        df_t1_sub = df_t1.select(t1_cols)
        df_t2_sub = df_t2.select(["symbol", pl.col("close").alias("close_prev2")]) if not df_t2.is_empty() else pl.DataFrame()

        merged = df_t0_sub.join(df_t1_sub, on="symbol", how="inner")
        if not df_t2_sub.is_empty():
            merged = merged.join(df_t2_sub, on="symbol", how="left")

        if not df_inst.is_empty():
            inst_cols = [c for c in ["symbol", "name", "total_shares", "float_shares", "list_date"] if c in df_inst.columns]
            merged = merged.join(df_inst.select(inst_cols), on="symbol", how="left")

        # 1. 过滤：排除北交所 (.BJ, 43, 83, 87, 92)
        merged = merged.filter(
            ~pl.col("symbol").str.ends_with(".BJ") &
            ~pl.col("symbol").str.starts_with("43") &
            ~pl.col("symbol").str.starts_with("83") &
            ~pl.col("symbol").str.starts_with("87") &
            ~pl.col("symbol").str.starts_with("92")
        )

        # 2. 过滤：排除 ST / 退市
        if "name" in merged.columns:
            merged = merged.filter(
                ~pl.col("name").str.starts_with("ST") &
                ~pl.col("name").str.starts_with("*ST") &
                ~pl.col("name").str.starts_with("S*ST") &
                ~pl.col("name").str.starts_with("SST") &
                ~pl.col("name").str.contains("退")
            )

        # 3. 过滤：排除上市未满 30 天新股
        if "list_date" in merged.columns:
            min_list_date = t0_date - timedelta(days=30)
            merged = merged.filter(
                pl.col("list_date").is_null() | (pl.col("list_date") <= min_list_date)
            )

        # 4. 关键过滤：排除昨日涨停/连板、昨日跌停
        if "consec_limit_ups_prev" in merged.columns:
            merged = merged.filter(pl.col("consec_limit_ups_prev") == 0)
        if "consec_limit_downs_prev" in merged.columns:
            merged = merged.filter(pl.col("consec_limit_downs_prev") == 0)

        # 5. 计算指标与涨幅
        merged = merged.with_columns(
            ((pl.col("open") - pl.col("close_prev")) / pl.col("close_prev") * 100).alias("open_gap_pct"),
            (pl.col("close_prev") - pl.col("open_prev")).abs().alias("body_abs"),
            ((pl.col("high_prev") - pl.col("low_prev")) / pl.col("close_prev") * 100).alias("prev_amplitude"),
            (pl.col("amount") / 10000.0).alias("bidding_amount_wan"),
            (pl.when(pl.col("close_prev2").is_not_null())
             .then((pl.col("close_prev") - pl.col("close_prev2")) / pl.col("close_prev2") * 100)
             .otherwise(0.0)).alias("prev_change_pct"),
        ).with_columns(
            (pl.col("body_abs") / pl.col("close_prev") * 100).alias("prev_body_pct"),
            (pl.when(pl.col("volume_prev") > 0)
             .then(pl.col("volume") / pl.col("volume_prev"))
             .otherwise(0.0)).alias("bidding_vol_ratio"),
        )

        # 计算市值（亿）
        if "total_shares" in merged.columns:
            merged = merged.with_columns(
                pl.when(pl.col("total_shares").is_not_null() & (pl.col("total_shares") > 0))
                .then(pl.col("total_shares") * pl.col("open") / 1e8)
                .otherwise(pl.lit(50.0))
                .alias("total_mv")
            )
        else:
            merged = merged.with_columns(pl.lit(50.0).alias("total_mv"))

        if "float_shares" in merged.columns:
            merged = merged.with_columns(
                pl.when(pl.col("float_shares").is_not_null() & (pl.col("float_shares") > 0))
                .then(pl.col("float_shares") * pl.col("open") / 1e8)
                .otherwise(pl.col("total_mv"))
                .alias("float_mv")
            )
        else:
            merged = merged.with_columns(pl.col("total_mv").alias("float_mv"))

        # 5. 条件筛选
        expr_filter = (
            (pl.col("open_gap_pct") >= min_gap_pct) &
            (pl.col("open_gap_pct") <= max_gap_pct) &
            (pl.col("prev_body_pct") <= max_prev_body_pct) &
            (pl.col("prev_change_pct") >= -3.5) &
            (pl.col("prev_change_pct") <= 3.5) &
            (pl.col("prev_amplitude") >= 0.5) &
            (pl.col("total_mv") >= min_mv) &
            (pl.col("total_mv") <= max_mv)
        )

        if not include_chinext:
            expr_filter = expr_filter & ~pl.col("symbol").str.starts_with("300") & ~pl.col("symbol").str.starts_with("301")

        if not include_star:
            expr_filter = expr_filter & ~pl.col("symbol").str.starts_with("688") & ~pl.col("symbol").str.starts_with("689")

        if only_doji:
            expr_filter = expr_filter & (pl.col("prev_body_pct") <= 0.8) & (pl.col("prev_change_pct").abs() <= 2.0) & (pl.col("prev_amplitude") >= 0.8)

        filtered = merged.filter(expr_filter)

        # 6. 历史试盘线与缩量回踩不破底形态识别
        candidate_symbols = filtered["symbol"].to_list() if not filtered.is_empty() else []
        hist_map: dict[str, dict] = {}

        if candidate_symbols:
            history_dates = [d for d in all_dates if d < t0_date][-30:]
            if history_dates:
                df_hist = lf.filter(
                    (pl.col("date").is_in(history_dates)) & (pl.col("symbol").is_in(candidate_symbols))
                ).select(["symbol", "date", "open", "high", "low", "close", "volume", "amount"]).collect()

                for sym in candidate_symbols:
                    sym_bars = df_hist.filter(pl.col("symbol") == sym).sort("date").to_dicts()
                    if len(sym_bars) < 8:
                        continue
                    # 从倒数第 22 天到倒数第 3 天中倒序寻找最近的放量试盘线
                    n = len(sym_bars)
                    start_idx = max(4, n - 22)
                    end_idx = n - 2
                    for i in range(end_idx, start_idx - 1, -1):
                        bar_i = sym_bars[i]
                        prior = sym_bars[max(0, i - 5):i]
                        if not prior:
                            continue
                        avg_vol = sum(b.get("volume") or 0.0 for b in prior) / len(prior)
                        if avg_vol <= 0:
                            continue
                        vol_ratio_test = (bar_i.get("volume") or 0.0) / avg_vol
                        has_test_action = (
                            ((bar_i["high"] - bar_i["low"]) / max(0.01, bar_i["low"]) >= 0.028)
                            or ((bar_i["close"] - bar_i["open"]) / max(0.01, bar_i["open"]) >= 0.015)
                            or ((bar_i["high"] - min(bar_i["open"], bar_i["close"])) / max(0.01, min(bar_i["open"], bar_i["close"])) >= 0.015)
                        )
                        if vol_ratio_test >= 1.25 and has_test_action:
                            subsequent = sym_bars[i + 1:]
                            if len(subsequent) < 3:
                                continue
                            test_low = bar_i["low"]
                            # 核心命门：后续所有K线收盘价坚守试盘最低价（允许 1% 极微毛刺容差）
                            all_hold = all((b.get("close") or 0.0) >= test_low * 0.99 for b in subsequent)
                            avg_sub_vol = sum(b.get("volume") or 0.0 for b in subsequent) / len(subsequent)
                            is_shrink = avg_sub_vol <= (bar_i.get("volume") or 1.0) * 0.90
                            if all_hold and is_shrink:
                                hist_map[sym] = {
                                    "test_date": str(bar_i["date"]),
                                    "test_low": round(float(test_low), 2),
                                    "defense_days": len(subsequent),
                                    "test_vol_ratio": round(float(vol_ratio_test), 2),
                                }
                                break

        # 7. 打标签与评分
        rows: list[dict] = []
        for r in filtered.iter_rows(named=True):
            sym = r["symbol"]
            board = _classify_board(sym)
            body_pct = r.get("prev_body_pct") or 0.0
            gap_pct = r.get("open_gap_pct") or 0.0
            close_prev = r.get("close_prev") or 0.0
            open_prev = r.get("open_prev") or 0.0
            prev_change = r.get("prev_change_pct") or 0.0
            prev_amp = r.get("prev_amplitude") or 0.0
            amount_wan = r.get("bidding_amount_wan") or 0.0
            vol_ratio = r.get("bidding_vol_ratio") or 0.0
            total_mv = r.get("total_mv") or 50.0

            is_doji = (body_pct <= 0.8) and (abs(prev_change) <= 2.0) and (prev_amp >= 0.8)

            # 💜 核心强势抢筹模式识别（以南京商旅为范式）：
            # 1. 前期出现放量试盘线，且后续震荡缩量、收盘价全部守在试盘最低价之上；
            # 2. 今日量比明显翻倍放大 (量比 >= 160%)；
            # 3. 竞价/成交额巨大 (竞价金额 >= 1000万 或 市值适中下 >= 600万 或 全天成交预估 > 1.5亿)；
            # 4. 黄金高开幅度 (1.0% <= 高开 <= 8.5%)。
            has_test_pattern = sym in hist_map
            test_info = hist_map.get(sym, {})
            
            is_core_purple = (
                has_test_pattern
                and (gap_pct >= 1.0)
                and (vol_ratio >= 1.6)
                and (amount_wan >= 1000.0 or (total_mv <= 80.0 and amount_wan >= 600.0))
            )

            # 🚀 跳空高开抢筹识别（高开 >= 3.0%，爆量，前日小实体/十字星蓄势）
            is_gap_jump = (
                (gap_pct >= 3.0)
                and (body_pct <= 2.2)
                and (vol_ratio >= 1.8 or amount_wan >= 800.0)
            )

            # 👑 顶级涨停起爆形态判定
            is_super_breakout = (
                is_doji
                and (2.0 <= gap_pct <= 7.5)
                and (vol_ratio >= 2.2 or amount_wan >= 1200.0)
                and (prev_amp <= 4.0)
            )

            if is_core_purple:
                pattern = "💜 核心强势抢筹"
                pattern_type = "core_purple"
            elif is_gap_jump and (gap_pct >= 4.0 or vol_ratio >= 3.0):
                pattern = "🚀 爆量跳空起爆"
                pattern_type = "gap_jump"
            elif is_gap_jump:
                pattern = "🚀 跳空高开抢筹"
                pattern_type = "gap_jump"
            elif is_super_breakout:
                pattern = "👑 爆量起爆十字星"
                pattern_type = "super_breakout"
            elif is_doji:
                pattern = "⭐ 极致十字星"
                pattern_type = "doji"
            elif close_prev >= open_prev:
                pattern = "📈 小阳蓄势"
                pattern_type = "bull_body"
            else:
                pattern = "📉 小阴回踩"
                pattern_type = "bear_body"

            # 抢筹评分（0~100）
            # 1. 黄金跳空高开 3.0%~6.5% 最具进攻性，得分最高 (40分)
            if 3.0 <= gap_pct <= 6.5:
                gap_score = 40.0
            elif 2.0 <= gap_pct < 3.0 or 6.5 < gap_pct <= 8.5:
                gap_score = 36.0
            elif 1.5 <= gap_pct < 2.0:
                gap_score = 30.0
            else:
                gap_score = 20.0

            # 2. 十字星/实体紧凑程度 (35分)
            shape_score = max(0.0, 35.0 - body_pct * 12.0)

            # 3. 竞价金额与量比 (25分)
            amount_score = min(25.0, (vol_ratio / 4.0) * 15.0 + (amount_wan / 500.0) * 10.0)

            # 超级起爆形态、跳空抢筹与核心紫色形态额外加分
            boost = 0.0
            if is_core_purple:
                boost += 25.0
            if is_gap_jump:
                boost += 22.0
            elif is_super_breakout:
                boost += 16.0

            total_score = min(100.0, round(gap_score + shape_score + amount_score + boost, 1))

            rows.append({
                "symbol": sym,
                "name": r.get("name") or sym,
                "board": board,
                "open": round(float(r.get("open") or 0.0), 2),
                "close_prev": round(float(close_prev), 2),
                "open_gap_pct": round(float(gap_pct), 2),
                "prev_body_pct": round(float(body_pct), 2),
                "prev_amplitude": round(float(r.get("prev_amplitude") or 0.0), 2),
                "total_mv": round(float(total_mv), 1),
                "float_mv": round(float(r.get("float_mv") or 0.0), 1),
                "bidding_amount_wan": round(float(amount_wan), 1),
                "bidding_vol_ratio": round(float(vol_ratio), 2),
                "pattern": pattern,
                "pattern_type": pattern_type,
                "is_doji": is_doji,
                "is_gap_jump": is_gap_jump,
                "is_super_breakout": is_super_breakout,
                "is_core_purple": is_core_purple,
                "test_date": test_info.get("test_date"),
                "test_low": test_info.get("test_low"),
                "defense_days": test_info.get("defense_days"),
                "score": total_score,
            })

        # 按优先抢筹形态（核心抢筹 / 跳空高开 / 爆量起爆）与评分降序排序，跳空高开优先置顶
        rows.sort(
            key=lambda x: (
                x.get("is_core_purple", False) or x.get("is_gap_jump", False) or x.get("is_super_breakout", False),
                x.get("is_gap_jump", False),
                x["score"],
                x.get("bidding_vol_ratio", 0.0),
                x.get("open_gap_pct", 0.0),
            ),
            reverse=True,
        )

        elapsed_ms = round((time.perf_counter() - t0_start) * 1000, 1)

        # 统计摘要
        board_counts = {"沪主板": 0, "深主板": 0, "创业板": 0, "科创板": 0}
        total_bidding_amount = 0.0
        avg_gap = 0.0

        for row in rows:
            b = row.get("board", "主板")
            if b in board_counts:
                board_counts[b] += 1
            total_bidding_amount += row.get("bidding_amount_wan", 0.0)
            avg_gap += row.get("open_gap_pct", 0.0)

        if rows:
            avg_gap = round(avg_gap / len(rows), 2)
            total_bidding_amount = round(total_bidding_amount / 10000.0, 2)  # 转换为亿元

        return {
            "as_of": str(t0_date),
            "t1_date": str(t1_date),
            "is_live": is_live,
            "total": len(rows),
            "stats": {
                "board_counts": board_counts,
                "total_bidding_amount_yi": total_bidding_amount,
                "avg_gap_pct": avg_gap,
                "doji_count": sum(1 for r in rows if r["is_doji"]),
                "core_purple_count": sum(1 for r in rows if r.get("is_core_purple")),
            },
            "rows": rows,
            "elapsed_ms": elapsed_ms,
        }
