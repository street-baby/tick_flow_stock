"""龙虎榜数据服务 (Dragon and Tiger List Service)

对接智兔 API 龙虎榜数据通道:
1. /hilh/mrxq: 今日龙虎榜概览 (按上榜原因分类)
2. /hilh/ggsb/{days}: 近 n 日个股上榜统计 (5/10/30/60)
3. /hilh/yybsb/{days}: 近 n 日营业部上榜统计 (5/10/30/60)
4. /hilh/jgxw/{days}: 近 n 日机构席位追踪 (5/10/30/60)
5. /hilh/xwmx: 近 5 日机构席位成交明细
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from app.data_providers import custom as custom_sources

logger = logging.getLogger(__name__)

# 内存微缓存 (TTL: 60秒)
_CACHE: Dict[str, tuple[float, Any]] = {}
CACHE_TTL_S = 60.0


def _symbol_with_exchange(dm: str) -> str:
    """给纯数字代码补齐市场后缀 (如 600487 -> 600487.SH, 300276 -> 300276.SZ)。"""
    code = str(dm or "").strip().zfill(6)
    if not code:
        return ""
    if code.startswith(("60", "68", "90")):
        return f"{code}.SH"
    if code.startswith(("00", "30", "20")):
        return f"{code}.SZ"
    if code.startswith(("43", "83", "87", "92", "88")):
        return f"{code}.BJ"
    return code


class LongHuBangService:
    def __init__(self):
        pass

    def _get_zhitu_client(self):
        provider = custom_sources.get_provider("zhitu")
        if not provider or not getattr(provider, "_client", None):
            return None
        return provider._client

    def _get_cached_or_fetch(self, key: str, fetch_fn):
        now = time.time()
        if key in _CACHE:
            ts, data = _CACHE[key]
            if now - ts < CACHE_TTL_S:
                return data
        try:
            data = fetch_fn()
            _CACHE[key] = (now, data)
            return data
        except Exception as e:
            logger.warning("fetch lhb data failed for %s: %s", key, e)
            if key in _CACHE:
                return _CACHE[key][1]
            return None

    def get_daily_lhb(self) -> Dict[str, Any]:
        """获取每日龙虎榜详情，按上榜原因归类并展平。"""
        def _fetch():
            client = self._get_zhitu_client()
            if not client:
                return {"date": "", "categories": {}, "all_stocks": []}
            raw = client.get_json("/hilh/mrxq") or {}
            if not isinstance(raw, dict):
                return {"date": "", "categories": {}, "all_stocks": []}

            date_str = str(raw.get("t") or "")
            
            # 分类映射字典
            category_names = {
                "zpl7": "日涨幅偏离值达7%",
                "z20": "连续3日涨幅偏离值达20%",
                "h20": "日换手率达20%",
                "zf15": "日振幅值达15%",
                "dpl7": "日跌幅偏离值达7%",
                "df15": "连续3日跌幅偏离值达20%",
                "st15": "ST连续3日涨幅偏离达15%",
                "st12": "ST连续3日涨幅偏离达12%",
                "std15": "ST连续3日跌幅偏离达15%",
                "std12": "ST连续3日跌幅偏离达12%",
                "wxz": "无价格涨跌幅限制",
                "wxztp": "无限制异常波动停牌",
            }

            categories: Dict[str, List[Dict[str, Any]]] = {}
            all_stocks_map: Dict[str, Dict[str, Any]] = {}

            for cat_key, cat_label in category_names.items():
                items = raw.get(cat_key)
                if isinstance(items, list) and items:
                    parsed_list = []
                    for it in items:
                        if not isinstance(it, dict):
                            continue
                        dm = str(it.get("dm") or "")
                        symbol = _symbol_with_exchange(dm)
                        row = {
                            "symbol": symbol,
                            "code": dm,
                            "name": str(it.get("mc") or ""),
                            "close": float(it.get("c") or 0.0),
                            "change_pct": float(it.get("val") or 0.0),  # 原始百分比值 如 10.02
                            "volume": float(it.get("v") or 0.0),
                            "amount": float(it.get("e") or 0.0),
                            "reason_key": cat_key,
                            "reason_label": cat_label,
                        }
                        parsed_list.append(row)
                        
                        if symbol not in all_stocks_map:
                            all_stocks_map[symbol] = {
                                **row,
                                "reasons": [cat_label],
                            }
                        else:
                            if cat_label not in all_stocks_map[symbol]["reasons"]:
                                all_stocks_map[symbol]["reasons"].append(cat_label)

                    categories[cat_key] = parsed_list

            return {
                "date": date_str,
                "category_meta": category_names,
                "categories": categories,
                "all_stocks": list(all_stocks_map.values()),
                "total_stocks_count": len(all_stocks_map),
            }

        return self._get_cached_or_fetch("daily_lhb", _fetch) or {
            "date": "",
            "category_meta": {},
            "categories": {},
            "all_stocks": [],
            "total_stocks_count": 0,
        }

    def get_stock_stats(self, days: int = 5) -> List[Dict[str, Any]]:
        """近 n 日个股上榜统计 (5, 10, 30, 60)。"""
        days = days if days in (5, 10, 30, 60) else 5
        
        def _fetch():
            client = self._get_zhitu_client()
            if not client:
                return []
            raw = client.get_json(f"/hilh/ggsb/{days}")
            if not isinstance(raw, list):
                return []
            res = []
            for r in raw:
                if not isinstance(r, dict):
                    continue
                dm = str(r.get("dm") or "")
                res.append({
                    "symbol": _symbol_with_exchange(dm),
                    "code": dm,
                    "name": str(r.get("mc") or ""),
                    "count": int(r.get("count") or 0),
                    "buy_amount": float(r.get("totalb") or 0.0),   # 万元
                    "sell_amount": float(r.get("totals") or 0.0), # 万元
                    "net_amount": float(r.get("netp") or 0.0),    # 万元
                    "buy_seats": int(r.get("xb") or 0),
                    "sell_seats": int(r.get("xs") or 0),
                })
            return res

        return self._get_cached_or_fetch(f"stock_stats_{days}", _fetch) or []

    def get_branch_stats(self, days: int = 5) -> List[Dict[str, Any]]:
        """近 n 日营业部上榜统计 (5, 10, 30, 60)。"""
        days = days if days in (5, 10, 30, 60) else 5

        def _fetch():
            client = self._get_zhitu_client()
            if not client:
                return []
            raw = client.get_json(f"/hilh/yybsb/{days}")
            if not isinstance(raw, list):
                return []
            res = []
            for r in raw:
                if not isinstance(r, dict):
                    continue
                res.append({
                    "branch_name": str(r.get("yybmc") or ""),
                    "count": int(r.get("count") or 0),
                    "buy_amount": float(r.get("totalb") or 0.0),   # 万元
                    "buy_seats": int(r.get("bcount") or 0),
                    "sell_amount": float(r.get("totals") or 0.0), # 万元
                    "sell_seats": int(r.get("scount") or 0),
                    "net_amount": float(r.get("totalb") or 0.0) - float(r.get("totals") or 0.0),
                    "top3_stocks": [s.strip() for s in str(r.get("top3") or "").split(",") if s.strip()],
                })
            return res

        return self._get_cached_or_fetch(f"branch_stats_{days}", _fetch) or []

    def get_institution_stats(self, days: int = 5) -> List[Dict[str, Any]]:
        """近 n 日机构席位追踪统计 (5, 10, 30, 60)。"""
        days = days if days in (5, 10, 30, 60) else 5

        def _fetch():
            client = self._get_zhitu_client()
            if not client:
                return []
            raw = client.get_json(f"/hilh/jgxw/{days}")
            if not isinstance(raw, list):
                return []
            res = []
            for r in raw:
                if not isinstance(r, dict):
                    continue
                dm = str(r.get("dm") or "")
                raw_be = float(r.get("be") or 0.0)
                raw_se = float(r.get("se") or 0.0)
                raw_ende = float(r.get("ende") or 0.0)
                raw_bc = int(r.get("bcount") or 0)
                raw_sc = int(r.get("scount") or 0)

                # 智兔 /hilh/jgxw 接口字段量纲自适应兼容:
                # 正常情况: be=买入额, se=卖出额, ende=净额, bcount=买入次, scount=卖出次
                # 智兔偏移情况 (be=0): se 存放买入额, ende 存放卖出额, scount 为买入上榜次数
                if raw_be > 0:
                    buy_amount = raw_be
                    sell_amount = raw_se
                    net_amount = float(r.get("ende") or (buy_amount - sell_amount))
                    buy_count = raw_bc
                    sell_count = raw_sc
                else:
                    buy_amount = raw_se
                    sell_amount = raw_ende
                    net_amount = buy_amount - sell_amount
                    buy_count = raw_sc
                    sell_count = raw_bc

                res.append({
                    "symbol": _symbol_with_exchange(dm),
                    "code": dm,
                    "name": str(r.get("mc") or ""),
                    "buy_amount": buy_amount,     # 万元
                    "buy_count": buy_count,
                    "sell_amount": sell_amount,   # 万元
                    "sell_count": sell_count,
                    "net_amount": net_amount,     # 万元
                })
            return res

        return self._get_cached_or_fetch(f"institution_stats_{days}", _fetch) or []

    def get_institution_details(self) -> List[Dict[str, Any]]:
        """近 5 日机构席位成交流水明细。"""
        def _fetch():
            client = self._get_zhitu_client()
            if not client:
                return []
            raw = client.get_json("/hilh/xwmx")
            if not isinstance(raw, list):
                return []
            res = []
            for r in raw:
                if not isinstance(r, dict):
                    continue
                dm = str(r.get("dm") or "")
                buy_val = float(r.get("buy") or 0.0)
                sell_val = float(r.get("sell") or 0.0)
                res.append({
                    "symbol": _symbol_with_exchange(dm),
                    "code": dm,
                    "name": str(r.get("mc") or ""),
                    "date": str(r.get("t") or ""),
                    "buy_amount": buy_val,   # 万元
                    "sell_amount": sell_val, # 万元
                    "net_amount": buy_val - sell_val,
                    "reason": str(r.get("type") or ""),
                })
            return res

        return self._get_cached_or_fetch("institution_details", _fetch) or []


lhb_service = LongHuBangService()
