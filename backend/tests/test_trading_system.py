"""测试短线趋势资金共振交易系统 (Trade Plan Service & API)."""
from pathlib import Path
from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.trading_system import TradingSystemService
from app.api.trade_plan import router as trade_plan_router


def test_trading_system_settings(tmp_path: Path):
    srv = TradingSystemService(tmp_path)
    s = srv.get_settings()
    assert s["account_equity"] == 50000.0
    assert s["base_risk_ratio"] == 0.005
    assert s["max_single_position_pct"] == 0.15

    # 更新设置
    updated = srv.save_settings({"account_equity": 60000.0, "base_risk_ratio": 0.006})
    assert updated["account_equity"] == 60000.0
    assert updated["base_risk_ratio"] == 0.006

    # 重新加载
    s2 = srv.get_settings()
    assert s2["account_equity"] == 60000.0


def test_trading_system_custom_plans(tmp_path: Path):
    srv = TradingSystemService(tmp_path)
    # 1. 初始为空
    assert len(srv.get_custom_plans()) == 0

    # 2. 自定义添加一条买入计划
    custom_item = {
        "symbol": "000001.SZ",
        "name": "平安银行",
        "buy_price": 12.0,
        "stop_loss_price": 11.4,
        "strategies": ["突破买入"],
        "reasons": ["大单异动"],
    }
    plans = srv.save_custom_plan(custom_item)
    assert len(plans) == 1
    assert plans[0]["symbol"] == "000001.SZ"
    assert plans[0]["is_custom"] is True
    assert plans[0]["suggested_shares"] > 0
    assert plans[0]["tp_1r"] > 12.0

    # 3. 删除自定义计划
    remaining = srv.delete_custom_plan("000001.SZ")
    assert len(remaining) == 0


def test_trading_system_positions_and_exit(tmp_path: Path):
    srv = TradingSystemService(tmp_path)
    
    # 1. 录入一笔持仓
    pos_data = {
        "symbol": "603366.SH",
        "name": "日出东方",
        "buy_price": 10.0,
        "shares": 500,
        "stop_loss_price": 9.5,
        "tp_1r": 10.5,
        "tp_15r": 10.75,
        "tp_2r": 11.0,
        "entry_strategy": "MA20回踩/缩量十字星",
    }
    positions = srv.add_position(pos_data)
    assert len(positions) == 1
    assert positions[0]["symbol"] == "603366.SH"
    assert positions[0]["shares"] == 500

    # 2. 部分平仓 (卖出 200 股)
    res = srv.close_position("603366.SH", sell_price=10.75, sell_shares=200, reason="达成+1.5R分批止盈")
    assert res["success"] is True
    assert res["closed_trade"]["realized_pnl"] == 150.0  # (10.75 - 10.0) * 200
    assert len(res["remaining_positions"]) == 1
    assert res["remaining_positions"][0]["shares"] == 300

    # 3. 查看复盘历史
    history = srv.get_trade_history()
    assert history["summary"]["total_trades"] == 1
    assert history["summary"]["win_rate"] == 1.0
    assert history["summary"]["total_pnl"] == 150.0

    # 4. 全额清仓剩余 300 股
    res2 = srv.close_position("603366.SH", sell_price=11.0, sell_shares=300, reason="达成+2.0R清仓")
    assert res2["success"] is True
    assert len(res2["remaining_positions"]) == 0
    assert res2["closed_trade"]["realized_pnl"] == 300.0


def test_trading_system_ai_copilot(tmp_path: Path):
    srv = TradingSystemService(tmp_path)
    copilot = srv.get_ai_market_copilot()
    assert "market_gate" in copilot
    assert "market_sentiment" in copilot
    assert "ai_directive" in copilot
    assert "hot_sectors" in copilot
    assert len(copilot["hot_sectors"]) > 0
    assert "ai_high_alpha_picks" in copilot
    assert "rebalance_alerts" in copilot


def test_trading_system_tail_market(tmp_path: Path):
    srv = TradingSystemService(tmp_path)
    tail = srv.get_tail_market_plan()
    assert "audit" in tail
    assert tail["audit"]["primary_win_rate"] >= 80.0
    assert tail["audit"]["profit_factor"] >= 3.0
    assert tail["audit"]["max_drawdown_pct"] <= 2.0
    assert "tail_picks" in tail


def test_trade_plan_api_routes(tmp_path: Path):
    app = FastAPI()
    app.state.repo = SimpleNamespace(store=SimpleNamespace(data_dir=tmp_path))
    app.include_router(trade_plan_router)
    client = TestClient(app)

    # 市场环境门控
    res = client.get("/api/trade-plan/market-gate")
    assert res.status_code == 200
    data = res.json()
    assert "market_score" in data
    assert "target_pos_max" in data
    assert "max_positions" in data

    # 设置读取与保存
    res_set = client.get("/api/trade-plan/settings")
    assert res_set.status_code == 200
    set_data = res_set.json()
    assert set_data["account_equity"] >= 0

    # 保存设置
    res_post_set = client.post("/api/trade-plan/settings", json={"account_equity": 80000.0})
    assert res_post_set.status_code == 200
    assert res_post_set.json()["account_equity"] == 80000.0

    # 自定义计划 API
    res_custom = client.post("/api/trade-plan/custom", json={
        "symbol": "600519.SH",
        "name": "贵州茅台",
        "buy_price": 1400.0,
        "stop_loss_price": 1330.0,
    })
    assert res_custom.status_code == 200
    assert len(res_custom.json()) == 1

    # 获取自定义计划
    res_list = client.get("/api/trade-plan/custom")
    assert res_list.status_code == 200
    assert len(res_list.json()) == 1

    # 删除自定义计划
    res_del = client.delete("/api/trade-plan/custom/600519.SH")
    assert res_del.status_code == 200
    assert len(res_del.json()) == 0

    # AI Copilot API
    res_copilot = client.get("/api/trade-plan/ai-copilot")
    assert res_copilot.status_code == 200
    c_data = res_copilot.json()
    assert "ai_directive" in c_data
    assert "ai_high_alpha_picks" in c_data

    # Tail Market API
    res_tail = client.get("/api/trade-plan/tail-market")
    assert res_tail.status_code == 200
    t_data = res_tail.json()
    assert "audit" in t_data
    assert "tail_picks" in t_data
