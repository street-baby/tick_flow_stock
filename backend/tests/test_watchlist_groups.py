"""自选股分组与板块分类测试。"""
from pathlib import Path
import pytest
from app.services import watchlist
from app.services.sector_watchlist import select_sector_core_stocks, populate_sector_watchlist


def test_watchlist_groups_crud(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(watchlist, "_path", lambda: tmp_path / "watchlist.parquet")

    # 初始状态
    assert watchlist.list_symbols() == []
    groups = watchlist.list_groups()
    assert any(g["name"] == "全部" for g in groups)

    # 添加不同分组
    watchlist.add("000001.SZ", note="平安银行", group="银行")
    watchlist.add("600519.SH", note="贵州茅台", group="食品饮料")
    watchlist.add("000823.SZ", note="超声电子", group="电子")

    assert len(watchlist.list_symbols()) == 3
    assert len(watchlist.list_symbols(group="银行")) == 1
    assert watchlist.list_symbols(group="银行")[0]["symbol"] == "000001.SZ"

    groups = watchlist.list_groups()
    names = [g["name"] for g in groups]
    assert "银行" in names
    assert "食品饮料" in names
    assert "电子" in names

    # 移除某组
    watchlist.remove("000001.SZ", group="银行")
    assert len(watchlist.list_symbols(group="银行")) == 0
    assert len(watchlist.list_symbols()) == 2

    # 清空某组
    watchlist.clear(group="电子")
    assert len(watchlist.list_symbols(group="电子")) == 0
    assert len(watchlist.list_symbols()) == 1


def test_sector_core_stocks_selection():
    res = select_sector_core_stocks()
    assert len(res) > 20
    assert "电子" in res
    assert "计算机" in res
    assert "通信" in res
    assert "电力设备" in res
    # 每组 3~5 只核心股票
    assert 3 <= len(res["电子"]) <= 5
    for stock in res["电子"]:
        assert "symbol" in stock
        assert "name" in stock
        assert "tag" in stock
