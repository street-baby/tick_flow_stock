# -*- coding: utf-8 -*-
"""板块驱动归因测试 —— 四维分解、权重归一化、快讯匹配与 AI 输出校验。

全部离线: 快讯池用内存夹具, 外围快照用本地 parquet 夹具, 盘面用内存矩阵。
"""
from __future__ import annotations

import polars as pl
import pytest

from app.services import sector_drivers
from app.services.sector_drivers import (
    build_drivers,
    data_headline,
    flash_from_ids,
    is_policy_text,
    market_text,
    match_news_scored,
    overseas_snapshot,
    overseas_text,
    parse_ai_drivers,
    pool_for_prompt,
    sector_tokens,
)

MATRIX = {
    "dates": ["2026-09-19", "2026-09-18", "2026-09-17"],
    "columns": {
        "2026-09-19": [["半导体设备", 0.0353], ["先进封装", 0.0398], ["国产芯片概念", 0.0431], ["白酒", -0.012]],
        "2026-09-18": [["国产芯片概念", 0.021], ["半导体设备", 0.011], ["先进封装", 0.009], ["白酒", -0.004]],
        "2026-09-17": [["国产芯片概念", 0.007], ["半导体设备", -0.002], ["先进封装", 0.004], ["白酒", 0.001]],
    },
    "concept_count": 4,
}

# 快讯池: 一条命中板块成分股(消息面), 一条命中板块名且属政策口径, 两条与板块无关
POOL = [
    {
        "id": "n1",
        "time": "2026-09-20 09:35:00",
        "title": "中芯国际宣布新产线扩产，设备订单排至明年",
        "content": "公司追加设备采购，用于先进制程产能建设。",
        "source": "同花顺",
        "url": "https://example.com/a",
    },
    {
        "id": "n2",
        "time": "2026-09-20 11:46:00",
        "title": "广东战新一号基金出资约165亿元投向半导体设备",
        "content": "省级产业基金落地，专项资金支持国产替代。",
        "source": "财联社",
        "url": "https://example.com/b",
    },
    {
        "id": "n3",
        "time": "2026-09-20 12:08:00",
        "title": "白酒动销数据低于预期",
        "content": "渠道反馈中秋旺季回款不及预期。",
        "source": "东方财富",
        "url": "https://example.com/c",
    },
    {
        "id": "n4",
        "time": "2026-09-20 13:00:00",
        "title": "无关的海外地缘新闻",
        "content": "某国大使馆发布旅行提示。",
        "source": "富途",
        "url": "",
    },
]

CARD = {
    "name": "半导体设备",
    "change_pct": 0.0353,
    "count": 12,
    "up_count": 11,
    "down_count": 1,
    "amount": 3.2e9,
    "leader": {"symbol": "688981.SH", "name": "中芯国际", "change_pct": 0.0871},
    "window_pct": 0.0297,
    "stocks": [{"symbol": "688981.SH", "name": "中芯国际", "change_pct": 0.0871}],
}


def test_sector_tokens_strip_generic_suffix_and_keep_ngrams():
    tokens = sector_tokens("国产芯片概念")

    assert "国产芯片概念" in tokens  # 全名保留(命中即最强相关)
    assert "国产芯片" in tokens  # 主干: 去掉「概念」后缀
    assert "芯片" in tokens
    # 不允许从「概念」后缀里生成检索词, 否则任何快讯都会被判定相关
    assert "概念" not in tokens
    assert sector_tokens("") == []


def test_is_policy_text_distinguishes_policy_from_company_news():
    assert is_policy_text("省级产业基金落地，加码半导体")
    assert is_policy_text("工信部印发行动方案")
    assert not is_policy_text("长鑫科技第五代平台正式量产")


def test_match_news_ranks_by_relevance_and_drops_irrelevant():
    matched = match_news_scored(POOL, "半导体设备", ["中芯国际"])

    titles = [item["title"] for item in matched]
    assert "中芯国际宣布新产线扩产，设备订单排至明年" in titles
    assert "广东战新一号基金出资约165亿元投向半导体设备" in titles
    # 板块名命中(权重更高) 必须排在仅命中成分股的前面
    assert titles[0].startswith("广东战新一号基金")
    # 与板块无关的白酒/地缘新闻不得被带进关联快讯
    assert all("白酒" not in title and "地缘" not in title for title in titles)


