# -*- coding: utf-8 -*-
"""快讯打标 service 测试 —— 方向词典、名称匹配(长名优先)、索引缓存。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import flash_classifier
from app.services.flash_classifier import (
    build_lexicon,
    classify_direction,
    load_lexicon,
    tag_flash_items,
)

_SECTOR_NAMES = ["芯片", "国产芯片概念", "半导体设备", "固态电池", "低空经济"]
_NAME_MAP = {
    "600519.SH": "贵州茅台",
    "688981.SH": "中芯国际",
    "000725.SZ": "京东方A",
    "002594.SZ": "比亚迪",
    "300750.SZ": "宁德时代",
    "000001.SZ": "平安",  # 2 字简称: 噪声太大, 不参与匹配
}


class _Repo:
    def __init__(self, name_map: dict[str, str] | None = None):
        self._name_map = name_map or {}
        self.name_map_calls = 0

    def get_name_map(self, symbols=None):
        self.name_map_calls += 1
        return dict(self._name_map)


@pytest.fixture(autouse=True)
def _clear_cache():
    flash_classifier.invalidate_cache()
    yield
    flash_classifier.invalidate_cache()


def test_classify_direction_bullish_bearish_and_neutral():
    assert classify_direction("某公司中标大额订单，股价涨停") == "bullish"
    assert classify_direction("某公司遭立案调查，股东拟减持") == "bearish"
    assert classify_direction("今日沪深两市成交额较前一交易日小幅波动") == "neutral"
    # 多空同时出现: 命中词多的一方胜出, 平局才判中性
    assert classify_direction("股东拟减持，公司同步公告回购，并上调全年指引") == "bullish"
    assert classify_direction("业绩预亏，随后公告回购") == "neutral"
    assert classify_direction("") == "neutral"


def test_build_lexicon_prefers_longest_sector_name():
    lexicon = build_lexicon(_SECTOR_NAMES, _NAME_MAP)

    assert [m for m in lexicon.sector_pattern.findall("国产芯片概念指数走强")] == ["国产芯片概念"]
    assert lexicon.sector_pattern.findall("芯片板块回暖") == ["芯片"]


def test_build_lexicon_ignores_short_stock_names():
    lexicon = build_lexicon(_SECTOR_NAMES, _NAME_MAP)

    assert "平安" not in lexicon.symbol_by_name
    assert lexicon.symbol_by_name["贵州茅台"] == "600519.SH"
    assert lexicon.stock_name_count == len(_NAME_MAP) - 1


def test_tag_flash_items_adds_direction_sectors_and_symbols():
    lexicon = build_lexicon(_SECTOR_NAMES, _NAME_MAP)
    items = [
        {
            "id": "1",
            "time": "2026-09-19 10:30:00",
            "tag": "要闻",
            "title": "中芯国际获批新一轮扩产，国产芯片概念涨停潮",
            "content": "公司公告称新增产线已投产，半导体设备订单饱满。",
        },
        {
            "id": "2",
            "time": "2026-09-19 09:10:00",
            "tag": "公司",
            "title": "某公司股东拟减持不超过 2% 股份",
            "content": "固态电池业务尚未贡献收入。",
        },
    ]

    tagged = tag_flash_items(items, lexicon)

    assert tagged[0]["direction"] == "bullish"
    assert "国产芯片概念" in tagged[0]["sectors"]
    assert {"name": "中芯国际", "symbol": "688981.SH"} in tagged[0]["symbols"]
    assert tagged[1]["direction"] == "bearish"
    assert tagged[1]["sectors"] == ["固态电池"]
    # 原对象不被修改
    assert "direction" not in items[0]


def test_tag_flash_items_keeps_fallback_marker_and_handles_missing_fields():
    lexicon = build_lexicon(_SECTOR_NAMES, _NAME_MAP)

    tagged = tag_flash_items(
        [{"id": "f_1", "is_fallback": True, "title": "", "content": ""}],
        lexicon,
    )

    assert tagged[0]["is_fallback"] is True
    assert tagged[0]["direction"] == "neutral"
    assert tagged[0]["sectors"] == [] and tagged[0]["symbols"] == []


def test_tag_flash_items_caps_match_count():
    lexicon = build_lexicon(_SECTOR_NAMES, _NAME_MAP)
    text = "芯片 国产芯片概念 半导体设备 固态电池 低空经济 贵州茅台 中芯国际"

    tagged = tag_flash_items([{"title": text, "content": ""}], lexicon)

    assert len(tagged[0]["sectors"]) == 5
    assert len(tagged[0]["symbols"]) == 2


def test_load_lexicon_caches_until_invalidated(monkeypatch):
    repo = _Repo(_NAME_MAP)
    monkeypatch.setattr(flash_classifier, "_sector_names", lambda _repo, days=7: set(_SECTOR_NAMES))

    first = load_lexicon(repo)
    second = load_lexicon(repo)

    assert first is second
    assert repo.name_map_calls == 1

    flash_classifier.invalidate_cache()
    third = load_lexicon(repo)

    assert third is not first
    assert repo.name_map_calls == 2


def test_load_lexicon_tolerates_missing_name_map(monkeypatch):
    class _BrokenRepo:
        def get_name_map(self, symbols=None):
            raise RuntimeError("维表不可用")

    monkeypatch.setattr(flash_classifier, "_sector_names", lambda _repo, days=7: set(_SECTOR_NAMES))

    lexicon = load_lexicon(_BrokenRepo())
    # 名称缺失只影响标的匹配, 板块与方向打标仍然可用
    assert lexicon.stock_pattern is None
    assert classify_direction("固态电池板块大涨") == "bullish"


def test_sector_names_collects_concept_and_industry(monkeypatch):
    from app.services import rps_rotation

    def fake_matrix(repo, days=12, kind="concept", level=None):
        assert level == 2 if kind == "industry" else level is None
        names = ["人工智能"] if kind == "concept" else ["电子"]
        return {"dates": ["2026-09-19"], "columns": {"2026-09-19": [[n, 0.01] for n in names]}}

    monkeypatch.setattr(rps_rotation, "build_rps_rotation", fake_matrix)

    assert flash_classifier._sector_names(SimpleNamespace(), days=7) == {"人工智能", "电子"}


def test_sector_names_survives_one_dimension_failure(monkeypatch):
    from app.services import rps_rotation

    def fake_matrix(repo, days=12, kind="concept", level=None):
        if kind == "concept":
            raise RuntimeError("概念维度不可用")
        return {"dates": ["2026-09-19"], "columns": {"2026-09-19": [["电子", 0.01]]}}

    monkeypatch.setattr(rps_rotation, "build_rps_rotation", fake_matrix)

    assert flash_classifier._sector_names(SimpleNamespace(), days=7) == {"电子"}
