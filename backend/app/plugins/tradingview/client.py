# -*- coding: utf-8 -*-
"""TradingView API 客户端与网络适配器。

职责:
1. 封装代理 (TRADINGVIEW_PROXY) 与认证 Session (TRADINGVIEW_SESSION_ID)；
2. 提供带 TTL 的线程安全内存短缓存，防止前端频繁轮询触发 Cloudflare 限流；
3. 超时与异常降级控制。
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from typing import Any, Callable

from app.config import settings

logger = logging.getLogger(__name__)

# 线程安全的轻量内存缓存
_CACHE_LOCK = threading.RLock()
_CACHE: dict[str, tuple[float, Any]] = {}
DEFAULT_CACHE_TTL = 20.0  # 秒


def get_request_kwargs() -> dict[str, Any]:
    """组装传递给 requests.post 的参数（代理、Cookie、超时等）。"""
    kwargs: dict[str, Any] = {
        "timeout": 15,
        "headers": {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
            ),
        },
    }

    # 代理配置 (HTTP / HTTPS / SOCKS5)
    proxy = (getattr(settings, "tradingview_proxy", "") or "").strip()
    if proxy and not proxy.startswith("#") and (proxy.startswith("http://") or proxy.startswith("https://") or proxy.startswith("socks5://")):
        kwargs["proxies"] = {
            "http": proxy,
            "https": proxy,
        }

    # 会话 Cookie 配置
    session_id = (getattr(settings, "tradingview_session_id", "") or "").strip()
    if session_id and not session_id.startswith("#"):
        kwargs["cookies"] = {
            "sessionid": session_id,
        }

    return kwargs


def cached_query(cache_key: str, fetch_fn: Callable[[], Any], ttl: float = DEFAULT_CACHE_TTL) -> Any:
    """对无状态的高开销 API 查询实施短 TTL 缓存。"""
    now = time.time()
    with _CACHE_LOCK:
        if cache_key in _CACHE:
            ts, val = _CACHE[cache_key]
            if now - ts < ttl:
                return val

    # 缓存穿透后执行查询
    try:
        val = fetch_fn()
    except Exception as e:
        logger.warning("TradingView API 查询失败 (%s): %s", cache_key, e)
        # 如果缓存里有旧数据，降级返回旧数据避免直接报错
        with _CACHE_LOCK:
            if cache_key in _CACHE:
                _, old_val = _CACHE[cache_key]
                logger.info("降级使用历史缓存数据: %s", cache_key)
                return old_val
        raise

    with _CACHE_LOCK:
        # 清理过期缓存，控制字典大小
        if len(_CACHE) > 500:
            expired_keys = [k for k, (ts, _) in _CACHE.items() if now - ts > ttl * 2]
            for k in expired_keys:
                _CACHE.pop(k, None)
        _CACHE[cache_key] = (now, val)

    return val


def make_cache_key(prefix: str, payload: Any) -> str:
    serialized = json.dumps(payload, sort_keys=True, default=str)
    h = hashlib.md5(serialized.encode("utf-8")).hexdigest()
    return f"{prefix}:{h}"
