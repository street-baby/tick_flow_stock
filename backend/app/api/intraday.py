"""行情状态 / SSE 推送 API。

盘中选股相关端点已迁移至策略页面，此处仅保留全局行情基础设施。
SSE 推送四种事件 (使用标准 SSE event 字段):
  - quotes_updated: 行情数据刷新，前端 invalidate 对应 query
  - strategy_results_updated: 策略监控已写入最新结果，前端刷新策略个股列表
  - strategy_alert: 策略监控/告警触发，前端弹通知
  - depth_updated: 五档盘口修正完成，前端刷新连板梯队/看板封单数据
"""
from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Query, Request
from sse_starlette.sse import EventSourceResponse

router = APIRouter(prefix="/api/intraday", tags=["quotes"])


def _get_quote_service(request: Request):
    """获取全局 QuoteService。"""
    return getattr(request.app.state, "quote_service", None)


def _fallback_index_quotes_from_daily(request: Request, symbols: list[str] | None = None) -> list[dict]:
    """实时指数缓存为空时，从本地指数日 K 取最近收盘价作为兜底。"""
    repo = getattr(request.app.state, "repo", None)
    if not repo:
        return []

    params: list[str] = []
    symbol_filter = ""
    if symbols:
        placeholders = ", ".join("?" for _ in symbols)
        symbol_filter = f"WHERE symbol IN ({placeholders})"
        params.extend(symbols)

    try:
        rows = repo.execute_all(
            f"""
            WITH ranked AS (
                SELECT symbol, date, close,
                       row_number() OVER (PARTITION BY symbol ORDER BY date DESC) AS rn
                FROM kline_index_daily
                {symbol_filter}
            ), latest AS (
                SELECT symbol,
                       max(CASE WHEN rn = 1 THEN date END) AS date,
                       max(CASE WHEN rn = 1 THEN close END) AS last_price,
                       max(CASE WHEN rn = 2 THEN close END) AS prev_close
                FROM ranked
                WHERE rn <= 2
                GROUP BY symbol
            )
            SELECT latest.symbol, latest.date, latest.last_price, latest.prev_close
            FROM latest
            ORDER BY latest.symbol
            """,
            params,
        )
    except Exception:  # noqa: BLE001
        return []

    out: list[dict] = []
    for symbol, dt, last_price, prev_close in rows:
        change_amount = None
        change_pct = None
        if last_price is not None and prev_close not in (None, 0):
            change_amount = float(last_price) - float(prev_close)
            change_pct = change_amount / float(prev_close) * 100
        out.append({
            "symbol": symbol,
            "name": None,
            "date": str(dt) if dt else None,
            "last_price": float(last_price) if last_price is not None else None,
            "close": float(last_price) if last_price is not None else None,
            "prev_close": float(prev_close) if prev_close is not None else None,
            "change_amount": change_amount,
            "change_pct": change_pct,
            "source": "index_daily",
        })
    return out


@router.get("/status")
def status(request: Request):
    """行情状态 (来自全局 QuoteService)。"""
    qs = _get_quote_service(request)
    if qs:
        return qs.status()
    return {"enabled": False, "running": False, "symbol_count": 0, "index_symbol_count": 0,
            "quote_age_ms": None, "is_trading_hours": False, "last_fetch_ms": None}


