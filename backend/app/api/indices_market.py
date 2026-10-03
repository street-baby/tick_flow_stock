"""港美股主要指数 API（多市场扩展）。

数据来自腾讯免费接口（TickFlow 免费模式无港美股指数），由
services/index_sync_market.sync_market_indices 同步到本地。

crypto 市场：实时交易所公开数据（Bybit 优先，services/crypto_klines），
无本地存储、无需同步；list/quotes 走 /v5/market/tickers，daily/minute 走 K 线接口。
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request

from app.services import index_sync_market

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/indices/market", tags=["indices-market"])

# crypto "指数" 固定清单（主流币，前端置顶展示; symbols 与交易所现货对一致）
_CRYPTO_PINNED = [
    {"symbol": "BTCUSDT", "name": "比特币"},
    {"symbol": "ETHUSDT", "name": "以太坊"},
    {"symbol": "SOLUSDT", "name": "Solana"},
    {"symbol": "BNBUSDT", "name": "BNB"},
    {"symbol": "DOGEUSDT", "name": "狗狗币"},
]


# ================================================================
# crypto 分支: 与港美股端点同构, 数据全部实时来自交易所 (无本地 parquet)
# ================================================================

def _crypto_quote_rows(symbols: list[dict] | None = None) -> list[dict]:
    """crypto 清单 + 实时行情 (Bybit tickers; 失败时行情字段为空但不炸接口)。"""
    from app.services import crypto_klines
    pins = symbols or _CRYPTO_PINNED
    tickers = {t["symbol"]: t for t in crypto_klines.fetch_crypto_tickers()}
    out = []
    for item in pins:
        t = tickers.get(item["symbol"])
        if t:
            out.append({
                "symbol": item["symbol"], "name": item["name"],
                "date": "", "close": t["last"], "last_price": t["last"],
                "change_pct": t["change_pct"], "pct": t["change_pct"],
            })
        else:
            out.append({"symbol": item["symbol"], "name": item["name"],
                        "date": "", "close": None, "last_price": None,
                        "change_pct": None, "pct": None})
    return out


@router.get("/crypto/list")
def crypto_indices_list():
    """crypto 指数清单（对齐 /list 返回格式; 固定主流币清单）。"""
    return {"results": [dict(item, asset_type="crypto") for item in _CRYPTO_PINNED], "count": len(_CRYPTO_PINNED)}


@router.get("/crypto/quotes")
def crypto_indices_quotes():
    """crypto 实时行情（对齐 /quotes 返回格式; Bybit 24h ticker）。"""
    rows = _crypto_quote_rows()
    return {"rows": rows, "count": len(rows)}


@router.get("/crypto/daily")
def crypto_indices_daily(symbol: str = Query(...), days: int = Query(180, ge=30, le=800)):
    """crypto 日K（对齐 /daily 返回格式; 交易所实时日K, 含今天未收盘根）。"""
    from datetime import date as _date
    from app.services import crypto_klines
    if not crypto_klines.is_crypto_symbol(symbol):
        raise HTTPException(status_code=400, detail="symbol 不是加密货币形态")
    days_n = int(getattr(days, "default", 180)) if type(days).__name__ == "Query" else int(days)
    end = _date.today()
    start = end - timedelta(days=days_n)
    try:
        rows = crypto_klines.fetch_crypto_daily(symbol, start, end)
    except Exception as e:  # noqa: BLE001
        logger.warning("crypto daily failed: %s", e)
        rows = []
    pretty = symbol[:-4] + "/USDT" if symbol.upper().endswith("USDT") else symbol
    name = next((i["name"] for i in _CRYPTO_PINNED if i["symbol"] == symbol.upper()), pretty)
    return {"symbol": symbol, "rows": rows, "index_info": {"symbol": symbol, "name": name}}


@router.get("/crypto/minute")
def crypto_indices_minute(symbol: str = Query(...)):
    """crypto 分时（对齐 /minute 返回格式; 最近 242 根 1m K, UTC）。"""
    from app.services import crypto_klines
    if not crypto_klines.is_crypto_symbol(symbol):
        raise HTTPException(status_code=400, detail="symbol 不是加密货币形态")
    try:
        df = crypto_klines.fetch_crypto_minute_recent(symbol)
    except Exception as e:  # noqa: BLE001
        logger.warning("crypto minute failed: %s", e)
        df = crypto_klines.fetch_crypto_klines(symbol, "1m", 0, 0)  # 空 schema df
    rows = [
        {"datetime": r["datetime"].isoformat(sep="T"), "open": r["open"], "high": r["high"],
         "low": r["low"], "close": r["close"], "volume": r["volume"], "amount": r["amount"]}
        for r in df.to_dicts()
    ]
    return {"symbol": symbol, "rows": rows, "index_info": None}


@router.post("/crypto/sync")
def crypto_indices_sync():
    """crypto 无需同步（实时读取），占位对齐 /sync 语义。"""
    return {"ok": True, "rows": 0, "market": "crypto"}


@router.get("")
def market_indices(request: Request, market: str = Query("hk", description="hk|us|crypto")):
    """港美股指数清单 + 最新收盘/涨跌幅。"""
    if market not in ("hk", "us"):
        raise HTTPException(status_code=400, detail="market 必须为 hk|us")
    items = index_sync_market.list_market_indices(market)
    data_dir = request.app.state.repo.store.data_dir
    daily_dir = Path(data_dir) / f"kline_index_daily_{market}"
    out = []
    for item in items:
        symbol = item["symbol"]
        latest = None
        if daily_dir.exists():
            try:
                import polars as pl
                # 实时快照优先（美股指数 latest_{symbol}.parquet 含 change_pct）
                snap_path = daily_dir / f"latest_{symbol}.parquet"
                if snap_path.exists():
                    snap = pl.read_parquet(snap_path)
                    if not snap.is_empty():
                        r = snap.to_dicts()[0]
                        latest = {
                            "date": str(r.get("date", "")),
                            "close": float(r.get("close", 0)),
                            "change_pct": float(r.get("change_pct") or 0),
                            "snapshot": True,
                        }
                if latest is None:
                    lf = pl.scan_parquet((daily_dir / "date=*" / "*.parquet").as_posix())
                    row = lf.filter(pl.col("symbol") == symbol).sort("date", descending=True).head(2).collect()
                    if row.height >= 2:
                        prev = float(row["close"][-1])
                        cur = float(row["close"][0])
                        latest = {
                            "date": str(row["date"][0]),
                            "close": cur,
                            "change_pct": (cur / prev - 1) if prev else 0.0,
                        }
                    elif row.height == 1:
                        latest = {"date": str(row["date"][0]), "close": float(row["close"][0]), "change_pct": 0.0}
            except Exception as e:  # noqa: BLE001
                logger.warning("index %s latest failed: %s", symbol, e)
        out.append({**item, "latest": latest})
    return {"market": market, "items": out}


@router.get("/kline")
def market_index_kline(
    request: Request,
    market: str = Query("hk"),
    symbol: str = Query(...),
    days: int = Query(250, ge=30, le=800),
):
    """港美股指数日K（含未复权 OHLCV）。"""
    daily_dir = Path(request.app.state.repo.store.data_dir) / f"kline_index_daily_{market}"
    if not daily_dir.exists():
        return {"rows": []}
    import polars as pl
    try:
        lf = pl.scan_parquet((daily_dir / "**" / "*.parquet").as_posix())
        df = (
            lf.filter(pl.col("symbol") == symbol)
            .sort("date", descending=True)
            .head(days)
            .sort("date")
            .collect()
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("index kline failed: %s", e)
        return {"rows": []}
    rows = [
        {"date": str(r["date"]), "open": r["open"], "high": r["high"],
         "low": r["low"], "close": r["close"], "volume": r["volume"]}
        for r in df.to_dicts()
    ]
    return {"symbol": symbol, "market": market, "rows": rows}


# ================================================================
# 与 A 股 /api/index/* 同构的端点（前端复用 A 股 Indices 页渲染）
# ================================================================

@router.get("/list")
def market_indices_list(request: Request, market: str = Query("hk", description="hk|us")):
    """港美股指数清单（对齐 A 股 /api/index/list 返回格式）。"""
    items = index_sync_market.list_market_indices(market)
    return {"results": items, "count": len(items)}


@router.get("/quotes")
def market_indices_quotes(request: Request, market: str = Query("hk", description="hk|us")):
    """港美股指数最新行情（对齐 A 股 /api/index/quotes 返回格式）。"""
    if market not in ("hk", "us"):
        raise HTTPException(status_code=400, detail="market 必须为 hk|us")
    import polars as pl

    data_dir = request.app.state.repo.store.data_dir
    daily_dir = Path(data_dir) / f"kline_index_daily_{market}"
    rows = []
    for item in index_sync_market.list_market_indices(market):
        symbol = item["symbol"]
        latest = None
        if daily_dir.exists():
            try:
                snap = daily_dir / f"latest_{symbol}.parquet"
                if snap.exists():
                    s = pl.read_parquet(snap)
                    if not s.is_empty():
                        r = s.to_dicts()[0]
                        latest = {
                            "date": str(r.get("date", "")),
                            "close": float(r.get("close", 0)),
                            "change_pct": float(r.get("change_pct") or 0),
                            "last_price": float(r.get("close", 0)),
                            "pct": float(r.get("change_pct") or 0),
                        }
                if latest is None:
                    lf = pl.scan_parquet((daily_dir / "date=*" / "*.parquet").as_posix())
                    df = lf.filter(pl.col("symbol") == symbol).sort("date", descending=True).head(2).collect()
                    if df.height >= 2:
                        prev = float(df["close"][-1]); cur = float(df["close"][0])
                        latest = {"date": str(df["date"][0]), "close": cur, "last_price": cur,
                                  "change_pct": (cur / prev - 1) if prev else 0.0, "pct": (cur / prev - 1) if prev else 0.0}
                    elif df.height == 1:
                        cur = float(df["close"][0])
                        latest = {"date": str(df["date"][0]), "close": cur, "last_price": cur, "change_pct": 0.0, "pct": 0.0}
            except Exception as e:  # noqa: BLE001
                logger.warning("index quote %s failed: %s", symbol, e)
        if latest:
            rows.append({"symbol": symbol, "name": item["name"], **latest})
    return {"rows": rows, "count": len(rows)}


@router.get("/daily")
def market_indices_daily(
    request: Request,
    market: str = Query("hk"),
    symbol: str = Query(...),
    days: int = Query(180, ge=30, le=800),
    start: str | None = None,
    end: str | None = None,
):
    """港美股指数日K（对齐 A 股 /api/index/daily 返回格式）。"""
    daily_dir = Path(request.app.state.repo.store.data_dir) / f"kline_index_daily_{market}"
    if not daily_dir.exists():
        return {"symbol": symbol, "rows": [], "index_info": None}
    import polars as pl
    try:
        lf = pl.scan_parquet((daily_dir / "date=*" / "*.parquet").as_posix())
        lf = lf.filter(pl.col("symbol") == symbol)
        if start and end:
            lf = lf.filter((pl.col("date") >= start) & (pl.col("date") <= end))
        else:
            lf = lf.sort("date", descending=True).head(days)
        df = lf.sort("date").collect()
    except Exception as e:  # noqa: BLE001
        logger.warning("index daily failed: %s", e)
        return {"symbol": symbol, "rows": [], "index_info": None}
    rows = [
        {"date": str(r["date"]), "open": r["open"], "high": r["high"],
         "low": r["low"], "close": r["close"], "volume": r["volume"], "amount": 0}
        for r in df.to_dicts()
    ]
    name = next((i["name"] for i in index_sync_market.list_market_indices(market) if i["symbol"] == symbol), symbol)
    return {"symbol": symbol, "rows": rows, "index_info": {"symbol": symbol, "name": name}}


@router.get("/minute")
def market_indices_minute(request: Request, market: str = Query("hk"), symbol: str = Query(...)):
    """港美股指数分时（免费数据源无，返回空）。"""
    return {"symbol": symbol, "rows": [], "index_info": None}


@router.post("/sync")
def market_indices_sync(request: Request, market: str = Query("hk", description="hk|us")):
    """手动同步港美股指数（对齐 A 股 /api/index/sync_daily 语义）。"""
    from app.services.index_sync_market import sync_market_indices

    data_dir = request.app.state.repo.store.data_dir
    n = sync_market_indices(market, Path(data_dir))
    return {"ok": True, "rows": n, "market": market}
