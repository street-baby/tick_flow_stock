# -*- coding: utf-8 -*-
"""7x24 快讯滚动池与实时抓取线程测试。

覆盖:
1. FlashFeed 合并: 去重(含缺 id 时按标题派生)、时间倒序、只返回新增条目
2. 保留窗/条数上限截断
3. 落盘与恢复: 往返一致 + 写盘节流
4. NewsService: 池子优先、TTL 内不再打上游、上游挂了退化为兜底示例且不留池子
5. NewsPoller: 只有真出现新条目才推 SSE、连续失败进状态
6. NewsPoller 全天候: 无交易时段闸门、上游一直失败也不停、主源故障切多源降级、
   线程意外退出由守护拉起、长时间没成功抓取如实标停滞
7. 降级抓取: 多源合并池的 source 进池子当 tag 并去重
8. SSE 通道: 每个订阅者都收到 news_updated(不是被先醒的连接取走)

不触网: 上游抓取方法一律用 monkeypatch 换成夹具。
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.api.news import _flash_live_meta
from app.services import news_poller as poller_mod
from app.services import news_service as news_mod
from app.services.news_poller import NewsPoller
from app.services.news_service import FlashFeed, NewsService, _coerce_dt, flash_feed


@pytest.fixture(autouse=True)
def _isolate_flash_state(monkeypatch):
    """池子是进程级单例 —— 用例之间必须隔离(含「已从磁盘加载」的路径标记)。"""
    monkeypatch.setattr(news_mod, "_flash_loaded_path", None)
    flash_feed.clear()
    yield
    flash_feed.clear()


def _row(ident: str, minutes_ago: int, title: str = "") -> dict:
    moment = datetime.now() - timedelta(minutes=minutes_ago)
    return {
        "id": ident,
        "time": moment.strftime("%Y-%m-%d %H:%M:%S"),
        "tag": "市场",
        "title": title or f"快讯 {ident}",
        "content": "正文",
        "url": "",
    }


def _pool_row(ident: str, minutes_ago: int, source: str, title: str) -> dict:
    """多源合并池的行结构(来源字段叫 source, 与快讯池的 tag 不是同一列名)。"""
    moment = datetime.now() - timedelta(minutes=minutes_ago)
    return {
        "id": ident,
        "time": moment.strftime("%Y-%m-%d %H:%M:%S"),
        "title": title,
        "content": "正文",
        "source": source,
        "url": "",
    }


# ── FlashFeed ────────────────────────────────────────────────────────


def test_merge_dedupes_and_returns_only_new_items():
    feed = FlashFeed()

    assert [it["id"] for it in feed.merge([_row("a", 3), _row("b", 1)])] == ["b", "a"]
    # 同一批再抓一次: 不重复入库, 也没有「新增」
    assert feed.merge([_row("a", 3), _row("b", 1)]) == []
    assert [it["id"] for it in feed.items()] == ["b", "a"]
    # 新事件排到最前
    assert [it["id"] for it in feed.merge([_row("c", 0)])] == ["c"]
    assert [it["id"] for it in feed.items(2)] == ["c", "b"]


def test_merge_derives_id_without_upstream_id_and_skips_empty_rows():
    feed = FlashFeed()

    now = datetime.now()
    t1 = (now - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    t2 = (now - timedelta(minutes=9)).strftime("%Y-%m-%d %H:%M:%S")
    t3 = (now - timedelta(minutes=8)).strftime("%Y-%m-%d %H:%M:%S")
    added = feed.merge(
        [
            {"time": t1, "title": "没有 id 的快讯", "content": "正文"},
            {"time": t2, "title": "没有 id 的快讯", "content": "正文"},
            {"time": t3, "title": "", "content": ""},
        ]
    )

    assert len(added) == 1
    assert added[0]["id"]
    assert len(feed) == 1


def test_merge_drops_items_outside_retention_window():
    feed = FlashFeed(retention_hours=1)

    feed.merge([_row("old", 180), _row("fresh", 5)])

    assert [it["id"] for it in feed.items()] == ["fresh"]


def test_cap_keeps_newest_items():
    feed = FlashFeed(cap=3)

    feed.merge([_row(f"r{i}", i) for i in range(6)])

    assert [it["id"] for it in feed.items()] == ["r0", "r1", "r2"]


def test_save_and_load_round_trip_and_save_is_throttled(tmp_path):
    path = tmp_path / "user_data" / "flash_feed.json"
    feed = FlashFeed()
    feed.merge([_row("a", 1)])

    assert feed.save(path, force=True) is True
    # 节流: 非强制时短时间内不重复写盘
    assert feed.save(path) is False

    restored = FlashFeed()
    assert restored.load(path) == 1
    assert [it["id"] for it in restored.items()] == ["a"]


# ── NewsService 读取路径 ─────────────────────────────────────────────


def test_fetch_live_flash_reads_pool_without_hitting_upstream_inside_ttl(tmp_path, monkeypatch):
    calls: list[str] = []

    def _fetch(self):
        calls.append("call")
        return [_row("a", 1)]

    monkeypatch.setattr(NewsService, "_fetch_upstream_flash", _fetch)
    svc = NewsService(data_dir=tmp_path)

    first = svc.fetch_live_flash(limit=10)
    assert [it["id"] for it in first] == ["a"]
    assert len(calls) == 1
    # TTL 内再读: 只读池子 —— 页面轮询/多标签页不会放大成上游请求
    assert svc.fetch_live_flash(limit=10) == first
    assert len(calls) == 1


def test_fetch_live_flash_falls_back_to_demo_when_upstream_down(tmp_path, monkeypatch):
    def _boom(self):
        raise RuntimeError("上游 502")

    monkeypatch.setattr(NewsService, "_fetch_upstream_flash", _boom)

    items = NewsService(data_dir=tmp_path).fetch_live_flash(limit=5)

    assert items and all(it["is_fallback"] for it in items)
    # 失败不推进 updated_at(前端据此知道数据没在刷新), 但要留下时间与原因
    assert flash_feed.updated_at == 0.0
    assert flash_feed.attempt_at > 0
    assert flash_feed.last_error == "上游 502"
    # 兜底示例文案不能被留在池子里当资讯
    assert len(flash_feed) == 0


def test_refresh_flash_store_survives_process_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(NewsService, "_fetch_upstream_flash", lambda self: [_row("a", 1)])
    svc = NewsService(data_dir=tmp_path)
    svc.refresh_flash_store()
    svc.save_flash_store(force=True)

    # 模拟进程重启: 清掉内存池, 但磁盘上有上一轮抓到的条目
    flash_feed.clear()
    monkeypatch.setattr(news_mod, "_flash_loaded_path", None)
    monkeypatch.setattr(NewsService, "_fetch_upstream_flash", lambda self: [])

    assert [it["id"] for it in NewsService(data_dir=tmp_path).fetch_live_flash(limit=10)] == ["a"]


def test_refresh_flash_from_pool_merges_rows_dedupes_and_keeps_source_as_tag(tmp_path, monkeypatch):
    pool_rows = [
        _pool_row("em_1", 30, "东方财富", "东财快讯"),
        _pool_row("cls_1", 10, "财联社", "财联社快讯"),
    ]
    monkeypatch.setattr(NewsService, "fetch_news_pool", lambda self, limit=300, within_hours=48: list(pool_rows))
    svc = NewsService(data_dir=tmp_path)

    added = svc.refresh_flash_from_pool()

    # 降级条目也要能看出出处: 合并池的 source 落到池子的 tag 上
    assert [it["tag"] for it in added] == ["财联社", "东方财富"]
    assert [it["id"] for it in flash_feed.items()] == ["cls_1", "em_1"]
    # 再抓一次: 池里已经有这两条, 没有新增(不会把同一事件反复塞进时间线)
    assert svc.refresh_flash_from_pool() == []


def test_refresh_flash_from_pool_clamps_source_timestamps_from_the_future(tmp_path, monkeypatch):
    """源时间跟服务器时区跑时会偏到未来(富途): 按「刚刚」入池, 不能污染时间线。"""
    pool_rows = [
        _pool_row("futu_1", -60, "富途", "偏到未来一小时的快讯"),
        _pool_row("em_1", 5, "东方财富", "正常快讯"),
    ]
    monkeypatch.setattr(NewsService, "fetch_news_pool", lambda self, limit=300, within_hours=48: list(pool_rows))
    svc = NewsService(data_dir=tmp_path)

    added = svc.refresh_flash_from_pool()
    by_id = {it["id"]: it for it in added}
    clamped = _coerce_dt(by_id["futu_1"]["time"])

    # 未来的那条被按「刚刚」收下: 既不丢内容, 也不会被排到时间线最前面之外
    assert clamped <= datetime.now()
    assert (datetime.now() - clamped).total_seconds() < 5
    assert clamped > _coerce_dt(by_id["em_1"]["time"])


# ── NewsPoller ───────────────────────────────────────────────────────


class _FakeQuoteService:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def notify_news_updated(self, payload: dict) -> None:
        self.payloads.append(dict(payload))


def test_poller_pushes_only_when_new_items_arrive(tmp_path, monkeypatch):
    batch = [_row("a", 1)]
    monkeypatch.setattr(NewsService, "_fetch_upstream_flash", lambda self: list(batch))
    qs = _FakeQuoteService()
    poller = NewsPoller(data_dir=tmp_path, quote_service=qs, interval=15.0)

    first = poller.poll_once()
    assert first["ok"] is True and first["new"] == 1 and first["stored"] == 1
    assert qs.payloads == [{"new": 1, "stored": 1, "latest": batch[0]["time"]}]

    # 上游没新内容: 不推 —— 推了只是让前端白重取一次
    second = poller.poll_once()
    assert second["ok"] is True and second["new"] == 0 and second["stored"] == 1
    assert len(qs.payloads) == 1

    batch.insert(0, _row("b", 0))
    third = poller.poll_once()
    assert third["new"] == 1 and third["stored"] == 2
    assert qs.payloads[-1]["new"] == 1 and qs.payloads[-1]["stored"] == 2


def test_poller_status_reports_consecutive_failures(tmp_path, monkeypatch):
    def _boom(self):
        raise RuntimeError("上游不可达")

    monkeypatch.setattr(NewsService, "_fetch_upstream_flash", _boom)
    # 连续失败会触发多源降级 —— 本用例只看主源失败计数, 降级源固定空(且不触网)
    monkeypatch.setattr(NewsService, "refresh_flash_from_pool", lambda self, limit=120, within_hours=12: [])
    poller = NewsPoller(data_dir=tmp_path, interval=15.0)

    assert poller.poll_once()["ok"] is False
    assert poller.poll_once()["ok"] is False

    status = poller.get_status()
    assert status["running"] is False
    assert status["enabled"] is True
    assert status["interval_seconds"] == 15.0
    assert status["cycles"] == 2
    assert status["consecutive_errors"] == 2
    assert status["last_error"] == "上游不可达"
    assert status["stored"] == 0


def test_poller_start_is_disabled_when_interval_zero(tmp_path):
    poller = NewsPoller(data_dir=tmp_path, interval=0)

    assert poller.start() is False
    assert poller.running is False
    assert poller.get_status()["enabled"] is False


# ── NewsPoller 全天候 ────────────────────────────────────────────────


def test_poller_polls_around_the_clock_without_trading_session_gate(tmp_path, monkeypatch):
    """凌晨 02:30(非交易时段)照抓 —— 「全天候」的前提就是没有交易时段闸门。"""
    nothing = [_row("night", 1)]
    monkeypatch.setattr(NewsService, "_fetch_upstream_flash", lambda self: list(nothing))
    night = datetime(2026, 9, 23, 2, 30, 0)

    class _NightDateTime(datetime):
        @classmethod
        def now(cls, tz=None):  # 只替换「现在」的取值, 其余行为与 datetime 一致
            return night

    monkeypatch.setattr(poller_mod, "datetime", _NightDateTime)
    poller = NewsPoller(data_dir=tmp_path, interval=15.0)

    assert poller.poll_once()["ok"] is True
    assert poller.get_status()["last_poll_at"] == "2026-09-23 02:30:00"
    assert [it["id"] for it in flash_feed.items()] == ["night"]


def test_poller_loop_keeps_polling_when_upstream_always_fails(tmp_path, monkeypatch):
    """上游一直失败也保持节奏继续抓: 不退出、不自停, 失败数如实累计。"""
    def _boom(self):
        raise RuntimeError("上游不可达")

    monkeypatch.setattr(NewsService, "_fetch_upstream_flash", _boom)
    # 降级源在这里单独测, 本用例只关心「抓取节奏不断」
    monkeypatch.setattr(NewsService, "refresh_flash_from_pool", lambda self, limit=120, within_hours=12: [])
    monkeypatch.setattr(poller_mod, "BOOT_DELAY_SECONDS", 0.0)
    monkeypatch.setattr(poller_mod.random, "uniform", lambda low, high: 0.0)
    poller = NewsPoller(data_dir=tmp_path, interval=15.0)
    poller.interval = 1.0  # 循环下限是 1s, 用例不必等 15s

    assert poller.start() is True
    try:
        deadline = time.monotonic() + 15.0
        while poller.get_status()["cycles"] < 3 and time.monotonic() < deadline:
            time.sleep(0.05)
        status = poller.get_status()

        assert status["cycles"] >= 3          # 连续失败仍按节奏抓下去
        assert status["running"] is True
        assert status["enabled"] is True
        assert status["consecutive_errors"] >= 3
        assert status["last_error"] == "上游不可达"
    finally:
        poller.stop()

    assert poller.running is False


def test_poller_falls_back_to_multi_source_when_primary_keeps_failing(tmp_path, monkeypatch):
    """主源挂掉时用多源合并池续上时间线, 且降级本身受最短间隔约束。"""
    def _boom(self):
        raise RuntimeError("上游 502")

    fallback_calls: list[int] = []

    def _fake_pool(self, limit=120, within_hours=12):
        fallback_calls.append(limit)
        return flash_feed.merge([_row(f"pool{len(fallback_calls)}", 1, "降级源补入")])

    monkeypatch.setattr(NewsService, "_fetch_upstream_flash", _boom)
    monkeypatch.setattr(NewsService, "refresh_flash_from_pool", _fake_pool)
    qs = _FakeQuoteService()
    poller = NewsPoller(data_dir=tmp_path, quote_service=qs, interval=15.0)

    first = poller.poll_once()   # 第 1 次失败: 还不动降级源
    assert first["ok"] is False and first["fallback_new"] == 0
    assert fallback_calls == []

    second = poller.poll_once()  # 连续第 2 次失败: 降级兜底
    assert second["fallback_new"] == 1
    assert [it["id"] for it in flash_feed.items()] == ["pool1"]
    assert qs.payloads[-1]["new"] == 1   # 降级条目照样推 SSE

    third = poller.poll_once()   # 最短间隔内: 不再去打多个上游
    assert third["fallback_new"] == 0
    assert len(fallback_calls) == 1

    status = poller.get_status()
    assert status["fallback_new"] == 1
    assert status["last_fallback_at"]


def test_poller_self_heals_when_worker_thread_dies(tmp_path, monkeypatch):
    """抓取线程意外退出由守护拉起 —— 否则「全天候」会在一次崩溃后静默停掉。"""
    monkeypatch.setattr(NewsService, "_fetch_upstream_flash", lambda self: [])
    poller = NewsPoller(data_dir=tmp_path, interval=15.0)

    # 线程还没起(守护路径也要能拉起), 幂等: 活着就不重复起
    assert poller.ensure_running() is True
    assert poller.running is True
    assert poller.ensure_running() is False
    assert poller.get_status()["restarts"] == 1

    # 线程死掉后: 状态如实报 False, 下一次守护检查拉起来
    poller._thread = None
    assert poller.get_status()["running"] is False
    assert poller.ensure_running() is True
    assert poller.get_status()["restarts"] == 2
    assert poller.running is True

    poller.stop()
    assert poller.running is False


def test_poller_status_reports_stall_when_no_successful_fetch(tmp_path, monkeypatch):
    """长时间没有一次成功抓取要如实标停滞 —— 「在不断获取」得可验证, 不能靠感觉。"""
    monkeypatch.setattr(NewsService, "_fetch_upstream_flash", lambda self: [_row("a", 1)])
    poller = NewsPoller(data_dir=tmp_path, interval=15.0)
    assert poller.poll_once()["ok"] is True

    fresh = poller.get_status()
    assert fresh["stalled"] is False
    assert fresh["last_success_at"] == fresh["source_updated_at"]
    assert fresh["stalled_seconds"] < poller.stall_threshold

    # 8 个周期(120s)是下限: 15s 节奏下不会因为「深夜快讯稀疏」被误判成停滞
    assert poller.stall_threshold == 120.0

    # 模拟十分钟没有一次成功抓取(上游挂了 / 抓取线程卡死)
    flash_feed._updated_at -= 600
    stalled = poller.get_status()
    assert stalled["stalled"] is True
    assert stalled["stalled_seconds"] >= 600


# ── SSE 通道 ─────────────────────────────────────────────────────────


def test_quote_subscriber_delivers_news_payload_and_clears_it():
    from app.services.quote_service import QuoteSubscriber

    sub = QuoteSubscriber()
    sub.push_news({"new": 2, "stored": 7})

    assert sub.pop()["news"] == {"new": 2, "stored": 7}
    # 取走即复位: 同一批快讯不会被重复推送
    assert sub.pop()["news"] is None


def test_quote_service_broadcasts_news_to_every_subscriber():
    from app.services.quote_service import QuoteService

    qs = QuoteService()
    first, second = qs.subscribe(), qs.subscribe()
    try:
        qs.notify_news_updated({"new": 3})
        assert first.pop()["news"] == {"new": 3}
        assert second.pop()["news"] == {"new": 3}
    finally:
        qs.unsubscribe(first)
        qs.unsubscribe(second)


# ── API 元信息 ───────────────────────────────────────────────────────


def test_flash_live_meta_reports_poller_interval():
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    meta = _flash_live_meta(request)
    assert set(meta) == {"updated_at", "server_time", "poll_interval_seconds"}
    # 没有 poller 时退化为 0: 前端据此显示「按需抓取」而不是假装实时
    assert meta["poll_interval_seconds"] == 0.0

    request.app.state.news_poller = SimpleNamespace(interval=15.0)
    assert _flash_live_meta(request)["poll_interval_seconds"] == 15.0