@router.get("/indices")
def index_quotes(
    request: Request,
    symbols: str | None = Query(None, description="逗号分隔的指数 symbol 列表"),
):
    """返回实时指数行情缓存，优先使用实时源。"""
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()] if symbols else None
    qs = _get_quote_service(request)
    if qs:
        df = qs.get_index_quotes(symbol_list)
        if not df.is_empty():
            return {"rows": df.to_dicts(), "count": len(df), "source": "realtime"}

    # 1. 优先从智兔数服 (Zhitu) 获取即时行情
    try:
        from app.data_providers import custom as custom_sources
        provider = custom_sources.get_provider("zhitu")
        if provider and hasattr(provider, "get_index_quotes"):
            rows = provider.get_index_quotes(symbol_list or ["000001.SH", "399001.SZ", "399006.SZ", "000680.SH", "000688.SH", "000300.SH"])
            if rows:
                return {"rows": rows, "count": len(rows), "source": "zhitu"}
    except Exception as e:
        logger.debug("智兔指数实时行情获取异常: %s", e)

    # 2. 在线备选实时源获取指数即时行情
    try:
        import httpx
        from app.market_time import cn_now

        now_str = cn_now().strftime("%Y-%m-%d")
        sina_map = {
            "000001.SH": "s_sh000001",
            "399001.SZ": "s_sz399001",
            "399006.SZ": "s_sz399006",
            "000680.SH": "s_sh000680",
            "000688.SH": "s_sh000688",
            "000300.SH": "s_sh000300",
            "000016.SH": "s_sh000016",
            "000905.SH": "s_sh000905",
            "399005.SZ": "s_sz399005",
            "000002.SH": "s_sh000002",
            "000003.SH": "s_sh000003",
            "000004.SH": "s_sh000004",
            "000005.SH": "s_sh000005",
            "000006.SH": "s_sh000006",
            "000007.SH": "s_sh000007",
            "000008.SH": "s_sh000008",
            "000009.SH": "s_sh000009",
            "000010.SH": "s_sh000010",
        }
        req_symbols = symbol_list if symbol_list else list(sina_map.keys())
        sina_keys = [sina_map[s] for s in req_symbols if s in sina_map]
        if sina_keys:
            url = f"http://hq.sinajs.cn/list={','.join(sina_keys)}"
            resp = httpx.get(url, headers={"Referer": "https://finance.sina.com.cn"}, timeout=3.0)
            if resp.status_code == 200:
                rows: list[dict] = []
                # 解析: var hq_str_s_sh000001="上证指数,3906.1151,11.6927,0.30,2816737,57693833";
                sym_by_sina = {v: k for k, v in sina_map.items()}
                for line in resp.text.splitlines():
                    if '="' not in line:
                        continue
                    k_part, v_part = line.split('="', 1)
                    var_name = k_part.replace("var hq_str_", "").strip()
                    val_str = v_part.rstrip('";').strip()
                    if not val_str:
                        continue
                    parts = val_str.split(",")
                    if len(parts) >= 6:
                        name = parts[0]
                        price = float(parts[1])
                        change_amt = float(parts[2])
                        change_pct = float(parts[3])
                        vol = float(parts[4])
                        amt = float(parts[5]) * 10000.0  # 万元转元
                        prev_close = price - change_amt
                        orig_sym = sym_by_sina.get(var_name, var_name)
                        rows.append({
                            "symbol": orig_sym,
                            "name": name,
                            "date": now_str,
                            "last_price": price,
                            "close": price,
                            "prev_close": prev_close,
                            "change_amount": change_amt,
                            "change_pct": change_pct,
                            "volume": vol,
                            "amount": amt,
                            "source": "live_realtime",
                        })
                if rows:
                    return {"rows": rows, "count": len(rows), "source": "live_realtime"}
    except Exception as e:
        logger.debug("在线拉取实时指数行情异常: %s", e)

    rows = _fallback_index_quotes_from_daily(request, symbol_list)
    return {"rows": rows, "count": len(rows), "source": "index_daily"}


@router.get("/stream")
async def quote_stream(request: Request):
    """SSE 端点: 行情更新 + 告警推送 + 五档修正 + 复盘进度。

    使用 sse-starlette EventSourceResponse:
    - 标准 SSE event 字段，前端按 event name 监听
    - 内置断线检测，客户端断开立即终止 generator
    - 内置 ping 心跳，保持连接活跃

    每个连接注册一个独立订阅者 (QuoteSubscriber: 独立事件 + 独立队列),
    事件由 QuoteService 广播 — 多客户端 (多标签页/设备) 各自收到全量事件。
    此前四通道共用服务级 Event + pop 取走语义, 告警只会被先醒的连接消费。
    """
    qs = _get_quote_service(request)

    async def event_generator():
        if qs is None:
            # 无行情服务: 保持连接 (EventSourceResponse 自带 ping), 不推事件
            while True:
                await asyncio.sleep(30)

        sub = qs.subscribe()
        try:
            while True:
                # 等待任一通道有新信号 (5s 超时保持循环, 便于断线时尽快退出)
                await asyncio.to_thread(sub.wait, 5.0)
                data = sub.pop()

                # 告警 (分片推送, 避免单条 SSE 过大)
                alerts = data["alerts"]
                for chunk_start in range(0, len(alerts), 20):
                    chunk = alerts[chunk_start:chunk_start + 20]
                    yield {
                        "event": "strategy_alert",
                        "data": json.dumps({
                            "ts": int(time.time() * 1000),
                            "alerts": chunk,
                        }, ensure_ascii=False),
                    }

                # 复盘进度 (定时复盘流式生成时) — 前端 reviewStore 直接消费
                # 事件已是 recap_market_stream 产出的 JSON 字符串, 逐条转发
                for evt_json in data["reviews"]:
                    yield {
                        "event": "review_progress",
                        "data": evt_json,
                    }

                # 行情更新
                if data["quote_updated"]:
                    yield {
                        "event": "quotes_updated",
                        "data": json.dumps({
                            "ts": int(time.time() * 1000),
                            "symbol_count": qs._symbol_count,
                        }),
                    }

                # 策略监控完成后, 结果已写入内存缓存; 独立通知只刷新策略个股列表。
                if data["strategy_results_updated"]:
                    yield {
                        "event": "strategy_results_updated",
                        "data": json.dumps({"ts": int(time.time() * 1000)}),
                    }

                # 五档修正完成 — 前端刷新连板梯队封单数据
                if data["depth_updated"]:
                    yield {
                        "event": "depth_updated",
                        "data": json.dumps({
                            "ts": int(time.time() * 1000),
                        }),
                    }
        finally:
            qs.unsubscribe(sub)

    return EventSourceResponse(event_generator())


@router.post("/refresh")
def refresh_quotes(request: Request):
    """手动刷新一次行情数据。"""
    qs = _get_quote_service(request)
    if qs:
        return qs.refresh()
    return {"error": "QuoteService not available"}
