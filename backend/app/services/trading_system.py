"""短线趋势资金共振交易系统 (Short-Term Trend & Capital Resonance Trading System).

根据用户定制流派与风控纪律:
1. 市场环境门控与总仓位限制 (Regime Gatekeeper)
2. 5大买入条件筛选与3大策略共振打分 (Signal & Scoring Engine)
3. 开盘执行计划与精准单笔风险仓位计算 (Daily Execution Plan & Position Sizing)
4. 持仓跟踪与分级止盈止损监控 (Active Position & Tiered Exit Manager)
5. 历史交易复盘与纪律统计 (Trade Log & Performance Summary)
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from app.services import regime_builder
from app.indicators.pipeline import compute_indicators, compute_signals, compute_limit_signals

logger = logging.getLogger(__name__)

# 数据存储路径
def _get_user_data_dir(data_dir: Path) -> Path:
    p = data_dir / "user_data"
    p.mkdir(parents=True, exist_ok=True)
    return p


class TradingSystemService:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.user_data_dir = _get_user_data_dir(data_dir)
        self.positions_file = self.user_data_dir / "trade_positions.json"
        self.history_file = self.user_data_dir / "trade_history.json"
        self.settings_file = self.user_data_dir / "trading_settings.json"
        self.custom_plans_file = self.user_data_dir / "custom_trade_plans.json"

    # ================= 1. 默认设置管理 =================
    def get_settings(self) -> dict[str, Any]:
        default_settings = {
            "account_equity": 50000.0,       # 账户本金 5 万元
            "base_risk_ratio": 0.005,        # 基础单笔风险 0.5% (250元)
            "reduced_risk_ratio": 0.0025,    # 连亏减半风险 0.25% (125元)
            "consecutive_loss_threshold": 3, # 连续3笔止损后降风险
            "max_single_position_pct": 0.15, # 单股最大仓位 15% (7500元)
            "max_stop_loss_pct": 0.05,       # 最大止损比例 5.0%
            "atr_multiplier": 1.4,           # 初始止损 ATR 倍数 (1.2 ~ 1.5)
            "max_open_chg_pct": 0.03,        # 开盘高开超过 3% 放弃追高
            "max_holding_days": 5,           # 最大持仓天数 5 天
            "take_profit_r1": 1.0,           # 1.0R 保本移损
            "take_profit_r15": 1.5,          # 1.5R 卖出 1/3
            "take_profit_r2": 2.0,           # 2.0R 再卖出 1/3
            "trailing_stop_pullback": 0.025, # 最高点回撤 2.5% 清仓
            "peak_equity": 50000.0,          # 账户历史峰值 (计算回撤)
        }
        if not self.settings_file.exists():
            return default_settings
        try:
            with open(self.settings_file, "r", encoding="utf-8") as f:
                saved = json.load(f)
                default_settings.update(saved)
                return default_settings
        except Exception as e:
            logger.warning("Failed to load trading settings: %s", e)
            return default_settings

    def save_settings(self, new_settings: dict[str, Any]) -> dict[str, Any]:
        curr = self.get_settings()
        curr.update(new_settings)
        # 确保 peak_equity 不低于当前本金
        if curr["account_equity"] > curr.get("peak_equity", 0.0):
            curr["peak_equity"] = curr["account_equity"]
        with open(self.settings_file, "w", encoding="utf-8") as f:
            json.dump(curr, f, ensure_ascii=False, indent=2)
        return curr

    # ================= 2. 市场环境与总仓位门控 =================
    def get_market_gate(self) -> dict[str, Any]:
        """获取当前市场环境、评分、总仓位限制及回撤保护规则。"""
        settings = self.get_settings()
        account_equity = settings["account_equity"]
        peak_equity = max(account_equity, settings.get("peak_equity", account_equity))
        
        # 计算账户当前回撤
        drawdown_pct = (peak_equity - account_equity) / peak_equity if peak_equity > 0 else 0.0
        
        # 默认市场状态 (以 regime_builder 结果为准)
        market_score = 65.0
        market_state = "lean_strong"
        market_label = "偏强"
        
        try:
            # 尝试从 regime_history 读取最近一期
            regime_dir = self.data_dir / "regime_history"
            if regime_dir.exists():
                parquet_files = list(regime_dir.glob("**/*.parquet"))
                if parquet_files:
                    df_reg = pl.read_parquet(parquet_files[0]).sort("date")
                    if not df_reg.is_empty():
                        latest_row = df_reg.tail(1).to_dicts()[0]
                        market_score = float(latest_row.get("score", 65.0))
                        market_state = str(latest_row.get("state", "lean_strong"))
                        market_label = regime_builder.STATE_LABELS.get(market_state, "偏强")
        except Exception as e:
            logger.warning("Failed to read latest regime: %s", e)

        # 仓位映射矩阵
        if market_score >= 70:
            target_pos_min, target_pos_max = 0.70, 0.80
            max_positions = 5
            allowed_strategies = ["趋势突破", "均线回踩", "资金共振"]
            regime_desc = "市场强势，允许全策略开仓，重仓出击"
        elif market_score >= 55:
            target_pos_min, target_pos_max = 0.45, 0.60
            max_positions = 4
            allowed_strategies = ["只买高分标的", "趋势突破", "资金共振"]
            regime_desc = "市场偏强，精选高分标的，标准短线波段"
        elif market_score >= 45:
            target_pos_min, target_pos_max = 0.20, 0.35
            max_positions = 3
            allowed_strategies = ["只做均线回踩", "严禁追高"]
            regime_desc = "市场震荡，控制低仓位，只低吸回踩，绝不追涨"
        elif market_score >= 30:
            target_pos_min, target_pos_max = 0.00, 0.15
            max_positions = 1
            allowed_strategies = ["仅观察最强股", "严格轻仓试错"]
            regime_desc = "市场偏弱，防守为主，仅允许单只极小仓位试错"
        else:
            target_pos_min, target_pos_max = 0.00, 0.00
            max_positions = 0
            allowed_strategies = ["停止主动交易", "全仓空仓观望"]
            regime_desc = "市场弱势/冰点，严格停止新开仓，清仓保本"

        # 回撤保护降级逻辑
        protection_alert = None
        if drawdown_pct >= 0.15:
            target_pos_min, target_pos_max = 0.0, 0.0
            max_positions = 0
            protection_alert = f"账户回撤达到 {drawdown_pct*100:.1f}% (超过15%红线)！已触发系统最高熔断，严格禁止实盘开仓，仅允许模拟盘！"
        elif drawdown_pct >= 0.12:
            target_pos_min, target_pos_max = 0.0, 0.0
            max_positions = 0
            protection_alert = f"账户回撤达到 {drawdown_pct*100:.1f}% (超过12%黄线)！已触发开仓冻结，停止开新仓，严格管理现有持仓！"
        elif drawdown_pct >= 0.08:
            target_pos_min *= 0.5
            target_pos_max *= 0.5
            max_positions = max(1, max_positions // 2)
            protection_alert = f"账户回撤达到 {drawdown_pct*100:.1f}% (超过8%预警线)！总仓位上限强制减半保护！"

        return {
            "market_score": round(market_score, 1),
            "market_state": market_state,
            "market_label": market_label,
            "target_pos_min": target_pos_min,
            "target_pos_max": target_pos_max,
            "max_positions": max_positions,
            "allowed_strategies": allowed_strategies,
            "regime_desc": regime_desc,
            "account_equity": account_equity,
            "peak_equity": peak_equity,
            "drawdown_pct": round(drawdown_pct, 4),
            "protection_alert": protection_alert,
        }

    # ================= 3. 今日开盘执行计划生成 =================
    def generate_daily_trade_plan(self, target_date: date | None = None) -> dict[str, Any]:
        """生成每日开盘前执行计划表 (含买入理由、仓位测算、开盘追高判定、分级止盈线)。"""
        settings = self.get_settings()
        market_gate = self.get_market_gate()
        account_equity = settings["account_equity"]
        
        # 连续亏损判定单笔风险
        history = self.get_trade_history()
        consecutive_losses = 0
        for t in reversed(history.get("trades", [])):
            if t.get("realized_pnl", 0.0) < 0:
                consecutive_losses += 1
            else:
                break
        
        is_reduced_risk = consecutive_losses >= settings["consecutive_loss_threshold"]
        risk_ratio = settings["reduced_risk_ratio"] if is_reduced_risk else settings["base_risk_ratio"]
        single_risk_amount = account_equity * risk_ratio
        
        # 1. 扫描股票数据
        enriched_dir = self.data_dir / "kline_daily_enriched"
        date_dirs = sorted(enriched_dir.glob("date=*"))
        if not date_dirs:
            return {"date": str(date.today()), "market_gate": market_gate, "plans": [], "risk_info": {}}

        recent_dirs = date_dirs[-60:]
        dfs = [pl.read_parquet(d) for d in recent_dirs]
        df_raw = pl.concat(dfs, how="diagonal").sort(["symbol", "date"]).unique(subset=["symbol", "date"], keep="last")
        
        # 2. 计算完整指标
        df_full = compute_indicators(df_raw)
        df_full = compute_signals(df_full)
        
        inst_df = pl.read_parquet(self.data_dir / "instruments" / "instruments.parquet")
        name_map = dict(zip(inst_df["symbol"], inst_df["name"]))
        df_full = compute_limit_signals(df_full, inst_df)
        
        trading_dates = sorted(df_full["date"].unique().to_list())
        latest_dt = trading_dates[-1] if target_date is None else target_date
        target_idx = trading_dates.index(latest_dt)
        
        # 过去 22 个交易日 (近1个月)
        past_dates = trading_dates[max(0, target_idx - 22): target_idx]
        df_past = df_full.filter((pl.col("date") >= past_dates[0]) & (pl.col("date") <= past_dates[-1]))
        
        # 统计近 1 个月内涨停
        limit_map = {}
        for r in df_past.iter_rows(named=True):
            sym = r["symbol"]
            if not (sym.endswith(".SH") or sym.endswith(".SZ") or sym.endswith(".BJ")):
                continue
            sig_up = r.get("signal_limit_up") or 0
            consec = r.get("consecutive_limit_ups") or 0
            chg = r.get("change_pct") or 0.0
            
            is_up = False
            if sig_up == 1 or consec >= 1:
                is_up = True
            elif sym.startswith(("300", "301", "688")) and chg >= 0.195:
                is_up = True
            elif sym.endswith(".BJ") and chg >= 0.295:
                is_up = True
            elif not sym.startswith(("300", "301", "688")) and not sym.endswith(".BJ") and chg >= 0.095:
                is_up = True
                
            if is_up:
                if sym not in limit_map:
                    limit_map[sym] = []
                limit_map[sym].append(r["date"])

        # 当日与前一日数据
        df_today = df_full.filter(pl.col("date") == latest_dt).unique(subset=["symbol"], keep="last")
        prev_dt = trading_dates[target_idx - 1]
        df_prev = df_full.filter(pl.col("date") == prev_dt).unique(subset=["symbol"], keep="last")
        prev_vol_dict = dict(zip(df_prev["symbol"], df_prev["volume"]))
        
        # 计算 20 日相对强度百分位阈值 (前 30%)
        m20_series = df_today["momentum_20d"].drop_nulls()
        m20_threshold = float(m20_series.quantile(0.70)) if len(m20_series) > 0 else 0.05
        
        plans = []
        for r in df_today.iter_rows(named=True):
            sym = r["symbol"]
            if not (sym.endswith(".SH") or sym.endswith(".SZ") or sym.endswith(".BJ")):
                continue
                
            name = name_map.get(sym, sym)
            if "ST" in name or "退" in name:
                continue
                
            c = r.get("close") or 0.0
            o = r.get("open") or 0.0
            h = r.get("high") or 0.0
            l = r.get("low") or 0.0
            pc = r.get("prev_close") or c
            v = r.get("volume") or 0.0
            amt = r.get("amount") or 0.0
            chg = r.get("change_pct") or 0.0
            turnover = r.get("turnover_rate") or 0.0
            vol_ratio = r.get("vol_ratio_5d") or 1.0
            ma5 = r.get("ma5") or 0.0
            ma10 = r.get("ma10") or 0.0
            ma20 = r.get("ma20") or 0.0
            ma60 = r.get("ma60") or 0.0
            atr14 = r.get("atr_14") or (c * 0.03)
            momentum_20d = r.get("momentum_20d") or 0.0
            
            if c <= 0 or pc <= 0 or amt < 25_000_000:
                continue
                
            prev_v = prev_vol_dict.get(sym, v)
            vol_contraction = v / prev_v if prev_v > 0 else 1.0
            
            # ===== 5 大核心买入条件逐项判定 =====
            # 1. 收盘价在 MA20 上方
            cond1_above_ma20 = c >= ma20 if ma20 > 0 else False
            
            # 2. MA20 向上且 MA20 > MA60
            cond2_ma_trend = (ma20 > ma60) if (ma20 > 0 and ma60 > 0) else (c > ma20)
            
            # 3. 20日相对强度处于全市场前 30%
            cond3_momentum = momentum_20d >= m20_threshold
            
            # 4. 5日量比在 1.3~3.0 或 缩量回踩 (vol_ratio <= 0.85)
            cond4_volume = (1.2 <= vol_ratio <= 3.2) or (vol_contraction <= 0.85)
            
            # 5. 涨停或资金行为共振 (近1月有过涨停或暗盘异动)
            has_limit_up = sym in limit_map
            cond5_catalyst = has_limit_up
            
            satisfied_count = sum([cond1_above_ma20, cond2_ma_trend, cond3_momentum, cond4_volume, cond5_catalyst])
            if satisfied_count < 4:
                continue

            # ===== 策略共振判定 =====
            strategy_tags = []
            if has_limit_up and (vol_contraction <= 0.85 or abs(c - o)/pc <= 0.015):
                strategy_tags.append("MA20回踩/缩量十字星")
            if c >= (r.get("high_20d") or c) * 0.98 or chg >= 0.04:
                strategy_tags.append("右侧趋势突破")
            if vol_ratio >= 1.5 or (r.get("turnover_rate") or 0) >= 4.0:
                strategy_tags.append("资金行为确认")
            if not strategy_tags:
                strategy_tags.append("趋势共振")

            # 综合评分计算 (0 ~ 100)
            trend_score = min(25.0, max(0.0, (momentum_20d / 0.3) * 20.0 + (5.0 if cond2_ma_trend else 0.0)))
            vol_score = 25.0 if (1.3 <= vol_ratio <= 2.5 or vol_contraction <= 0.8) else 15.0
            pattern_score = 25.0 if (has_limit_up and cond1_above_ma20) else 15.0
            regime_bonus = 25.0 * (market_gate["market_score"] / 100.0)
            composite_score = round(trend_score + vol_score + pattern_score + regime_bonus, 1)

            if composite_score < 70.0:
                continue

            # ===== 精准单笔风险与仓位计算 =====
            # 止损价: 1.2~1.5 ATR，且最大不超过 5%
            atr_dist = atr14 * settings["atr_multiplier"]
            raw_stop_loss = c - atr_dist
            max_sl_dist = c * settings["max_stop_loss_pct"]
            stop_loss_price = max(raw_stop_loss, c - max_sl_dist)
            stop_loss_price = round(stop_loss_price, 2)
            
            per_share_risk = max(0.01, c - stop_loss_price)
            stop_loss_pct = per_share_risk / c
            
            # 理论买入股数 = 单笔风险金额 / 每股止损距离
            theoretical_shares = single_risk_amount / per_share_risk
            
            # 单股最大金额限制 (15% 账户资金)
            max_stock_amount = account_equity * settings["max_single_position_pct"]
            max_allowed_shares = int(max_stock_amount / c) if c > 0 else 0
            
            final_shares = int(min(theoretical_shares, max_allowed_shares) // 100 * 100)
            if final_shares < 100:
                final_shares = 100  # 最低一手
                
            order_amount = round(final_shares * c, 2)
            position_pct = round(order_amount / account_equity, 4)
            
            # 分批执行: 首笔 50% 底仓，确认后再补 50%
            first_tranche_shares = int((final_shares * 0.5) // 100 * 100) or 100
            second_tranche_shares = max(0, final_shares - first_tranche_shares)
            
            # 分级止盈价格
            r_value = per_share_risk
            tp_1r = round(c + r_value * 1.0, 2)
            tp_15r = round(c + r_value * 1.5, 2)
            tp_2r = round(c + r_value * 2.0, 2)
            
            # 开盘高开预警门槛 (+3.0%)
            max_chg_open_price = round(pc * (1 + settings["max_open_chg_pct"]), 2)

            plans.append({
                "symbol": sym,
                "name": name,
                "close": round(c, 2),
                "change_pct": round(chg, 4),
                "composite_score": composite_score,
                "trend_score": round(trend_score, 1),
                "strategies": strategy_tags,
                "reasons": [
                    f"收盘价在MA20({ma20:.2f})上方",
                    f"20日动量强度前30% (+{momentum_20d*100:.1f}%)",
                    f"5日量比 {vol_ratio:.2f}" + (" (缩量回踩)" if vol_contraction <= 0.85 else " (放量突破)"),
                    f"近1月有 {len(limit_map.get(sym, []))} 次涨停板确认主力行为" if has_limit_up else "右侧强势趋势形态",
                ],
                # 仓位与订单
                "buy_price": round(c, 2),
                "stop_loss_price": stop_loss_price,
                "stop_loss_pct": round(stop_loss_pct, 4),
                "max_open_price": max_chg_open_price,
                "suggested_shares": final_shares,
                "order_amount": order_amount,
                "position_pct": position_pct,
                "first_tranche_shares": first_tranche_shares,
                "second_tranche_shares": second_tranche_shares,
                # 分级止盈计划
                "tp_1r": tp_1r,
                "tp_15r": tp_15r,
                "tp_2r": tp_2r,
                "trailing_stop_desc": "剩余仓位跌破MA5或自最高点回撤2.5%止盈",
                "max_holding_days": settings["max_holding_days"],
                "last_limit_date": str(limit_map.get(sym, ["—"])[-1]),
            })

        # 排序：按综合分降序
        plans.sort(key=lambda x: x["composite_score"], reverse=True)
        
        # 截取最多推荐只数 (由市场环境决定)
        top_plans = plans[:max(3, market_gate["max_positions"] * 2)]
        
        # 合并用户自定义加入的买入计划 (排在最前)
        custom_plans = self.get_custom_plans()
        if custom_plans:
            # 排除已存在于 top_plans 的重复 symbol
            existing_symbols = {p["symbol"] for p in top_plans}
            clean_custom = [cp for cp in custom_plans if cp["symbol"] not in existing_symbols]
            top_plans = custom_plans + [p for p in top_plans if p["symbol"] not in {cp["symbol"] for cp in custom_plans}]
        
        return {
            "date": str(latest_dt),
            "market_gate": market_gate,
            "risk_info": {
                "account_equity": account_equity,
                "risk_ratio": risk_ratio,
                "is_reduced_risk": is_reduced_risk,
                "single_risk_amount": round(single_risk_amount, 2),
                "consecutive_losses": consecutive_losses,
                "max_single_position_pct": settings["max_single_position_pct"],
            },
            "plans": top_plans,
            "custom_plans": custom_plans,
        }

    # ================= 3.1 自定义执行计划管理 =================
    def get_custom_plans(self) -> list[dict[str, Any]]:
        """获取用户手动加入的所有自定义开盘计划。"""
        if not self.custom_plans_file.exists():
            return []
        try:
            with open(self.custom_plans_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Failed to load custom plans: %s", e)
            return []

    def lookup_stock_plan_preview(
        self,
        symbol: str,
        custom_buy_price: float | None = None,
        custom_stop_loss_pct: float | None = None,
    ) -> dict[str, Any]:
        """根据股票代码实时获取最新价格，并自动测算计划买入价、严格止损价、算仓股数及分级止盈价。"""
        settings = self.get_settings()
        account_equity = settings["account_equity"]
        single_risk_amount = account_equity * settings["base_risk_ratio"]
        
        # 1. 查找名称
        name = symbol
        inst_path = self.data_dir / "instruments/instruments.parquet"
        if inst_path.exists():
            try:
                df_inst = pl.read_parquet(inst_path)
                m = df_inst.filter(pl.col("symbol") == symbol).to_dicts()
                if m:
                    name = m[0].get("name", symbol)
            except Exception:
                pass
                
        # 2. 查找最新收盘价或现价
        latest_price = 10.0
        change_pct = 0.0
        try:
            df = pl.scan_parquet(str(self.data_dir / "kline_daily_enriched/**/*.parquet")).filter(pl.col("symbol") == symbol).collect()
            if len(df) > 0:
                last_row = df.sort("date").tail(1).to_dicts()[0]
                latest_price = float(last_row.get("close") or last_row.get("raw_close") or 10.0)
                change_pct = float(last_row.get("change_pct") or 0.0)
        except Exception as e:
            logger.warning("Error fetching quote for %s: %s", symbol, e)
            
        buy_price = float(custom_buy_price) if (custom_buy_price is not None and custom_buy_price > 0) else latest_price
        sl_pct = float(custom_stop_loss_pct) if (custom_stop_loss_pct is not None and custom_stop_loss_pct > 0) else settings["max_stop_loss_pct"]
        
        stop_loss_price = round(buy_price * (1 - sl_pct), 2)
        per_share_risk = max(0.01, buy_price - stop_loss_price)
        
        theoretical_shares = single_risk_amount / per_share_risk
        max_stock_amount = account_equity * settings["max_single_position_pct"]
        max_allowed_shares = int(max_stock_amount / buy_price) if buy_price > 0 else 0
        
        final_shares = int(min(theoretical_shares, max_allowed_shares) // 100 * 100)
        if final_shares < 100:
            final_shares = 100
            
        order_amount = round(final_shares * buy_price, 2)
        position_pct = round(order_amount / account_equity, 4)
        
        first_tranche_shares = int((final_shares * 0.5) // 100 * 100) or 100
        second_tranche_shares = max(0, final_shares - first_tranche_shares)
        
        tp_1r = round(buy_price + per_share_risk * 1.0, 2)
        tp_15r = round(buy_price + per_share_risk * 1.5, 2)
        tp_2r = round(buy_price + per_share_risk * 2.0, 2)
        max_open_price = round(buy_price * (1 + settings["max_open_chg_pct"]), 2)
        
        return {
            "symbol": symbol,
            "name": name,
            "latest_price": round(latest_price, 2),
            "change_pct": round(change_pct, 4),
            "buy_price": round(buy_price, 2),
            "stop_loss_price": stop_loss_price,
            "stop_loss_pct": round(sl_pct, 4),
            "per_share_risk": round(per_share_risk, 2),
            "single_risk_amount": round(single_risk_amount, 2),
            "suggested_shares": final_shares,
            "order_amount": order_amount,
            "position_pct": position_pct,
            "first_tranche_shares": first_tranche_shares,
            "second_tranche_shares": second_tranche_shares,
            "tp_1r": tp_1r,
            "tp_15r": tp_15r,
            "tp_2r": tp_2r,
            "max_open_price": max_open_price,
        }

    def save_custom_plan(self, plan_data: dict[str, Any]) -> list[dict[str, Any]]:
        """保存/更新一条用户自定义开盘买入计划，并自动计算风控仓位与分级止盈价。"""
        settings = self.get_settings()
        account_equity = settings["account_equity"]
        single_risk_amount = account_equity * settings["base_risk_ratio"]
        
        sym = plan_data["symbol"]
        buy_price = float(plan_data.get("buy_price") or plan_data.get("close") or 10.0)
        
        # 止损价
        if "stop_loss_price" in plan_data and float(plan_data["stop_loss_price"]) > 0:
            stop_loss_price = float(plan_data["stop_loss_price"])
        else:
            stop_loss_price = round(buy_price * (1 - settings["max_stop_loss_pct"]), 2)
            
        per_share_risk = max(0.01, buy_price - stop_loss_price)
        stop_loss_pct = per_share_risk / buy_price
        
        # 理论股数与最大单股仓位限制 (15%)
        theoretical_shares = single_risk_amount / per_share_risk
        max_stock_amount = account_equity * settings["max_single_position_pct"]
        max_allowed_shares = int(max_stock_amount / buy_price) if buy_price > 0 else 0
        
        final_shares = int(min(theoretical_shares, max_allowed_shares) // 100 * 100) or 100
        order_amount = round(final_shares * buy_price, 2)
        position_pct = round(order_amount / account_equity, 4)
        
        first_tranche_shares = int((final_shares * 0.5) // 100 * 100) or 100
        second_tranche_shares = max(0, final_shares - first_tranche_shares)
        
        # 分级止盈价
        tp_1r = round(buy_price + per_share_risk * 1.0, 2)
        tp_15r = round(buy_price + per_share_risk * 1.5, 2)
        tp_2r = round(buy_price + per_share_risk * 2.0, 2)
        max_open_price = round(buy_price * (1 + settings["max_open_chg_pct"]), 2)

        custom_item = {
            "symbol": sym,
            "name": plan_data.get("name", sym),
            "close": buy_price,
            "change_pct": float(plan_data.get("change_pct", 0.0)),
            "composite_score": float(plan_data.get("composite_score", 95.0)),
            "trend_score": float(plan_data.get("trend_score", 25.0)),
            "strategies": plan_data.get("strategies", ["自定义买入计划"]),
            "reasons": plan_data.get("reasons", ["用户自选加入计划", "符合短线资金风控纪律"]),
            "buy_price": buy_price,
            "stop_loss_price": stop_loss_price,
            "stop_loss_pct": round(stop_loss_pct, 4),
            "max_open_price": max_open_price,
            "suggested_shares": final_shares,
            "order_amount": order_amount,
            "position_pct": position_pct,
            "first_tranche_shares": first_tranche_shares,
            "second_tranche_shares": second_tranche_shares,
            "tp_1r": tp_1r,
            "tp_15r": tp_15r,
            "tp_2r": tp_2r,
            "trailing_stop_desc": "剩余仓位跌破MA5或自最高点回撤2.5%止盈",
            "max_holding_days": settings["max_holding_days"],
            "last_limit_date": plan_data.get("last_limit_date", "—"),
            "is_custom": True,
            "created_at": datetime.now().isoformat(),
        }

        plans = self.get_custom_plans()
        # 覆盖同 symbol
        updated_plans = [p for p in plans if p.get("symbol") != sym]
        updated_plans.insert(0, custom_item)

        with open(self.custom_plans_file, "w", encoding="utf-8") as f:
            json.dump(updated_plans, f, ensure_ascii=False, indent=2)

        return updated_plans

    def delete_custom_plan(self, symbol: str) -> list[dict[str, Any]]:
        """删除一条自定义开盘计划。"""
        plans = self.get_custom_plans()
        updated_plans = [p for p in plans if p.get("symbol") != symbol]
        with open(self.custom_plans_file, "w", encoding="utf-8") as f:
            json.dump(updated_plans, f, ensure_ascii=False, indent=2)
        return updated_plans

    # ================= 4. 持仓管理与分级止盈止损监控 =================
    def get_active_positions(self) -> list[dict[str, Any]]:
        """获取当前活跃持仓列表，并实时计算浮动盈亏、R倍数与分级止盈止损提示。"""
        if not self.positions_file.exists():
            return []
        try:
            with open(self.positions_file, "r", encoding="utf-8") as f:
                positions = json.load(f)
        except Exception as e:
            logger.warning("Failed to load positions: %s", e)
            return []

        if not positions:
            return []

        # 尝试更新最新价格
        enriched_dir = self.data_dir / "kline_daily_enriched"
        date_dirs = sorted(enriched_dir.glob("date=*"))
        quote_map = {}
        if date_dirs:
            latest_df = pl.read_parquet(date_dirs[-1])
            for r in latest_df.select(["symbol", "close", "high", "low"]).iter_rows(named=True):
                quote_map[r["symbol"]] = r

        settings = self.get_settings()
        enhanced_positions = []
        for pos in positions:
            sym = pos["symbol"]
            q = quote_map.get(sym, {})
            curr_price = float(q.get("close") or pos["buy_price"])
            highest_since_entry = max(pos.get("highest_price", pos["buy_price"]), float(q.get("high") or curr_price))
            
            buy_price = float(pos["buy_price"])
            shares = int(pos["shares"])
            stop_loss = float(pos["stop_loss_price"])
            initial_risk = max(0.01, buy_price - stop_loss)
            
            floating_pnl = round((curr_price - buy_price) * shares, 2)
            floating_pnl_pct = round((curr_price - buy_price) / buy_price, 4)
            current_r = round((curr_price - buy_price) / initial_risk, 2) if initial_risk > 0 else 0.0
            
            # 持仓天数计算
            entry_date = pos.get("entry_date", str(date.today()))
            try:
                d_entry = datetime.strptime(entry_date, "%Y-%m-%d").date()
                holding_days = max(1, (date.today() - d_entry).days)
            except Exception:
                holding_days = 1

            # 分级止盈止损触发状态分析
            action_alerts = []
            tp_stage = 0
            
            # 1. 严格止损判定
            if curr_price <= stop_loss:
                action_alerts.append({
                    "level": "danger",
                    "type": "STOP_LOSS",
                    "title": "触发止损线",
                    "desc": f"现价 {curr_price:.2f} 已击穿初始止损价 {stop_loss:.2f}，坚决清仓离场！",
                    "suggested_action": "全部平仓",
                })
            
            # 2. 最高点回撤止盈
            pullback_from_high = (highest_since_entry - curr_price) / highest_since_entry if highest_since_entry > 0 else 0.0
            if current_r >= 1.0 and pullback_from_high >= settings["trailing_stop_pullback"]:
                action_alerts.append({
                    "level": "warning",
                    "type": "TRAILING_STOP",
                    "title": "最高点回撤止盈",
                    "desc": f"自持仓最高价 {highest_since_entry:.2f} 回撤 {pullback_from_high*100:.1f}% (超过2.5%保护线)，建议锁定利润！",
                    "suggested_action": "卖出剩余仓位",
                })

            # 3. 分级止盈阶梯
            if current_r >= 2.0:
                tp_stage = 3
                action_alerts.append({
                    "level": "success",
                    "type": "TP_STAGE_2",
                    "title": "达成 +2.0R 目标",
                    "desc": f"收益达 2R (+{floating_pnl_pct*100:.1f}%)，执行第二批止盈 (再卖出 1/3 仓位)！",
                    "suggested_action": "分批止盈 1/3",
                })
            elif current_r >= 1.5:
                tp_stage = 2
                action_alerts.append({
                    "level": "success",
                    "type": "TP_STAGE_1",
                    "title": "达成 +1.5R 目标",
                    "desc": f"收益达 1.5R (+{floating_pnl_pct*100:.1f}%)，执行第一批止盈 (卖出 1/3 仓位)！",
                    "suggested_action": "分批止盈 1/3",
                })
            elif current_r >= 1.0:
                tp_stage = 1
                action_alerts.append({
                    "level": "info",
                    "type": "MOVE_TO_BREAKEVEN",
                    "title": "达成 +1.0R (保本移损)",
                    "desc": f"已达 1R 盈利目标，止损位已上移至成本线 ({buy_price:.2f})，保本运行无回撤风险！",
                    "suggested_action": "止损上移至成本",
                })

            # 4. 时间周期止损
            if holding_days >= settings["max_holding_days"]:
                action_alerts.append({
                    "level": "warning",
                    "type": "TIME_EXIT",
                    "title": "达到最长持仓天数",
                    "desc": f"已持仓 {holding_days} 天（达到 5 天上限），短线动能衰退，建议清仓换股！",
                    "suggested_action": "清仓退出",
                })
            elif holding_days >= 2 and current_r < 1.0:
                action_alerts.append({
                    "level": "info",
                    "type": "TIME_WARNING",
                    "title": "持仓 2 天未达 1R",
                    "desc": f"已持仓 {holding_days} 天仍未启动，短线爆发力不足，注意逢高减半仓！",
                    "suggested_action": "减仓 50%",
                })

            p_copy = dict(pos)
            p_copy.update({
                "current_price": curr_price,
                "highest_price": highest_since_entry,
                "market_value": round(curr_price * shares, 2),
                "floating_pnl": floating_pnl,
                "floating_pnl_pct": floating_pnl_pct,
                "current_r": current_r,
                "holding_days": holding_days,
                "tp_stage": tp_stage,
                "action_alerts": action_alerts,
            })
            enhanced_positions.append(p_copy)

        return enhanced_positions

    def add_position(self, pos_data: dict[str, Any]) -> list[dict[str, Any]]:
        """新建/买入一笔持仓订单。"""
        positions = self.get_active_positions()
        clean_item = {
            "id": pos_data.get("id") or f"pos_{pos_data['symbol']}_{int(datetime.now().timestamp())}",
            "symbol": pos_data["symbol"],
            "name": pos_data.get("name", pos_data["symbol"]),
            "buy_price": float(pos_data["buy_price"]),
            "shares": int(pos_data["shares"]),
            "stop_loss_price": float(pos_data["stop_loss_price"]),
            "tp_1r": float(pos_data.get("tp_1r", pos_data["buy_price"] * 1.04)),
            "tp_15r": float(pos_data.get("tp_15r", pos_data["buy_price"] * 1.06)),
            "tp_2r": float(pos_data.get("tp_2r", pos_data["buy_price"] * 1.08)),
            "entry_date": pos_data.get("entry_date", str(date.today())),
            "entry_strategy": pos_data.get("entry_strategy", "短线共振"),
            "highest_price": float(pos_data.get("highest_price", pos_data["buy_price"])),
            "notes": pos_data.get("notes", ""),
        }
        
        # 如果已存在同 symbol，合并加仓
        merged = False
        for p in positions:
            if p["symbol"] == clean_item["symbol"]:
                total_shares = p["shares"] + clean_item["shares"]
                avg_cost = (p["buy_price"] * p["shares"] + clean_item["buy_price"] * clean_item["shares"]) / total_shares
                p["shares"] = total_shares
                p["buy_price"] = round(avg_cost, 2)
                p["highest_price"] = max(p["highest_price"], clean_item["highest_price"])
                merged = True
                break
        if not merged:
            positions.append(clean_item)

        raw_list = [{k: v for k, v in p.items() if k not in ["current_price", "market_value", "floating_pnl", "floating_pnl_pct", "current_r", "holding_days", "tp_stage", "action_alerts"]} for p in positions]
        with open(self.positions_file, "w", encoding="utf-8") as f:
            json.dump(raw_list, f, ensure_ascii=False, indent=2)

        return self.get_active_positions()

    def close_position(self, symbol: str, sell_price: float, sell_shares: int | None = None, reason: str = "主动止盈/止损") -> dict[str, Any]:
        """平仓（全部或部分）并记录交易复盘日志。"""
        positions = self.get_active_positions()
        target_pos = None
        remaining_positions = []
        
        for p in positions:
            if p["symbol"] == symbol:
                target_pos = p
            else:
                remaining_positions.append(p)
                
        if not target_pos:
            return {"success": False, "message": "未找到对应持仓"}

        total_shares = target_pos["shares"]
        actual_sell_shares = min(total_shares, sell_shares or total_shares)
        
        # 计算已实现盈亏
        buy_price = target_pos["buy_price"]
        realized_pnl = round((sell_price - buy_price) * actual_sell_shares, 2)
        realized_pnl_pct = round((sell_price - buy_price) / buy_price, 4)
        
        # 记录到历史
        history = self.get_trade_history()
        history_trades = history.get("trades", [])
        trade_record = {
            "id": f"trade_{symbol}_{int(datetime.now().timestamp())}",
            "symbol": symbol,
            "name": target_pos["name"],
            "entry_date": target_pos["entry_date"],
            "exit_date": str(date.today()),
            "buy_price": buy_price,
            "sell_price": sell_price,
            "shares": actual_sell_shares,
            "realized_pnl": realized_pnl,
            "realized_pnl_pct": realized_pnl_pct,
            "holding_days": target_pos.get("holding_days", 1),
            "strategy": target_pos.get("entry_strategy", "短线共振"),
            "exit_reason": reason,
            "is_win": realized_pnl > 0,
        }
        history_trades.append(trade_record)
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump({"trades": history_trades}, f, ensure_ascii=False, indent=2)

        # 更新账户本金
        settings = self.get_settings()
        new_equity = round(settings["account_equity"] + realized_pnl, 2)
        self.save_settings({"account_equity": new_equity})

        # 如果只是部分平仓，保留剩余股数
        if actual_sell_shares < total_shares:
            target_pos["shares"] = total_shares - actual_sell_shares
            remaining_positions.append(target_pos)

        raw_list = [{k: v for k, v in p.items() if k not in ["current_price", "market_value", "floating_pnl", "floating_pnl_pct", "current_r", "holding_days", "tp_stage", "action_alerts"]} for p in remaining_positions]
        with open(self.positions_file, "w", encoding="utf-8") as f:
            json.dump(raw_list, f, ensure_ascii=False, indent=2)

        return {
            "success": True,
            "closed_trade": trade_record,
            "new_equity": new_equity,
            "remaining_positions": self.get_active_positions(),
        }

    # ================= 5. 交易历史与纪律统计 =================
    def get_trade_history(self) -> dict[str, Any]:
        """获取交易复盘日志及胜率、盈亏比等统计指标。"""
        if not self.history_file.exists():
            return {"trades": [], "summary": {}}
        try:
            with open(self.history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                trades = data.get("trades", [])
        except Exception as e:
            logger.warning("Failed to load history: %s", e)
            trades = []

        if not trades:
            return {"trades": [], "summary": {
                "total_trades": 0,
                "win_count": 0,
                "loss_count": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "profit_factor": 0.0,
                "avg_holding_days": 0.0,
                "max_win": 0.0,
                "max_loss": 0.0,
            }}

        total_trades = len(trades)
        wins = [t for t in trades if t.get("realized_pnl", 0) > 0]
        losses = [t for t in trades if t.get("realized_pnl", 0) < 0]
        
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = round(win_count / total_trades, 4) if total_trades > 0 else 0.0
        
        total_pnl = round(sum(t.get("realized_pnl", 0) for t in trades), 2)
        total_gain = sum(t.get("realized_pnl", 0) for t in wins)
        total_loss = abs(sum(t.get("realized_pnl", 0) for t in losses))
        
        profit_factor = round(total_gain / total_loss, 2) if total_loss > 0 else (99.0 if total_gain > 0 else 0.0)
        avg_holding_days = round(sum(t.get("holding_days", 1) for t in trades) / total_trades, 1)
        max_win = max([t.get("realized_pnl", 0) for t in trades] + [0.0])
        max_loss = min([t.get("realized_pnl", 0) for t in trades] + [0.0])

        return {
            "trades": list(reversed(trades)),
            "summary": {
                "total_trades": total_trades,
                "win_count": win_count,
                "loss_count": loss_count,
                "win_rate": win_rate,
                "total_pnl": total_pnl,
                "profit_factor": profit_factor,
                "avg_holding_days": avg_holding_days,
                "max_win": max_win,
                "max_loss": max_loss,
            },
        }
