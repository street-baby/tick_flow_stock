# -*- coding: utf-8 -*-
"""7x24 财经快讯实时滚动抓取器。

为什么需要它:
  - 快讯的上游每次只回最近 50 条。前端自己定时拉, 拿到的永远是同一个 50 条
    窗口 —— 用户看到的就是「半天不动」, 而且每个标签页都在打上游;
  - 已有的 catalyst 调度是 5 分钟一次, 对「明天炒什么」够用, 但对资讯页太慢。

所以由服务端保持一个固定节奏的抓取线程: 抓到的条目并入 FlashFeed 滚动池
(时间线连续累积), 有新条目就通过行情 SSE 推一条 news_updated, 前端只重取
一次快讯查询 —— 页面是「实时不断在长出新的」, 而不是靠用户手动刷新。

「全天候」还有两个前提, 都由这里兜住:
  - 时段无关: 半夜、收盘、周末照抓(没有交易时段闸门), 循环按固定节奏跑;
  - 故障不停: 抓取线程意外退出由守护线程拉起, 主源连续失败切多源合并池,
    所以单源被限流/改版不会让时间线整段停住。

抓取成败都写进 get_status(), 供 /api/news/live-status 展示与排障。
"""
from __future__ import annotations

import logging
import random
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config import settings
from app.services.news_service import NewsService, _iso, flash_feed

logger = logging.getLogger(__name__)

# 抓取节奏下限: 上游本身约 15 秒才有一条新快讯, 再密只是白发请求
MIN_INTERVAL_SECONDS = 5.0
# 首轮延迟: 启动时数据预热/调度器初始化先跑, 不跟它们抢 IO
BOOT_DELAY_SECONDS = 2.0
# 守护检查间隔: 只看抓取线程还活着吗, 不必跟着抓取节奏走
SUPERVISOR_INTERVAL_SECONDS = 30.0
# 主源连续失败到这次数就启用降级源
FALLBACK_AFTER_FAILURES = 2
# 降级源(东财/富途/同花顺/财联社/新浪合并池)一次要打多个上游, 设最短间隔,
# 避免「降级」本身变成以抓取节奏反复打上游
FALLBACK_MIN_INTERVAL_SECONDS = 120.0


def _clamp_interval(value: Any) -> float:
    try:
        interval = float(value)
    except (TypeError, ValueError):
        interval = 0.0
    if interval <= 0:
        return 0.0
    return max(MIN_INTERVAL_SECONDS, interval)


