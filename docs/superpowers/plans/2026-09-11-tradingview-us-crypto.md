# TradingView 美股与加密货币数据全套集成实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `tickflow-stock-panel` 中深度集成 `tradingview-screener` 开源库，将美股（US）与加密货币（Crypto）作为全局核心市场接入，打通云端选股扫描、自选股跟踪与实时行情刷新。

**Architecture:** 采用独立插件驱动的混合架构（Hybrid Plugin Architecture）。在 `backend/app/plugins/tradingview/` 封装统一的客户端、选股预设与批量行情拉取；在 `backend/app/markets.py` 注册 `crypto` 市场；前后端全局市场切换器扩展为 `[A股 | 港股 | 美股 | 加密货币]`，Screener 与 Watchlist 自动分流并提供自适应精度展示。

**Tech Stack:** Python 3.12, FastAPI, `tradingview-screener`, TypeScript, React 18, TailwindCSS.

---

## Proposed Tasks

### Task 1: 依赖管理与环境配置 (Dependencies & Configuration)
- [x] **Step 1**: 在 `backend/pyproject.toml` 的 `dependencies` 中添加 `"tradingview-screener>=3.2.0"`
- [x] **Step 2**: 在 `.env` 中增加 `TRADINGVIEW_PROXY=` 与 `TRADINGVIEW_SESSION_ID=`
- [x] **Step 3**: 在 `backend/app/config.py` 的 Settings 中声明这两个配置项并提供默认值
- [x] **Step 4**: 执行 `uv sync` 或 `uv pip install` 验证依赖就绪
- [x] **Step 5**: Commit: `chore: add tradingview-screener dependency and config`

---

### Task 2: 核心市场注册表扩展 (Market Registry Extension)
- [x] **Step 1**: 编写针对 `crypto` 市场的单元测试 `test_markets_crypto.py`
- [x] **Step 2**: 运行测试验证失败（`MARKET_CRYPTO` 未定义）
- [x] **Step 3**: 在 `backend/app/markets.py` 中定义 `MARKET_CRYPTO = "crypto"`，更新 `ALL_MARKETS`、`_META`、`market_of` 与 `normalize_symbol`
- [x] **Step 4**: 运行测试验证通过
- [x] **Step 5**: Commit: `feat(markets): register crypto market in backend market registry`

---

### Task 3: TradingView 专用数据服务插件 (TradingView Data Plugin)
- [x] **Step 1**: 编写 `test_tradingview_plugin.py` 测试客户端、选股预设与批量行情查询
- [x] **Step 2**: 实现 `client.py`：支持代理与会话 Cookie、内存 TTL 缓存（15~30s）
- [x] **Step 3**: 实现 `screener.py`：美股与加密货币预设策略（突破、RSI超卖、MACD金叉等）及字段标准化
- [x] **Step 4**: 实现 `quotes.py`：批量标的行情高速获取
- [x] **Step 5**: 运行测试验证通过
- [x] **Step 6**: Commit: `feat(plugin): implement tradingview data plugin for US and crypto`

---

### Task 4: 选股器服务与 API 路由对接 (Screener API Integration)
- [x] **Step 1**: 编写 `test_screener_us_crypto.py`，验证 `market="us"` 与 `market="crypto"` 时的预设策略和执行结果
- [x] **Step 2**: 在 `ScreenerService` 和 `app/api/screener.py` 中增加对 `us` 和 `crypto` 市场的策略分流与扫描执行
- [x] **Step 3**: 运行测试验证通过
- [x] **Step 4**: Commit: `feat(screener): connect screener endpoints to TradingView service for US and crypto`

---

### Task 5: 自选股与行情跨市场搜索与刷新 (Watchlist & Quote Service)
- [x] **Step 1**: 编写 `test_watchlist_crypto.py` 验证美股/加密代币的搜索与自选股报价返回
- [x] **Step 2**: 在 `app/api/watchlist.py` 中增加跨市场代码识别，结合 TradingView 批量行情填补美股与加密标的最新价格与涨跌幅
- [x] **Step 3**: 运行测试验证通过
- [x] **Step 4**: Commit: `feat(watchlist): support US stocks and crypto in watchlist search and live quotes`

---

### Task 6: 前端全局市场与 UI 适配 (Frontend Integration)
- [x] **Step 1**: 更新 `market.tsx` 中的 `Market` 类型与中文标签 `'加密货币'`
- [x] **Step 2**: 更新 `Layout.tsx` 的 `MarketSwitcher` 为四市场按钮，并在 `crypto` 模式下展示核心风向标（BTC/ETH/SOL）
- [x] **Step 3**: 更新 `format.ts`，为小额代币提供自适应多位小数精度格式化
- [x] **Step 4**: 运行 `pnpm build` 验证前端无 TypeScript 错误
- [x] **Step 5**: Commit: `feat(ui): add crypto market to global switcher and optimize price formatting`

---

### Task 7: 全系统端到端验证与服务重启 (Verification & Restart)
- [x] **Step 1**: 运行全套后端测试：`pytest tests/` (61 passed)
- [x] **Step 2**: 验证前端构建与 live API 访问通过
- [x] **Step 3**: 验证 `./dev.sh` 服务运行健康正常