def test_match_news_is_conservative_without_name_overlap():
    """名称毫无重叠的快讯不会被硬拉进关联快讯。

    「长鑫存储量产」与「国产芯片概念」在语义上相关, 但两个板块名/成分股名都没出现;
    这种语义关联只能靠 AI 在快讯池里选(flash_ids), 规则路径宁缺勿滥。
    """
    pool = [{
        "id": "s1",
        "time": "2026-09-20 09:35:00",
        "title": "长鑫存储第五代技术平台正式量产",
        "content": "大容量 LPDDR5X 产品同步展出。",
        "source": "同花顺",
        "url": "",
    }]

    assert match_news_scored(pool, "国产芯片概念", ["中芯国际"]) == []


def test_two_char_fragment_alone_cannot_pull_news_in():
    """二字片段单独命中就是噪声 —— 实测过德大选新闻被拉进「国家大基金持股」。"""
    pool = [
        {"id": "z1", "time": "2026-09-21 01:20:00", "title": "德国总理默茨：德国必须成为一个开启新时代的国家", "content": "", "source": "富途", "url": ""},
        {"id": "z2", "time": "2026-09-20 23:46:00", "title": "花旗集团CEO表示 人工智能的瓶颈已从芯片转向能源", "content": "", "source": "富途", "url": ""},
        {"id": "z3", "time": "2026-09-20 12:48:00", "title": "蔚来：汽车豪华品牌定价权正转至中国品牌", "content": "", "source": "东方财富", "url": ""},
    ]

    assert match_news_scored(pool, "国家大基金持股", []) == []
    assert match_news_scored(pool, "汽车芯片", []) == []


def test_sector_words_are_only_matched_in_the_title():
    """正文里顺带提到板块词的宏观言论不算催化; 正文提到成分股名仍然算数。"""
    content_only = [{
        "id": "c1",
        "time": "2026-09-20 23:46:00",
        "title": "某机构发布年度策略展望",
        "content": "报告认为存储芯片与算力需求将在明年继续扩张。",
        "source": "东方财富",
        "url": "",
    }]
    assert match_news_scored(content_only, "存储芯片", ["兆易创新"]) == []

    body_member = [{
        "id": "c2",
        "time": "2026-09-20 15:31:00",
        "title": "某机构发布年度策略展望",
        "content": "报告重点推荐兆易创新等标的。",
        "source": "东方财富",
        "url": "",
    }]
    matched = match_news_scored(body_member, "存储芯片", ["兆易创新"])
    assert len(matched) == 1 and matched[0]["_hits"] == ["兆易创新(正文)"]


def test_match_news_detects_member_stock_names():
    pool = [{**POOL[3], "title": "中芯国际公告新增产线", "content": ""}]

    matched = match_news_scored(pool, "半导体设备", ["中芯国际"])

    assert len(matched) == 1
    assert matched[0]["title"] == "中芯国际公告新增产线"
    assert matched[0]["category"] == "news"


def test_weights_normalize_to_exactly_100():
    weights = sector_drivers._weights({"news": 4.0, "policy": 2.0, "market": 5.0, "overseas": 3.0})

    assert sum(weights.values()) == 100
    assert set(weights) == {"news", "policy", "market", "overseas"}
    assert weights["news"] > weights["policy"]
    assert sector_drivers._weights({}) == {}
    assert sector_drivers._weights({"news": 0.0}) == {}


def test_market_text_uses_real_peers_and_window_cumulative():
    text, raw = market_text(CARD, MATRIX, 7, "bullish")

    assert "当日板块均值 +3.53%" in text
    assert "中芯国际 +8.71% 领涨" in text
    assert "先进封装" in text  # 当日涨幅榜首, 与参考设计一致的「同类联动」写法
    assert "近 7 日累计 +2.97%" in text
    assert 1.0 <= raw <= 5.5


_OVERSEAS = [
    {"market": "us", "market_label": "美股", "name": "纳斯达克", "change_pct": 0.0289, "date": "2026-09-18"},
    {"market": "hk", "market_label": "港股", "name": "恒生科技指数", "change_pct": 0.021, "date": "2026-09-18"},
]


def test_overseas_text_absent_without_local_index_data():
    assert overseas_text([], "bullish") is None

    text, raw = overseas_text(_OVERSEAS, "bullish", "2026-09-19")
    assert "纳斯达克 +2.89%" in text
    assert "恒生科技指数 +2.10%" in text
    assert raw == pytest.approx(3.0)

    # 方向背离时必须如实说, 不能把外围硬说成顺风
    bear_text, _ = overseas_text(_OVERSEAS, "bearish", "2026-09-19")
    assert "不一致" in bear_text