class NewsPoller:
    """7x24 快讯滚动抓取器(进程内单例, daemon 线程 + 守护线程)。"""

    def __init__(
        self,
        data_dir: Path,
        quote_service: Any = None,
        interval: float | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.news_service = NewsService(data_dir=self.data_dir)
        self.quote_service = quote_service
        # interval<=0 表示关闭自动抓取(只剩读取路径的兜底同步拉取)
        self.interval = _clamp_interval(
            settings.news_poll_interval_seconds if interval is None else interval
        )
        self._thread: threading.Thread | None = None
        self._supervisor: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.RLock()
        self._cycles = 0
        self._total_new = 0
        self._last_new_count = 0
        self._last_poll_at: str | None = None
        self._last_pushed_at: str | None = None
        self._consecutive_errors = 0
        self._last_error: str | None = None
        self._restarts = 0
        self._fallback_at = 0.0
        self._last_fallback_at: str | None = None
        self._fallback_new = 0

    # ── 生命周期 ────────────────────────────────────────────────────
    def start(self) -> bool:
        """启动后台抓取线程与守护线程(幂等)。interval<=0 时不启动, 返回 False。"""
        if self.interval <= 0:
            logger.info("快讯实时抓取已关闭 (NEWS_POLL_INTERVAL_SECONDS=0)")
            return False
        with self._lock:
            if self._thread and self._thread.is_alive():
                return True
            self._start_worker_locked()
            if not (self._supervisor and self._supervisor.is_alive()):
                self._supervisor = threading.Thread(
                    target=self._supervise, name="news-poller-supervisor", daemon=True
                )
                self._supervisor.start()
        logger.info("7x24 快讯实时抓取已启动: 每 %.0f 秒一次", self.interval)
        return True

    def ensure_running(self) -> bool:
        """存活保障: 抓取线程意外退出时重新拉起(幂等)。真正拉起才返回 True。"""
        with self._lock:
            if self.interval <= 0 or (self._thread and self._thread.is_alive()):
                return False
            self._start_worker_locked()
            self._restarts += 1
            restarts = self._restarts
        logger.warning("快讯抓取线程意外退出, 已重新拉起(第 %d 次)", restarts)
        return True

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        for name in ("_thread", "_supervisor"):
            thread = getattr(self, name)
            if thread and thread.is_alive():
                thread.join(timeout=timeout)
            setattr(self, name, None)

    def _start_worker_locked(self) -> None:
        """调用方需持有 self._lock。"""
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="news-poller", daemon=True)
        self._thread.start()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    @property
    def supervising(self) -> bool:
        return bool(self._supervisor and self._supervisor.is_alive())

    @property
    def stall_threshold(self) -> float:
        """多久没有一次成功抓取就算「停滞」: 8 个抓取周期, 下限 120 秒。"""
        return max(120.0, self.interval * 8)

    # ── 一次抓取 ────────────────────────────────────────────────────
    def poll_once(self) -> dict:
        """抓一次上游并推送新条目。返回本次结果(测试与状态展示都用它)。"""
        before = flash_feed.updated_at
        added = self.news_service.refresh_flash_store()
        # 上游成功才有 updated_at 前进; 失败只在池子上留 last_error
        ok = flash_feed.updated_at > before

        now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._lock:
            self._cycles += 1
            if ok:
                self._consecutive_errors = 0
                self._last_error = None
                self._last_poll_at = now_text
                self._last_new_count = len(added)
                self._total_new += len(added)
            else:
                self._consecutive_errors += 1
                self._last_error = flash_feed.last_error or "上游无响应"
            failures = self._consecutive_errors

        # 主源持续失败: 时间线不能跟着一起停, 切多源合并池兜住
        fallback_added: list[dict] = []
        if not ok and failures >= FALLBACK_AFTER_FAILURES:
            fallback_added = self._poll_fallback(now_text)

        if added:
            self._push_news(len(added), now_text)

        return {
            "ok": ok,
            "new": len(added),
            "fallback_new": len(fallback_added),
            "stored": len(flash_feed),
            "updated_at": _iso(flash_feed.updated_at),
            "latest": flash_feed.latest_time(),
            "error": None if ok else self._last_error,
        }

    def _push_news(self, new_count: int, now_text: str) -> None:
        """有新条目才推 SSE —— 没新内容时推了也只是让前端白重取一次。"""
        self.news_service.save_flash_store()
        if self.quote_service is None:
            return
        self.quote_service.notify_news_updated({
            "new": new_count,
            "stored": len(flash_feed),
            "latest": flash_feed.latest_time(),
        })
        with self._lock:
            self._last_pushed_at = now_text

    def _poll_fallback(self, now_text: str) -> list[dict]:
        """降级源: 主源不可用时改用多源合并池补条目, 让时间线不断档。

        最短间隔照收 —— 降级失败也要记时刻, 否则主源长时间挂掉时会按抓取节奏
        反复去打五个上游。
        """
        moment = time.monotonic()
        with self._lock:
            if moment - self._fallback_at < FALLBACK_MIN_INTERVAL_SECONDS:
                return []
            self._fallback_at = moment
        try:
            added = self.news_service.refresh_flash_from_pool()
        except Exception as exc:  # 降级失败只记录, 主循环继续按节奏重试
            logger.warning("快讯降级源抓取失败: %s", exc)
            return []
        if not added:
            return []
        with self._lock:
            self._last_fallback_at = now_text
            self._fallback_new = len(added)
        logger.info("主源不可用, 已由多源合并池补入 %d 条快讯", len(added))
        self._push_news(len(added), now_text)
        return added

    def _loop(self) -> None:
        self._stop.wait(BOOT_DELAY_SECONDS)
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                self.poll_once()
            except Exception as exc:  # 单轮异常不能让线程退出
                logger.warning("快讯抓取循环异常: %s", exc)
                self._note_round_failure(str(exc))
            try:
                # 抖动 ±20%: 多个实例/长跑进程不要长期踩在上游同一秒的节拍上
                wait = self.interval * random.uniform(0.8, 1.2) - (time.monotonic() - started)
            except Exception:  # 节奏计算偶发异常兜底成固定间隔, 不能把循环带走
                wait = self.interval
            self._stop.wait(max(1.0, wait))

    def _supervise(self) -> None:
        """守护循环: 抓取线程意外退出就拉起 —— 「全天候不停抓」不能只赌线程不崩。"""
        while not self._stop.is_set():
            self._stop.wait(SUPERVISOR_INTERVAL_SECONDS)
            if self._stop.is_set():
                break
            try:
                self.ensure_running()
            except Exception as exc:  # 守护自身异常不影响下一次检查
                logger.warning("快讯抓取守护检查异常: %s", exc)

    def _note_round_failure(self, error: str) -> None:
        with self._lock:
            self._consecutive_errors += 1
            self._last_error = error[:200]

    # ── 状态 ────────────────────────────────────────────────────────
    def get_status(self) -> dict:
        success_at = flash_feed.updated_at
        stalled_seconds = round(time.time() - success_at, 1) if success_at else None
        with self._lock:
            return {
                "running": self.running,
                "supervising": self.supervising,
                "enabled": self.interval > 0,
                "interval_seconds": round(self.interval, 1),
                "cycles": self._cycles,
                "total_new": self._total_new,
                "last_new_count": self._last_new_count,
                "last_poll_at": self._last_poll_at,
                "last_pushed_at": self._last_pushed_at,
                "last_success_at": _iso(success_at),
                "stalled_seconds": stalled_seconds,
                "stalled": stalled_seconds is not None and stalled_seconds > self.stall_threshold,
                "consecutive_errors": self._consecutive_errors,
                "last_error": self._last_error,
                "restarts": self._restarts,
                "last_fallback_at": self._last_fallback_at,
                "fallback_new": self._fallback_new,
                "stored": len(flash_feed),
                "source_updated_at": _iso(flash_feed.updated_at),
                "latest_flash_time": flash_feed.latest_time(),
                "beijing_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
