#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自动化全量 API 接口与前端映射健康度检查套件。"""
import sys
import time
import requests
import json

BASE_URL = "http://localhost:3018"

# 待测试的核心接口清单 (含参数)
TEST_ENDPOINTS = [
    # 1. 基础与配置
    ("GET", "/api/data/version", None, None),
    ("GET", "/api/capabilities", None, None),
    ("GET", "/api/settings", None, None),
    ("GET", "/api/settings/preferences", None, None),
    ("GET", "/api/settings/data-sources", None, None),
    ("GET", "/api/analysis-menus", None, None),
    ("GET", "/api/data/status", None, None),
    
    # 2. 实时行情与大盘
    ("GET", "/api/intraday/status", None, None),
    ("GET", "/api/intraday/indices?symbols=000001.SH,399001.SZ,399006.SZ,000680.SH", None, None),
    ("GET", "/api/overview", None, None),
    ("GET", "/api/overview/dimension-ranks?as_of=2026-08-31", None, None),
    ("GET", "/api/indices/summary", None, None),
    ("GET", "/api/indices-market/summary", None, None),
    
    # 3. 选股与集合竞价
    ("GET", "/api/auction/screen?min_gap_pct=1.5&min_mv=10&max_mv=200", None, None),
    ("GET", "/api/darkpool/rank?sort_by=net_inflow&limit=20", None, None),
    ("GET", "/api/screener/screen?preset=limit_up", None, None),
    ("GET", "/api/screener/presets", None, None),
    ("GET", "/api/signals/supported", None, None),
    
    # 4. 策略与回测
    ("GET", "/api/strategy/list", None, None),
    ("GET", "/api/strategy/categories", None, None),
    ("GET", "/api/backtest/strategies", None, None),
    ("GET", "/api/backtest/universe-presets", None, None),
    ("GET", "/api/backtest/tasks", None, None),
    ("GET", "/api/backtest/matrix/status?asset_type=stock", None, None),
    
    # 5. 监控与预警
    ("GET", "/api/alerts?days=7&limit=20", None, None),
    ("GET", "/api/monitor-rules", None, None),
    
    # 6. 自选与交易计划
    ("GET", "/api/watchlist", None, None),
    ("GET", "/api/watchlist/enriched", None, None),
    ("GET", "/api/trade-plan", None, None),
    
    # 7. 财务与扩展分析
    ("GET", "/api/financials/status", None, None),
    ("GET", "/api/ext/data/status", None, None),
    ("GET", "/api/ext/data/configs", None, None),
    ("GET", "/api/ext/data/industries", None, None),
    ("GET", "/api/ext/data/concepts", None, None),
    ("GET", "/api/rps/rotation", None, None),
    ("GET", "/api/regime/status", None, None),
    ("GET", "/api/market-recap/latest", None, None),
    ("GET", "/api/news/realtime", None, None),
    
    # 8. 个股深度分析
    ("GET", "/api/stock-analysis/000001.SZ", None, None),
    ("GET", "/api/kline/daily/000001.SZ?limit=30", None, None),
]

def run_health_check():
    print("=" * 70)
    print("🚀 开始执行全系统 API 接口与前端映射健康度检查...")
    print("=" * 70)
    
    success_count = 0
    fail_count = 0
    warnings = []
    
    for method, path, params, body in TEST_ENDPOINTS:
        url = f"{BASE_URL}{path}"
        t0 = time.perf_counter()
        try:
            if method == "GET":
                resp = requests.get(url, params=params, timeout=10)
            else:
                resp = requests.post(url, json=body, timeout=10)
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
            
            if resp.status_code == 200:
                success_count += 1
                try:
                    data = resp.json()
                    item_count = len(data) if isinstance(data, list) else len(data.keys()) if isinstance(data, dict) else 1
                    print(f"✅ [200 OK] {method:<4} {path:<55} ({elapsed_ms:>6.1f}ms, items/keys: {item_count})")
                except Exception:
                    print(f"✅ [200 OK] {method:<4} {path:<55} ({elapsed_ms:>6.1f}ms)")
            else:
                fail_count += 1
                print(f"❌ [{resp.status_code}] {method:<4} {path:<55} ({elapsed_ms:>6.1f}ms) -> {resp.text[:120]}")
                warnings.append((path, resp.status_code, resp.text[:200]))
        except Exception as e:
            fail_count += 1
            print(f"💥 [ERROR] {method:<4} {path:<55} -> {str(e)[:100]}")
            warnings.append((path, 500, str(e)))
            
    print("=" * 70)
    print(f"📊 测试结果汇报: 总计 {len(TEST_ENDPOINTS)} 个接口 | 成功 {success_count} 个 | 异常 {fail_count} 个")
    print("=" * 70)
    
    if warnings:
        print("\n⚠️ 异常接口清单与排查定位：")
        for path, code, detail in warnings:
            print(f"  - [{code}] {path} -> {detail}")
            
    return fail_count

if __name__ == "__main__":
    sys.exit(run_health_check())