def test_overseas_text_drops_stale_index_data():
    """本地指数可能很久没同步: 过期数据必须整维度不出现, 不能当「隔夜」展示。"""
    stale = [{**_OVERSEAS[0], "date": "2026-08-24"}]

    assert overseas_text(stale, "bullish", "2026-09-19") is None
    # 数据日比简报日更晚(未来日期)同样不可信
    assert overseas_text(_OVERSEAS, "bullish", "2026-09-01") is None
    # 超过两天就不是「隔夜」, 文案要用真实日期
    late = [{**_OVERSEAS[0], "date": "2026-09-16"}]
    late_text, _ = overseas_text(late, "bullish", "2026-09-19")
    assert late_text.startswith("09-16 收盘")


def test_overseas_snapshot_reads_local_parquet_and_tolerates_missing(tmp_path):
    assert overseas_snapshot(tmp_path) == []

    daily = tmp_path / "kline_index_daily_us"
    daily.mkdir(parents=True)
    pl.DataFrame({
        "date": ["2026-09-18", "2026-09-19"],
        "close": [100.0, 102.89],
        "change_pct": [0.0, 0.0289],
    }).write_parquet(daily / "latest_IXIC.parquet")

    snapshot = overseas_snapshot(tmp_path)
    assert [q["name"] for q in snapshot] == ["纳斯达克"]
    # index_sync_market 返回百分数(2.89), 本模块必须换算成小数制(0.0289)
    assert snapshot[0]["change_pct"] == pytest.approx(0.0289)
    assert snapshot[0]["date"] == "2026-09-19"


def test_build_drivers_splits_policy_and_news_and_caps_flash():
    result = build_drivers(
        CARD,
        pool=POOL,
        matrix=MATRIX,
        days=7,
        direction="bullish",
        overseas=_OVERSEAS,
        member_names=["中芯国际"],
        as_of="2026-09-19",
    )

    assert sum(driver["weight"] for driver in result["drivers"]) == 100
    keys = [driver["key"] for driver in result["drivers"]]
    assert keys[0] == "news" and "policy" in keys and "market" in keys
    by_key = {driver["key"]: driver for driver in result["drivers"]}
    # 政策类快讯不得混进「消息面」, 公司事件也不得混进「政策产业」
    assert "中芯国际" in by_key["news"]["text"]
    assert "基金" in by_key["policy"]["text"]
    assert len(result["flash"]) <= 4
    # 榜首是政策类快讯 → 标题必须说「政策面」而不是笼统的「消息面」
    assert result["headline"].startswith("广东战新一号基金")
    assert "政策面利好半导体设备" in result["headline"]


def test_build_drivers_without_news_or_overseas_still_reports_market():
    result = build_drivers(CARD, pool=[], matrix=MATRIX, days=7, direction="bullish")

    assert [driver["key"] for driver in result["drivers"]] == ["market"]
    assert result["drivers"][0]["weight"] == 100
    assert result["flash"] == []
    assert "当日板块均值" in result["headline"]
    assert "消息面" not in result["headline"]


def test_flash_from_ids_rejects_out_of_range_and_non_integer():
    flash = flash_from_ids(POOL, [0, "1", 99, -3, None, "abc", 1])

    assert [item["id"] for item in flash] == ["n1", "n2"]  # 重复编号只留一次
    assert flash[0]["time"] == "2026-09-20 09:35:00"
    assert flash[1]["category"] == "policy"


def test_parse_ai_drivers_validates_and_normalizes():
    drivers = parse_ai_drivers([
        {"key": "news", "weight": 60, "text": "量产落地"},
        {"key": "policy", "weight": 40, "text": "产业基金加码"},
        {"key": "unknown", "weight": 90, "text": "不该出现"},
        {"key": "market", "weight": 10, "text": ""},
    ])

    assert [driver["key"] for driver in drivers] == ["news", "policy"]
    assert [driver["weight"] for driver in drivers] == [60, 40]
    assert drivers[0]["label"] == "消息面"


def test_parse_ai_drivers_falls_back_when_weights_all_zero():
    assert parse_ai_drivers([{"key": "news", "weight": 0, "text": "文案"}]) == []
    assert parse_ai_drivers("not-a-list") == []
    assert parse_ai_drivers(None) == []


def test_data_headline_states_facts_without_inventing_causes():
    no_news = data_headline({**CARD, "leader": {"name": "中芯国际", "change_pct": 0.0871}}, [], "bullish")

    assert "中芯国际 +8.71% 领涨" in no_news
    assert "消息面" not in no_news and "政策面" not in no_news


def test_pool_for_prompt_numbers_items_for_ai_reference():
    lines = pool_for_prompt(POOL).splitlines()

    assert lines[0].startswith("[0] 09-20 09:35")
    assert lines[1].startswith("[1]")
    assert len(lines) == len(POOL)
