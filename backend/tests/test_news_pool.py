# -*- coding: utf-8 -*-
"""多源快讯池测试 —— 时间解析、标题归一化、跨源去重、时间窗过滤与缓存。

不触网: 各源的读取方法用 monkeypatch 替换成夹具。
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest

from app.services.news_service import (
    NewsService,
    _coerce_dt,
    _news_id,
    _news_title,
    _same_story,
    _title_key,
)


@pytest.fixture(autouse=True)
def _clear_pool_cache():
    """池子是进程级缓存, 用例之间必须隔离。"""
    NewsService._pool_cache = []
    NewsService._pool_cache_ts = 0.0
    yield
    NewsService._pool_cache = []
    NewsService._pool_cache_ts = 0.0


def _item(minutes_ago: int, title: str, source: str, content: str = "") -> dict:
    moment = datetime.now() - timedelta(minutes=minutes_ago)
    return {
        "id": _news_id(source, title),
        "time": moment.strftime("%Y-%m-%d %H:%M:%S"),
        "title": title,
        "content": content,
        "source": source,
        "url": "",
    }


def test_coerce_dt_handles_every_source_shape():
    assert _coerce_dt("2026-09-20 23:01:24") == datetime(2026, 9, 20, 23, 1, 24)
    assert _coerce_dt("2026-09-20 23:01") == datetime(2026, 9, 20, 23, 1)
    assert _coerce_dt("2026-09-20") == datetime(2026, 9, 20)
    # 财联社: 发布日期与发布时间分两列
    assert _coerce_dt(date(2026, 9, 20), time(23, 1, 24)) == datetime(2026, 9, 20, 23, 1, 24)
    # 新浪: 时间列是字符串, 但也可能是 time/datetime
    assert _coerce_dt(time(9, 30), date(2026, 9, 20)) == datetime(2026, 9, 20, 9, 30)
    assert _coerce_dt(datetime(2026, 9, 20, 8, 0)) == datetime(2026, 9, 20, 8, 0)
    assert _coerce_dt("") is None
    assert _coerce_dt("昨天下午") is None
    # 财联社给 time 但没给日期时退回今天, 不因缺日期丢掉整条
    assert _coerce_dt(time(9, 30)).date() == date.today()


def test_news_title_falls_back_to_bracket_or_body():
    assert _news_title("长鑫科技量产", "正文") == "长鑫科技量产"
    assert _news_title("", "【央行开展逆回购】详情……") == "央行开展逆回购"
    # 既无标题也无【】时取正文首句, 不能因为没标题就把条目丢掉
    fallback = _news_title(None, "没有方括号的正文内容" * 10)
    assert fallback.startswith("没有方括号的正文内容") and len(fallback) == 48


def test_title_key_strips_source_prefixes_and_punctuation():
    assert _title_key("财联社9月20日电，央行开展逆回购") == _title_key("【央行开展逆回购】")
    assert _title_key("花旗：AI 瓶颈转向能源") == _title_key("花旗:AI瓶颈转向能源")


def test_same_story_collapses_same_event_from_two_sources():
    keys = [_title_key("花旗集团CEO弗雷泽表示 人工智能的瓶颈已从芯片转向能源")]

    assert _same_story(_title_key("财联社9月20日电，花旗集团CEO弗雷泽表示人工智能的瓶颈已从芯片转向能源"), keys)
    # 短标题只做完全相等判定, 避免把不同的短消息合并
    assert not _same_story(_title_key("央行开展逆回购"), [_title_key("央行逆回购")])


def test_fetch_news_pool_dedupes_filters_window_and_caches(tmp_path, monkeypatch):
    calls: list[str] = []
    old = _item(60 * 72, "三天前的旧闻", "东方财富")  # 超出 48h 窗口
    same_event_a = _item(30, "花旗集团CEO弗雷泽表示 人工智能的瓶颈已从芯片转向能源", "富途")
    same_event_b = _item(40, "财联社9月20日电，花旗集团CEO弗雷泽表示人工智能的瓶颈已从芯片转向能源", "财联社")
    newest = _item(5, "新鲜消息", "同花顺")

    def fake_rows(ak, func_name, source, body_col):
        calls.append(func_name)
        if func_name == "stock_info_global_em":
            return [old, same_event_a, same_event_b, newest]
        return []

    monkeypatch.setattr(NewsService, "_akshare_news_rows", lambda self, ak, fn, src, col: fake_rows(ak, fn, src, col))
    monkeypatch.setattr(NewsService, "fetch_live_flash", lambda self, limit=30: [{"is_fallback": True}])

    svc = NewsService(data_dir=tmp_path)
    pool = svc.fetch_news_pool(within_hours=48)

    titles = [item["title"] for item in pool]
    assert titles[0] == "新鲜消息"  # 时间倒序
    assert "三天前的旧闻" not in titles
    # 同一事件的两个源版本只留最新那条
    assert len([t for t in titles if "花旗集团" in t]) == 1
    assert len(pool) == 2

    # 第二次调用命中进程缓存, 不再打上游
    svc.fetch_news_pool(within_hours=48)
    assert len(calls) == 5  # 首轮 5 个源各调一次


def test_fetch_news_pool_limit_caps_and_skips_fallback_items(tmp_path, monkeypatch):
    items = [_item(index, f"消息 {index}", "东方财富") for index in range(10)]
    fallback = {
        "id": "f_1",
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tag": "半导体",
        "title": "兜底示例：晶圆代工产能紧张",
        "content": "示例文案",
        "is_fallback": True,
    }

    monkeypatch.setattr(
        NewsService, "_akshare_news_rows", lambda self, ak, fn, src, col: list(items) if fn == "stock_info_global_em" else []
    )
    monkeypatch.setattr(NewsService, "fetch_live_flash", lambda self, limit=30: [fallback])

    pool = NewsService(data_dir=tmp_path).fetch_news_pool(limit=3, within_hours=48)

    assert len(pool) == 3
    # 上游不可用时的写死示例文案不能混进快讯池当证据
    assert all("兜底示例" not in item["title"] for item in pool)


def test_news_id_is_stable_and_source_scoped():
    assert _news_id("同花顺", "某条新闻") == _news_id("同花顺", "某条新闻")
    assert _news_id("同花顺", "某条新闻") != _news_id("财联社", "某条新闻")


def test_pool_cache_is_isolated_from_other_news_caches(tmp_path, monkeypatch):
    """快讯池缓存与 7x24 滚动池各管各的, 互不覆盖(两者 TTL 与用途不同)。"""
    from app.services.news_service import flash_feed

    monkeypatch.setattr(NewsService, "_akshare_news_rows", lambda self, ak, fn, src, col: [])
    monkeypatch.setattr(NewsService, "fetch_live_flash", lambda self, limit=30: [])
    flash_feed.clear()

    svc = NewsService(data_dir=tmp_path)
    svc.fetch_news_pool()

    assert NewsService._pool_cache == []
    # 合并池是进程级缓存, 滚动池是持续抓取的时间线 —— 后者不该被前者写入
    assert flash_feed.items() == []
    flash_feed.clear()
