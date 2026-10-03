# -*- coding: utf-8 -*-
"""板块简报 service 测试 —— 利好/利空排序、热度、关联标的、AI 文案缓存与降级。

夹具照 tests/test_sector_monitor.py: SimpleNamespace 假 repo + ExtConfigStore 写临时 parquet,
不触网、不依赖真实 data/ 目录。
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from types import SimpleNamespace

import polars as pl
import pytest

from app.services import ai_provider, flash_classifier, rps_rotation, sector_brief
from app.services.ext_data import ExtConfig, ExtConfigStore, ExtField
from app.services.sector_brief import (
    SectorBriefAIError,
    _heat,
    _parse_narratives,
    _rank_map,
    build_sector_brief,
    narrate_sector_brief,
)

LATEST = date(2026, 9, 19)


class _Repo:
    """最小 repo 替身: 只提供板块简报与 rps 矩阵用到的接口。"""

    def __init__(self, data_dir, latest: pl.DataFrame, history: pl.DataFrame, names: dict[str, str] | None = None):
        self.store = SimpleNamespace(data_dir=data_dir)
        self._rows = latest
        self._history = history
        self._enriched_history_cache = history
        self._names = names or {}
        self.name_map_calls = 0

    def get_enriched_latest(self) -> tuple[pl.DataFrame, date | None]:
        return self._rows, LATEST

    def get_enriched_range(self, start, end, symbols=None, columns=None):
        # 与真实 repo 一致: 缓存不覆盖请求区间末端时返回 None, 其余情况返回区间内的数据。
        df = self._history
        if df is None or df.is_empty() or df["date"].max() < end:
            return None
        out = df.filter((pl.col("date") >= start) & (pl.col("date") <= end))
        if columns:
            keep = [c for c in columns if c in out.columns]
            out = out.select(keep)
        return out.sort(["symbol", "date"])

    def get_name_map(self, symbols=None):
        self.name_map_calls += 1
        if symbols is None:
            return dict(self._names)
        return {s: self._names.get(s, s) for s in symbols}


@pytest.fixture(autouse=True)
def _clear_caches():
    """三个 service 都是进程级缓存, 用例之间必须隔离(否则 ext 映射串台)。"""
    for module in (sector_brief, flash_classifier, rps_rotation):
        module.invalidate_cache()
    rps_rotation._map_cache.clear()  # 维度映射缓存无公开清理入口
    rps_rotation._map_ts.clear()
    yield
    for module in (sector_brief, flash_classifier, rps_rotation):
        module.invalidate_cache()
    rps_rotation._map_cache.clear()
    rps_rotation._map_ts.clear()


def _write_concept_ext(tmp_path, mapping: dict[str, list[str]]) -> None:
    config = ExtConfig(
        id="concept_test",
        label="概念测试",
        mode="snapshot",
        fields=[
            ExtField("symbol", "string", "标的代码"),
            ExtField("concept", "string", "所属概念"),
        ],
    )
    ExtConfigStore(tmp_path).upsert(config)
    ext_dir = tmp_path / "ext_data" / config.id
    ext_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({
        "symbol": list(mapping.keys()),
        "concept": [";".join(values) for values in mapping.values()],
    }).write_parquet(ext_dir / "part.parquet")


# 强势概念 4 只(当日大涨, 且窗口内排名持续上行); 弱势概念 3 只(当日下跌, 排名下滑);
# 小概念只有 2 只成分股 → 必须被剔除(噪声板块不霸榜)
_CONCEPT_MAP = {
    "A1.SZ": ["强势概念"],
    "A2.SZ": ["强势概念"],
    "A3.SZ": ["强势概念"],
    "A4.SZ": ["强势概念"],
    "B1.SZ": ["弱势概念"],
    "B2.SZ": ["弱势概念"],
    "B3.SZ": ["弱势概念"],
    "C1.SZ": ["小概念"],
    "C2.SZ": ["小概念"],
}

_NAMES = {
    "A1.SZ": "甲一", "A2.SZ": "甲二", "A3.SZ": "甲三", "A4.SZ": "甲四",
    "B1.SZ": "乙一", "B2.SZ": "乙二", "B3.SZ": "乙三",
    "C1.SZ": "丙一", "C2.SZ": "丙二",
}

_LATEST_PCT = {
    "A1.SZ": 0.052, "A2.SZ": 0.041, "A3.SZ": 0.028, "A4.SZ": 0.019,
    "B1.SZ": -0.031, "B2.SZ": -0.022, "B3.SZ": -0.014,
    "C1.SZ": 0.099, "C2.SZ": 0.088,
}


def _history_frame(days: int = 8) -> pl.DataFrame:
    """构造窗口内逐日 change_pct。

    强势概念从低位(-5pct)线性爬到最新日, 弱势概念从高位(+5pct)线性回落,
    小概念始终在低位徘徊 —— 这样窗口首末两列的排名会真正互换,
    能验证排名变化与热度方向。
    """
    symbols, dates, pcts = [], [], []
    for offset in range(days):
        day = LATEST - timedelta(days=(days - 1 - offset) * 3)
        ratio = offset / (days - 1)
        for symbol, latest_pct in _LATEST_PCT.items():
            if symbol.startswith("A"):
                pct = (latest_pct - 0.05) + 0.05 * ratio
            elif symbol.startswith("B"):
                pct = (latest_pct + 0.05) - 0.05 * ratio
            else:
                pct = latest_pct * 0.2
            symbols.append(symbol)
            dates.append(day)
            pcts.append(pct)
    return pl.DataFrame({"symbol": symbols, "date": dates, "change_pct": pcts})


def _repo(tmp_path, with_latest: bool = True, with_ext: bool = True) -> _Repo:
    if with_ext:
        _write_concept_ext(tmp_path, _CONCEPT_MAP)
    if not with_latest:
        empty = pl.DataFrame({"symbol": [], "name": [], "change_pct": [], "amount": [], "close": []})
        return _Repo(tmp_path, empty, _history_frame(), _NAMES)
    latest = pl.DataFrame({
        "symbol": list(_LATEST_PCT.keys()),
        "change_pct": list(_LATEST_PCT.values()),
        "amount": [1.2e9, 8.0e8, 5.0e8, 3.0e8, 4.0e8, 3.0e8, 2.0e8, 9.0e7, 8.0e7],
        "close": [10.0] * len(_LATEST_PCT),
    })
    return _Repo(tmp_path, latest, _history_frame(), _NAMES)


def test_build_sector_brief_orders_bullish_desc_and_bearish_asc(tmp_path):
    brief = build_sector_brief(_repo(tmp_path), kind="concept", top_n=5)

    assert brief["as_of"] == LATEST.isoformat()
    assert brief["kind"] == "concept"
    # 夹具只有 3 个概念(真实环境 387 个), 榜单会整体覆盖, 因此只断言排序方向
    assert brief["bullish"][0]["name"] == "强势概念"
    assert brief["bearish"][0]["name"] == "弱势概念"
    assert [c["change_pct"] for c in brief["bullish"]] == sorted(
        [c["change_pct"] for c in brief["bullish"]], reverse=True
    )
    assert brief["bullish"][0]["change_pct"] > 0 > brief["bearish"][0]["change_pct"]
    # 成分股 < 3 的"小概念"当日涨幅最高, 也必须被剔除
    assert all(card["name"] != "小概念" for card in brief["bullish"] + brief["bearish"])


def test_build_sector_brief_tracks_rank_change_and_heat(tmp_path):
    brief = build_sector_brief(_repo(tmp_path), kind="concept", top_n=5)
    up = brief["bullish"][0]
    down = brief["bearish"][0]

    assert up["rank"] == 1
    assert up["prev_rank"] is not None and up["prev_rank"] > up["rank"]
    assert up["rank_change"] == up["prev_rank"] - up["rank"] > 0
    assert down["rank_change"] < 0
    assert 0 <= down["heat"] <= 100
    # 强势板块涨幅更大 + 排名上行 → 热度必须更高
    assert up["heat"] > down["heat"]


def test_heat_is_monotonic_in_change_and_rank_improvement():
    assert _heat(0.05, 10, 50) > _heat(0.01, 10, 50)
    assert _heat(0.02, 40, 100) > _heat(0.02, 2, 100)
    # 排名信息缺失时取中性, 不假装排名大幅改善
    assert _heat(0.0, None, None) == 20
    assert _heat(0.05, 10, 50) <= 100


def test_rank_map_treats_missing_prev_rank_as_none():
    matrix = {"dates": ["2026-09-19", "2026-09-18"], "columns": {
        "2026-09-19": [["新概念", 0.03], ["老概念", 0.01]],
        "2026-09-18": [["老概念", 0.02]],
    }}
    ranks = _rank_map(matrix)

    assert ranks["老概念"] == (1, 2)
    assert ranks["新概念"] == (None, 1)
    assert _rank_map({"dates": [], "columns": {}}) == {}


def test_card_picks_associated_stocks_with_names(tmp_path):
    brief = build_sector_brief(_repo(tmp_path), kind="concept", top_n=5)

    bull_stocks = brief["bullish"][0]["stocks"]
    assert [s["symbol"] for s in bull_stocks] == ["A1.SZ", "A2.SZ", "A3.SZ"]
    assert bull_stocks[0]["name"] == "甲一"
    assert bull_stocks[0]["change_pct"] == pytest.approx(0.052)

    bear_stocks = brief["bearish"][0]["stocks"]
    # 利空取跌幅最大的 3 只, 跌幅居前者在前
    assert [s["symbol"] for s in bear_stocks] == ["B1.SZ", "B2.SZ", "B3.SZ"]
    assert bear_stocks[0]["change_pct"] == pytest.approx(-0.031)


def test_logic_stats_states_rank_and_member_facts(tmp_path):
    card = build_sector_brief(_repo(tmp_path), kind="concept", top_n=5)["bullish"][0]

    assert "近 7 个交易日板块均值 +3.50%" in card["logic_stats"]
    assert "排名由第 3 位升至第 1 位" in card["logic_stats"]
    assert "4 只成分股中 4 只上涨、0 只下跌" in card["logic_stats"]
    assert "领涨 甲一 +5.20%" in card["logic_stats"]
    assert card["ai_logic"] is None


def test_no_data_sentinel_rows_are_excluded_from_sector_stats(tmp_path):
    """停牌/无数据标的(close=0, change_pct=-1.0)不得参与板块均值与关联标的。

    真实数据里这类行会把板块均值算成 -100%, 让利空榜单彻底失真。
    """
    _write_concept_ext(tmp_path, {
        "A1.SZ": ["强势概念"], "A2.SZ": ["强势概念"], "A3.SZ": ["强势概念"], "A4.SZ": ["强势概念"],
        "B1.SZ": ["弱势概念"], "B2.SZ": ["弱势概念"], "B3.SZ": ["弱势概念"], "B4.SZ": ["弱势概念"],
        "C1.SZ": ["小概念"], "C2.SZ": ["小概念"],
    })
    latest = pl.DataFrame({
        "symbol": ["A1.SZ", "A2.SZ", "A3.SZ", "A4.SZ", "B1.SZ", "B2.SZ", "B3.SZ", "B4.SZ", "C1.SZ", "C2.SZ"],
        "change_pct": [0.052, 0.041, 0.028, 0.019, -0.031, -0.022, -0.014, -1.0, 0.099, 0.088],
        "amount": [1.2e9, 8.0e8, 5.0e8, 3.0e8, 4.0e8, 3.0e8, 2.0e8, 0.0, 9.0e7, 8.0e7],
        # B4 是停牌哨兵行: close=0 → 必须整行剔除
        "close": [10.0, 10.0, 10.0, 10.0, 9.0, 9.0, 9.0, 0.0, 20.0, 20.0],
    })
    repo = _Repo(tmp_path, latest, _history_frame(), _NAMES)

    brief = build_sector_brief(repo, kind="concept", top_n=5)
    bear = brief["bearish"][0]

    assert bear["count"] == 3
    assert bear["change_pct"] > -0.05
    assert all((s["change_pct"] or 0) > -0.1 for s in bear["stocks"])
    assert "B4.SZ" not in [s["symbol"] for s in bear["stocks"]]


def test_empty_enriched_returns_empty_brief_without_error(tmp_path):
    brief = build_sector_brief(_repo(tmp_path, with_latest=False), kind="concept", top_n=5)

    assert brief["as_of"] is None
    assert brief["bullish"] == [] and brief["bearish"] == []
    assert brief["ai_status"] == "missing"


def test_missing_ext_dimension_returns_empty_lists(tmp_path):
    brief = build_sector_brief(_repo(tmp_path, with_ext=False), kind="concept", top_n=5)

    assert brief["bullish"] == []
    assert brief["bearish"] == []
    assert brief["as_of"] == LATEST.isoformat()


def test_brief_cache_key_follows_latest_trading_day(tmp_path):
    repo = _repo(tmp_path)
    first = build_sector_brief(repo, kind="concept", top_n=5)
    assert first["as_of"] == LATEST.isoformat()

    # 新交易日(缓存 key 变化)必须重新计算, 而不是返回上一天的缓存
    repo.get_enriched_latest = lambda: (repo._rows, LATEST + timedelta(days=1))
    second = build_sector_brief(repo, kind="concept", top_n=5)
    assert second["as_of"] == (LATEST + timedelta(days=1)).isoformat()


async def test_narrate_generates_then_reuses_cache(tmp_path, monkeypatch):
    repo = _repo(tmp_path)
    calls: list[list[dict]] = []

    async def fake_generate(messages, **kwargs):
        calls.append(list(messages))
        # 一次请求只包含一边板块(推理型模型靠拆分请求才能吐出正文)
        if "利好板块" in messages[1]["content"]:
            return json.dumps(
                [{"name": "强势概念", "logic": "窗口内排名升至首位，资金关注度提升。"}],
                ensure_ascii=False,
            )
        return json.dumps(
            [{"name": "弱势概念", "logic": "排名下滑，成分股普遍走弱。"}], ensure_ascii=False
        )

    monkeypatch.setattr(ai_provider, "generate_ai_text", fake_generate)
    monkeypatch.setattr(ai_provider, "ai_configured", lambda *a, **k: True)

    first = await narrate_sector_brief(repo, kind="concept", top_n=5)
    assert first["ai_status"] == "generated"
    assert first["bullish"][0]["ai_logic"] == "窗口内排名升至首位，资金关注度提升。"
    assert first["bearish"][0]["ai_logic"] == "排名下滑，成分股普遍走弱。"
    # 利好/利空各一次调用, 且每次只带自己的那一边
    assert len(calls) == 2
    assert "利空板块" not in calls[0][1]["content"]
    assert "利好板块" not in calls[1][1]["content"]

    store = json.loads((tmp_path / "user_data" / "sector_brief_ai.json").read_text(encoding="utf-8"))
    entry = store[f"{LATEST.isoformat()}|concept|{sector_brief._AI_SCHEMA}"]
    assert entry["sectors"]["强势概念"]["logic"].startswith("窗口内排名")
    assert entry["generated_at"]

    # 同一交易日第二次调用: 命中缓存, 不再消耗 token
    second = await narrate_sector_brief(repo, kind="concept", top_n=5)
    assert second["ai_status"] == "cached"
    assert len(calls) == 2

    # GET 路径同样能读到已落盘的 AI 文案
    read_brief = build_sector_brief(repo, kind="concept", top_n=5)
    assert read_brief["ai_status"] == "cached"
    assert read_brief["bearish"][0]["ai_logic"] == "排名下滑，成分股普遍走弱。"


def test_parse_narratives_handles_markdown_fence_and_preamble():
    raw = '好的，以下是我根据数据给出的分析：\n```json\n[{"name": "强势概念", "logic": "逻辑 A"}]\n```\n如需展开可以继续说。'

    assert _parse_narratives(raw) == {
        "强势概念": {"headline": "", "logic": "逻辑 A", "drivers": [], "flash_ids": []}
    }


def test_parse_narratives_keeps_rich_fields_and_cleans_bad_types():
    raw = (
        '[{"name": "强势概念", "headline": "资金共振", "logic": "逻辑 A",'
        ' "drivers": [{"key": "news", "weight": 40, "text": "量产"}], "flash_ids": [1, 2],'
        ' "drivers_typo": 1},'
        ' {"name": "弱势概念", "logic": "逻辑 B", "drivers": "not-a-list", "flash_ids": {"a": 1}}]'
    )

    parsed = _parse_narratives(raw)

    assert parsed["强势概念"]["headline"] == "资金共振"
    assert parsed["强势概念"]["drivers"] == [{"key": "news", "weight": 40, "text": "量产"}]
    assert parsed["强势概念"]["flash_ids"] == [1, 2]
    # 非法类型一律清成空列表, 不能把 dict 当编号列表往下传
    assert parsed["弱势概念"]["drivers"] == []
    assert parsed["弱势概念"]["flash_ids"] == []


def test_parse_narratives_returns_nothing_on_garbage_or_incomplete_items():
    assert _parse_narratives("抱歉，我无法完成这个请求。") == {}
    assert _parse_narratives('```json\n[{"name": "甲概念"}]\n```') == {}
    assert _parse_narratives("") == {}


async def test_narrate_partial_reply_keeps_data_text_for_missing_sectors(tmp_path, monkeypatch):
    async def partial(messages, **kwargs):
        return '[{"name": "强势概念", "logic": "只解释了这个板块"}]'

    monkeypatch.setattr(ai_provider, "ai_configured", lambda *a, **k: True)
    monkeypatch.setattr(ai_provider, "generate_ai_text", partial)

    brief = await narrate_sector_brief(_repo(tmp_path), kind="concept", top_n=5)

    assert brief["bullish"][0]["ai_logic"] == "只解释了这个板块"
    # 未覆盖的板块不编造 AI 文案, 继续用数据派生文案
    assert brief["bearish"][0]["ai_logic"] is None
    assert brief["bearish"][0]["logic_stats"]


async def test_narrate_raises_on_empty_ai_reply(tmp_path, monkeypatch):
    async def blank(messages, **kwargs):
        return "   "

    monkeypatch.setattr(ai_provider, "ai_configured", lambda *a, **k: True)
    monkeypatch.setattr(ai_provider, "generate_ai_text", blank)

    # 推理型模型吃完全部输出预算时会返回空正文: 必须报出真实原因, 不能笼统说无法解析
    with pytest.raises(SectorBriefAIError, match="推理"):
        await narrate_sector_brief(_repo(tmp_path), kind="concept", top_n=5)


async def test_narrate_raises_when_ai_not_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_provider, "ai_configured", lambda *a, **k: False)
    monkeypatch.setattr(ai_provider, "generate_ai_text", pytest.fail)  # 不应被调用

    with pytest.raises(SectorBriefAIError):
        await narrate_sector_brief(_repo(tmp_path), kind="concept", top_n=5)


async def test_narrate_raises_when_ai_call_fails(tmp_path, monkeypatch):
    async def boom(messages, **kwargs):
        raise RuntimeError("upstream 500")

    monkeypatch.setattr(ai_provider, "ai_configured", lambda *a, **k: True)
    monkeypatch.setattr(ai_provider, "generate_ai_text", boom)

    with pytest.raises(SectorBriefAIError, match="upstream 500"):
        await narrate_sector_brief(_repo(tmp_path), kind="concept", top_n=5)

    # 降级: GET 仍然返回数据派生文案, 且不写坏缓存
    fallback = build_sector_brief(_repo(tmp_path), kind="concept", top_n=5)
    assert fallback["bullish"][0]["logic_stats"]
    assert not (tmp_path / "user_data" / "sector_brief_ai.json").exists()


async def test_narrate_raises_on_unparsable_ai_reply(tmp_path, monkeypatch):
    async def garbage(messages, **kwargs):
        return "抱歉，我无法完成这个请求。"

    monkeypatch.setattr(ai_provider, "ai_configured", lambda *a, **k: True)
    monkeypatch.setattr(ai_provider, "generate_ai_text", garbage)

    with pytest.raises(SectorBriefAIError, match="无法解析"):
        await narrate_sector_brief(_repo(tmp_path), kind="concept", top_n=5)


_POOL = [
    {
        "id": "x1",
        "time": "2026-09-20 09:35:00",
        "title": "甲一公告拿到大额订单，产能排至明年",
        "content": "公司披露新增订单情况。",
        "source": "同花顺",
        "url": "https://example.com/1",
    },
    {
        "id": "x2",
        "time": "2026-09-20 10:35:00",
        "title": "省级产业基金加码，甲二所在产业链获专项资金支持",
        "content": "政策面增量资金落地。",
        "source": "财联社",
        "url": "https://example.com/2",
    },
]


class _FakeNewsService:
    """只提供快讯池的 NewsService 替身(不触网)。"""

    def __init__(self, pool: list[dict] | None = None):
        self._pool = pool if pool is not None else list(_POOL)
        self.calls = 0

    def fetch_news_pool(self, limit: int = 120, within_hours: int = 48) -> list[dict]:
        self.calls += 1
        return list(self._pool)[:limit]


def test_cards_carry_data_driven_drivers_without_news_service(tmp_path):
    brief = build_sector_brief(_repo(tmp_path), kind="concept", top_n=5)
    card = brief["bullish"][0]

    # 没有快讯源/外围数据时至少要有盘面维度, 且权重必须是完整的一份(100)
    assert [d["key"] for d in card["drivers"]] == ["market"]
    assert card["drivers"][0]["weight"] == 100
    assert card["drivers"][0]["label"] == "盘面题材"
    assert card["headline"] and "强势概念" in card["headline"]
    assert card["window_pct"] is not None
    assert card["flash"] == []


def test_cards_match_related_flash_from_news_pool(tmp_path):
    brief = build_sector_brief(
        _repo(tmp_path), kind="concept", top_n=5, news_service=_FakeNewsService()
    )
    card = brief["bullish"][0]

    assert [d["key"] for d in card["drivers"]] == ["news", "policy", "market"]
    assert sum(d["weight"] for d in card["drivers"]) == 100
    by_key = {d["key"]: d for d in card["drivers"]}
    # 公司订单归到消息面, 产业基金归到政策产业 —— 两类不得混在一个维度里
    assert "甲一" in by_key["news"]["text"]
    assert "甲二" in by_key["policy"]["text"]
    # 关联快讯带真实时间/来源/链接, 前端直接渲染
    assert {item["id"] for item in card["flash"]} == {"x1", "x2"}
    assert {item["time"] for item in card["flash"]} == {"2026-09-20 09:35:00", "2026-09-20 10:35:00"}
    assert {item["url"] for item in card["flash"]} == {"https://example.com/1", "https://example.com/2"}


async def test_ai_drivers_and_flash_ids_override_data_path(tmp_path, monkeypatch):
    seen: dict[int, str] = {}

    async def reply(messages, **kwargs):
        content = messages[1]["content"]
        assert "快讯清单" in content
        # 清单编号就是 flash_ids 的引用口径: 记录下模型看到的每条编号对应哪条新闻
        for line in content.splitlines():
            match = re.match(r"\[(\d+)\] .+?\| (.+?) \|", line)
            if match:
                seen[int(match.group(1))] = match.group(2)
        assert len(seen) == 2
        return json.dumps(
            [{
                "name": "强势概念",
                "headline": "订单与政策共振",
                "logic": "排名升至首位。",
                "drivers": [
                    {"key": "news", "weight": 70, "text": "甲一拿到大额订单"},
                    {"key": "market", "weight": 30, "text": "排名升至首位"},
                ],
                "flash_ids": [1, 99, "x"],
            }],
            ensure_ascii=False,
        )

    monkeypatch.setattr(ai_provider, "ai_configured", lambda *a, **k: True)
    monkeypatch.setattr(ai_provider, "generate_ai_text", reply)

    brief = await narrate_sector_brief(
        _repo(tmp_path), kind="concept", top_n=5, news_service=_FakeNewsService()
    )
    card = brief["bullish"][0]

    assert card["headline"] == "订单与政策共振"
    assert [(d["key"], d["weight"]) for d in card["drivers"]] == [("news", 70), ("market", 30)]
    # 越界编号(99)与非整数("x")必须被丢弃, 只保留真实存在的第 2 条
    assert [item["title"] for item in card["flash"]] == [seen[1]]

    # 未被 AI 覆盖的板块继续用数据派生归因, 不能因 AI 只回了一半就变空
    assert brief["bearish"][0]["ai_logic"] is None
    # 快讯池里没有「弱势概念」的成分股名 → 该卡只有盘面维度, 也不编消息面
    assert [d["key"] for d in brief["bearish"][0]["drivers"]] == ["market"]


async def test_narrate_skips_ai_without_any_sector_data(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_provider, "ai_configured", lambda *a, **k: True)
    monkeypatch.setattr(ai_provider, "generate_ai_text", pytest.fail)

    brief = await narrate_sector_brief(_repo(tmp_path, with_latest=False), kind="concept", top_n=5)
    assert brief["ai_status"] == "unavailable"
    assert brief["bullish"] == []


def test_jsonable_strips_non_finite_and_foreign_scalars():
    """出口收尾: 非有限数→None、numpy 标量→原生值、日期→字符串。

    这些值混进结果就会被 60s 缓存固定住, 接口持续 500 直到进程重启。"""
    np = pytest.importorskip("numpy")

    out = sector_brief._jsonable(
        {
            "nan": float("nan"),
            "inf": float("inf"),
            "npy": np.float64(1.25),
            "npi": np.int64(7),
            "when": date(2026, 9, 19),
            "nested": [{"v": np.float32(2.5)}],
            "ok": "文本",
        }
    )

    assert out["nan"] is None and out["inf"] is None
    assert out["npy"] == 1.25 and type(out["npy"]) is float
    assert out["npi"] == 7 and type(out["npi"]) is int
    assert out["when"] == "2026-09-19"
    assert out["nested"][0]["v"] == 2.5
    # 不抛 = 出口对 starlette 的 allow_nan=False 是安全的
    json.dumps(out, allow_nan=False, ensure_ascii=False)


def test_build_sector_brief_survives_strict_json(tmp_path):
    """板块简报结果必须能被 strict JSON 序列化 —— 否则整条接口 500。"""
    brief = build_sector_brief(_repo(tmp_path), kind="concept", top_n=5)

    json.dumps(brief, allow_nan=False, ensure_ascii=False)
