# TradingView 美股与加密货币数据全套集成技术方案

**创建日期**：2026-09-11  
**状态**：已评审 (Approved)  
**目标**：在 `tickflow-stock-panel` 中深度集成 TradingView 数据能力，扩展支持全球美股与加密货币市场的实时选股、行情监控与自选跟踪。

---

## 1. 背景与目标

### 1.1 背景
系统目前的核心行情与选股服务主要聚焦于国内 A 股市场（依赖本地 DuckDB、Polars 增量计算与本土实时行情源）。随着多资产多市场交易需求增加，需要将**美股市场（US Stocks）**与**加密货币市场（Crypto）**作为一等公民无缝融入系统。

### 1.2 核心目标
1. **全局市场扩展**：在系统全局市场体系中，将 `crypto`（加密货币）正式升为核心市场之一，形成 `A股 (cn)`、`港股 (hk)`、`美股 (us)`、`加密货币 (crypto)` 四大市场协同矩阵；
2. **云端指标选股 (Screener)**：通过引入开源 `tradingview-screener` 库，直接利用 TradingView 云端已预计算好的 3000+ 技术指标与财务数据，为美股与加密货币提供秒级出结果的实时策略筛选；
3. **自选股与盯盘 (Watchlist & Quotes)**：支持搜索、添加美股代码（如 `AAPL.US`, `NVDA.US`, `TSLA.US`）和加密货币交易对（如 `BTCUSDT`, `ETHUSDT`, `SOLUSDT`），提供低延迟批量行情刷新；
4. **环境自适应**：免 Key 开箱即用，同时在 `.env` 中提供可选的代理（`TRADINGVIEW_PROXY`）与 Session Cookie（`TRADINGVIEW_SESSION_ID`）配置支持。

---

## 2. 总体架构设计

系统采用**独立插件驱动的混合架构**（Hybrid Plugin Architecture），实现云端指标与本地引擎的优雅互补。

```
┌────────────────────────────────────────────────────────────────────────┐
│                                前端 UI 层                              │
│  - Layout: 全局市场切换器 [A股 | 港股 | 美股 | 加密货币]               │
│  - Screener: 美股/加密货币专属预设策略卡片与多因子选股表格              │
│  - Watchlist: 跨市场自选列表，支持美股与加密货币自适应精度价格展示     │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │ HTTP REST API
┌────────────────────────────────────▼───────────────────────────────────┐
│                                后端 API 层                             │
│  - /api/markets: 注册 cn, hk, us, crypto 元数据规范                    │
│  - /api/screener: 按 market 参数智能分流 (cn->DuckDB, us/crypto->TV)   │
│  - /api/watchlist: 统一支持跨市场标的搜索与批量行情刷新                │
└────────────────────────────────────┬───────────────────────────────────┘
                                     │
           ┌─────────────────────────┴─────────────────────────┐
           ▼                                                   ▼
┌───────────────────────────────┐               ┌───────────────────────────────┐
│        A 股 / 港股引擎        │               │     TradingView 插件引擎      │
│  - 本地 DuckDB 存储           │               │  - app/plugins/tradingview/   │
│  - Polars Enriched 矩阵计算   │               │  - tradingview_screener 库    │
│  - 连板/游资龙虎榜/首阴战法   │               │  - 内存短缓存 (TTL 15~30s)    │
│  - 智兔 / TickFlow 本土数据源 │               │  - 自动适配 Proxy & Cookie    │
└───────────────────────────────┘               └───────────────────────────────┘
```

---

## 3. 详细模块设计

### 3.1 市场元数据规范 (`backend/app/markets.py`)
1. **枚举扩展**：
   ```python
   MARKET_CN = "cn"
   MARKET_HK = "hk"
   MARKET_US = "us"
   MARKET_CRYPTO = "crypto"

   ALL_MARKETS = [MARKET_CN, MARKET_HK, MARKET_US, MARKET_CRYPTO]
   ```
2. **市场属性定义 (`MarketMeta`)**：
   * `crypto` 市场：`t_plus=0`，`stamp_tax=0.0`，`lot_size=1`，`price_round=0.0001`，`has_limit=False`，交易时段为 `sessions=24/7 全天候`。
3. **Symbol 规范与归一化 (`normalize_symbol` & `market_of`)**：
   * 美股：支持 `AAPL.US`, `TSLA.US` 或无后缀 `NVDA`；
   * 加密货币：以 `USDT` 计价对为主，如 `BTCUSDT`, `ETHUSDT`, `SOLUSDT`，或带交易所前缀 `BINANCE:BTCUSDT`，统一识别为 `crypto` 市场。

