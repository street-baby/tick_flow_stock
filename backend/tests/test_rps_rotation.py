# -*- coding: utf-8 -*-
"""rps_rotation 维度映射缓存的形状契约测试。

为什么需要它:
  维度映射缓存(600s)比结果缓存(120s)活得久。命中映射缓存时返回的形状一旦和未命中
  不一致, 调用方按 (map_df, member_count) 解包 DataFrame 就会拿到两个 Series,
  紧接着 df.join(map_df, ...) 抛
  "TypeError: expected `other` to be a 'DataFrame', not 'Series'" —— 于是
  /api/rps/rotation 与 /api/news/sector-brief 会在「结果缓存已过期、映射缓存还在」
  的那段时间里整段 500, 等映射缓存过期又自己恢复。

  这里不靠等待 TTL: 直接对命中/未命中两条路径的返回形状与缓存内容下断言。
"""
from __future__ import annotations

from types import SimpleNamespace

import polars as pl
import pytest

from app.services import rps_rotation


class _FakeConfigStore:
    """替掉 ExtConfigStore: 只提供一份带概念字段的扩展配置。"""

    def __init__(self, data_dir) -> None:
        self._config = SimpleNamespace(
            id="ext_test",
            label="概念",
            mode="snapshot",
            fields=[SimpleNamespace(name="所属概念", dtype="string", label="所属概念")],
            symbol_map={"type": "mapped", "col": "symbol"},
            code_map=None,
        )

    def load_all(self):
        return [self._config]


@pytest.fixture(autouse=True)
def _clear_map_cache():
    """映射缓存是进程级字典 —— 用例之间必须隔离。"""
    rps_rotation._map_cache.clear()
    rps_rotation._map_ts.clear()
    yield
    rps_rotation._map_cache.clear()
    rps_rotation._map_ts.clear()


def _fake_repo() -> SimpleNamespace:
    return SimpleNamespace(store=SimpleNamespace(data_dir=None))


def test_concept_map_cache_hit_returns_tuple_like_miss(monkeypatch):
    monkeypatch.setattr(rps_rotation, "ExtConfigStore", _FakeConfigStore)
    monkeypatch.setattr(
        rps_rotation,
        "_read_ext_rows",
        lambda data_dir, config, field: [
            {"symbol": "000001.SZ", "所属概念": "银行"},
            {"symbol": "000002.SZ", "所属概念": "房地产"},
        ],
    )
    repo = _fake_repo()

    miss = rps_rotation._load_concept_map_df(repo, "concept")  # 未命中: 构建并写入缓存
    hit = rps_rotation._load_concept_map_df(repo, "concept")   # 命中: 必须同形状

    assert isinstance(miss, tuple)
    assert isinstance(hit, tuple), "命中路径返回了 DataFrame: 调用方会解包成两个 Series"

    map_df, member_count = hit
    assert isinstance(map_df, pl.DataFrame)
    assert map_df.columns == ["_sym_up", "concept"]
    assert member_count == 2

    # 缓存里存的也必须是同一形状, 否则下一次命中又会退回 DataFrame
    cached = rps_rotation._map_cache["concept"]
    assert isinstance(cached, tuple)
    assert isinstance(cached[0], pl.DataFrame)


def test_concept_map_cache_is_reused_within_ttl(monkeypatch):
    """命中必须复用缓存(不再重复扫扩展表), 否则这个缓存就没意义了。"""
    monkeypatch.setattr(rps_rotation, "ExtConfigStore", _FakeConfigStore)
    calls: list[int] = []

    def _read(data_dir, config, field):
        calls.append(1)
        return [{"symbol": "000001.SZ", "所属概念": "银行"}]

    monkeypatch.setattr(rps_rotation, "_read_ext_rows", _read)
    repo = _fake_repo()

    first_df, first_count = rps_rotation._load_concept_map_df(repo, "concept")
    second_df, second_count = rps_rotation._load_concept_map_df(repo, "concept")

    assert len(calls) == 1
    assert (first_count, second_count) == (1, 1)
    assert first_df.equals(second_df)


def test_concept_map_cache_does_not_leak_between_kinds(monkeypatch):
    """概念与行业分开缓存: 行业命中不能拿到概念成分股。"""
    monkeypatch.setattr(rps_rotation, "ExtConfigStore", _FakeConfigStore)
    monkeypatch.setattr(
        rps_rotation,
        "_read_ext_rows",
        lambda data_dir, config, field: [{"symbol": "000001.SZ", field: "银行-股份制银行"}],
    )
    repo = _fake_repo()

    concept_df, _ = rps_rotation._load_concept_map_df(repo, "concept")
    industry_df, _ = rps_rotation._load_concept_map_df(repo, "industry")

    # 夹具配置只有概念字段: 概念侧拿到成分股(symbol 与去后缀 code 两个键),
    # 行业侧没有可用维度 → 空表, 而不是复用概念的成分股
    assert set(concept_df.columns) == {"_sym_up", "concept"}
    assert set(concept_df["concept"]) == {"银行-股份制银行"}
    assert industry_df.is_empty()