### 3.2 TradingView 专用数据插件 (`backend/app/plugins/tradingview/`)
在 `backend/app/plugins/tradingview/` 下实现核心服务：
* `client.py`：
  * 封装 `tradingview_screener` 调用；
  * 读取 `.env` 中的 `TRADINGVIEW_PROXY`（如配置了 `http://127.0.0.1:7890` 则注入 Session 代理）；
  * 读取可选的 `TRADINGVIEW_SESSION_ID`；
  * 实现带 TTL（15~30 秒）的轻量 LRU 内存缓存，防止重复请求触发限流；
* `screener.py`：
  * 定义美股与加密货币的预设扫描器（Presets）；
  * 执行云端 Query 构建与过滤；
  * 字段标准化清洗：转换为前端统一的 `{symbol, name, close, change_pct, volume, market_cap, rsi, macd, pe, rating}`。
* `quotes.py`：
  * 批量报价查询：给定多个 symbol，通过 `Query().where(col('name').isin(symbols))` 单次请求拉取所有标的最新行情（耗时 ~150-250ms）。

### 3.3 预设选股策略库
#### 美股精选策略 (US Presets)
1. **放量大涨突破 (High Volume Momentum)**：日涨幅 > 3%，相对成交量 > 1.5 倍，收盘站在 MA20 之上，市值 > 10 亿美元；
2. **RSI 超卖反弹 (RSI Oversold Bounce)**：RSI(14) < 32，今日收红盘阳线；
3. **MACD 黄金交叉 (MACD Golden Cross)**：日线 MACD 上穿 Signal 信号线，成交量放大；
4. **蓝筹巨头动量榜 (Megacap Leaders)**：市值 > 1000 亿美元，MA20 > MA50 多头排列；
5. **TradingView 强烈买入 (Strong Buy)**：TradingView 云端技术综合评分评级为 Strong Buy。

#### 加密货币精选策略 (Crypto Presets)
1. **24H 暴涨动量榜 (24H Top Gainers)**：24小时涨幅 > 5%，24小时成交量 > 1000 万美元；
2. **大市值主流币强势榜 (Major Crypto Leaders)**：锁定 BTC、ETH、SOL、BNB 等百大币种，按技术多头与涨幅排行；
3. **主力放量突破 (Volume Breakout)**：成交量激增 200% 以上，向上突破；
4. **RSI 极度超卖抄底 (RSI Extreme Oversold)**：RSI(14) < 30 极度超卖区寻找超跌反弹；
5. **多周期金叉共振 (Multi-Timeframe Golden Cross)**：日线级别多头 + 1 小时级别 MACD 金叉。

### 3.4 前端界面与交互调整
1. **全局市场切换器 (`frontend/src/lib/market.tsx` & `Layout.tsx`)**：
   * `Market` 类型更新为 `'cn' | 'hk' | 'us' | 'crypto'`；
   * `MarketSwitcher` 显示四个选项：`[ A股 | 港股 | 美股 | 加密货币 ]`；
   * 顶栏风向标在 `crypto` 模式下展示：`BTC/USDT`, `ETH/USDT`, `SOL/USDT`。
2. **自选股与价格格式 (`frontend/src/pages/Watchlist.tsx` & `frontend/src/lib/format.ts`)**：
   * 搜索框支持直接搜索美股代码（AAPL, TSLA, NVDA）与加密货币（BTC, ETH, SOL, DOGE）；
   * 价格展示精度自适应：价格 ≥ $1 显示 2 位小数；价格 < $1 显示 4~6 位小数。

---

## 4. 异常处理与稳定性保障

1. **限流保护**：
   * 接口层引入本地内存缓存，防止前端组件重复刷新触发频控；
   * TradingView 请求统一设置 10 秒超时，防止网络偶发抖动造成前端长时间卡死。
2. **降级机制**：
   * 如果网络直连无法到达 TradingView，日志明确提示是否需要配置 `TRADINGVIEW_PROXY`；
   * 失败时返回空结果集并附带友好错误提示，不影响 A 股和港股功能。

---

## 5. 测试与验证计划

1. **依赖与接口测试**：
   * 在虚拟环境中安装 `tradingview-screener`；
   * 编写单元测试验证美股与加密货币的 Query 构造与返回数据完整性。
2. **端到端 API 测试**：
   * 验证 `GET /api/screener/strategies?market=us` 与 `GET /api/screener/strategies?market=crypto`；
   * 验证选股器执行端点返回字段；
   * 验证自选股批量行情获取与搜索。
3. **前端 UI 校验**：
   * 切换四个市场，验证 UI 响应、表格渲染和价格格式化。
