# Terminal Dense Visual Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有多市场股票工作台统一升级为深浅双主题的 Terminal Dense 专业金融终端，同时保留路由、业务逻辑、数据源和交易策略行为。

**Architecture:** 先用 CSS 语义令牌和图表主题建立全站视觉契约，再用少量无业务状态的终端原语统一标题、指标、面板和数据状态。`Layout` 继续承载现有查询与导航，只增加紧凑市场状态条和窄屏导航；页面改造只调整展示编排与样式，不改 API、Query Key、策略计算或交易动作。

**Tech Stack:** React 18、TypeScript、Vite、Tailwind CSS、TanStack Query、Framer Motion、Lucide React、ECharts、lightweight-charts。

---

## File Structure

### New files

- `frontend/src/components/terminal/TerminalPrimitives.tsx`：无业务状态的面板、指标、状态标签和区块标题。
- `frontend/src/components/terminal/MarketStatusBar.tsx`：由 `Layout` 传入市场、数据源、交易阶段、行情延迟和 SSE 状态后渲染全局状态条。
- `frontend/src/components/terminal/DataState.tsx`：统一 loading、empty、error、delayed 和 simulated 状态。

### Foundation files

- `frontend/src/index.css`：深浅主题令牌、终端表面、水流状态线、行情闪烁和减少动态效果。
- `frontend/tailwind.config.ts`：小圆角和现有语义色映射，不增加新依赖。
- `frontend/src/lib/theme.ts`：ECharts/lightweight-charts 的冷青终端调色板。
- `frontend/index.html`：浏览器主题色改为终端冷青色。
- `frontend/src/components/PageHeader.tsx`：支持紧凑标题、元数据和操作区换行。
- `frontend/src/components/EmptyState.tsx`、`frontend/src/components/data/Skeleton.tsx`：接入统一数据状态语言。
- `frontend/src/components/stock-table/StockDataTable.tsx`、`frontend/src/components/stock-table/primitives.tsx`：稳定表头、行高、hover 和移动端滚动。

### Shell and primary pages

- `frontend/src/components/Layout.tsx`
- `frontend/src/pages/Dashboard.tsx`
- `frontend/src/pages/TradePlan.tsx`
- `frontend/src/pages/Screener.tsx`
- `frontend/src/components/screener/ScreenerTable.tsx`
- `frontend/src/pages/Backtest.tsx`
- `frontend/src/pages/backtest/FactorBacktest.tsx`
- `frontend/src/pages/backtest/StrategyBacktest.tsx`
- `frontend/src/pages/backtest/StrategyOptimizer.tsx`
- `frontend/src/pages/backtest/StrategyWalkForward.tsx`
- `frontend/src/pages/backtest/charts/*.tsx`
- `frontend/src/pages/Monitor.tsx`
- `frontend/src/pages/DarkPoolRanking.tsx`
- `frontend/src/pages/Regime.tsx`

### Route-wide compatibility sweep

- `frontend/src/pages/AuctionSnatch.tsx`
- `frontend/src/pages/TomorrowCatalyst.tsx`
- `frontend/src/pages/LimitUpLadder.tsx`
- `frontend/src/pages/Watchlist.tsx`
- `frontend/src/pages/Review.tsx`
- `frontend/src/pages/ConceptAnalysis.tsx`
- `frontend/src/pages/IndustryAnalysis.tsx`
- `frontend/src/pages/StockAnalysis.tsx`
- `frontend/src/pages/Financials.tsx`
- `frontend/src/pages/Data.tsx`
- `frontend/src/pages/settings/*.tsx`
- `frontend/src/components/analysis-shared.tsx`
- `frontend/src/components/financials/*.tsx`
- `frontend/src/components/stock-analysis/*.tsx`
- `frontend/src/components/screener/*.tsx`

## Working Tree Safety

`frontend/src/pages/Dashboard.tsx` and `frontend/src/pages/AuctionSnatch.tsx` already contain user-owned changes. Before editing them, capture their current diffs and preserve every non-visual hunk:

```bash
git diff -- frontend/src/pages/Dashboard.tsx frontend/src/pages/AuctionSnatch.tsx > /tmp/tickflow-preexisting-ui-pages.patch
git status --short
```

Expected: the patch is non-empty and the status still lists the existing backend, packaging, API and page changes. Never restore or overwrite those files from `HEAD`. Commits in this plan must stage only the implementation hunks; when a file has pre-existing changes, review `git diff --cached` before committing.

### Task 1: Establish the Terminal Dense theme contract

**Files:**
- Modify: `frontend/src/index.css`
- Modify: `frontend/tailwind.config.ts`
- Modify: `frontend/src/lib/theme.ts`
- Modify: `frontend/index.html`

- [ ] **Step 1: Record the current build baseline**

Run:

```bash
cd frontend
pnpm build
```

Expected: exit code `0`. If it fails before edits, record the failure and isolate it from this visual change before continuing.

- [ ] **Step 2: Replace the purple quantum palette with semantic terminal tokens**

In `frontend/src/index.css`, keep the existing variable names consumed by Tailwind, add status tokens, and replace the radial-gradient body treatment with a stable terminal surface:

```css
:root {
  --base: 204 24% 97%;
  --surface: 0 0% 100%;
  --elevated: 200 22% 94%;
  --border: 201 18% 82%;
  --border-subtle: 200 18% 89%;
  --fg-primary: 207 28% 12%;
  --fg-secondary: 203 13% 36%;
  --fg-muted: 201 10% 52%;
  --accent: 188 78% 38%;
  --bull: 354 72% 52%;
  --bear: 153 54% 38%;
  --warning: 38 84% 46%;
  --danger: 326 72% 48%;
  --grid-line: 196 32% 72%;
  --water-line: 188 78% 38%;
}

html.dark {
  --base: 210 29% 6%;
  --surface: 207 27% 9%;
  --elevated: 205 24% 13%;
  --border: 199 20% 22%;
  --border-subtle: 201 20% 16%;
  --fg-primary: 195 24% 92%;
  --fg-secondary: 197 14% 68%;
  --fg-muted: 199 11% 49%;
  --accent: 187 78% 52%;
  --bull: 354 78% 61%;
  --bear: 154 61% 48%;
  --warning: 38 89% 61%;
  --danger: 326 79% 63%;
  --grid-line: 195 28% 28%;
  --water-line: 187 78% 52%;
}

body {
  background-color: hsl(var(--base));
  background-image:
    linear-gradient(hsl(var(--grid-line) / 0.035) 1px, transparent 1px),
    linear-gradient(90deg, hsl(var(--grid-line) / 0.035) 1px, transparent 1px);
  background-size: 24px 24px;
  color: hsl(var(--fg-primary));
}
```

- [ ] **Step 3: Add stable terminal surfaces and moderate motion**

Add these reusable classes and replace the old glass/glow implementation rather than keeping parallel visual systems:

```css
.terminal-panel {
  background: hsl(var(--surface) / 0.96);
  border: 1px solid hsl(var(--border));
  border-radius: 4px;
}

.terminal-panel-header {
  min-height: 2rem;
  border-bottom: 1px solid hsl(var(--border-subtle));
  background: hsl(var(--elevated) / 0.45);
}

.terminal-waterline {
  background: linear-gradient(90deg, transparent, hsl(var(--water-line)), transparent);
  background-size: 200% 100%;
  animation: terminal-flow 2.8s ease-in-out infinite;
}

@keyframes terminal-flow {
  from { background-position: 200% 0; }
  to { background-position: -200% 0; }
}

@keyframes ticker-flash-up {
  from { background-color: hsl(var(--bull) / 0.28); }
  to { background-color: transparent; }
}

@keyframes ticker-flash-down {
  from { background-color: hsl(var(--bear) / 0.28); }
  to { background-color: transparent; }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    scroll-behavior: auto !important;
    transition-duration: 0.01ms !important;
  }
}
```

- [ ] **Step 4: Tighten radii and update chart colors**

In `frontend/tailwind.config.ts`, set `card: '4px'`, `btn: '4px'`, `input: '3px'`, and `dialog: '6px'`. In `frontend/src/lib/theme.ts`, replace purple crosshair, tooltip, zoom and info-bar colors with cyan/neutral values:

```ts
const DARK: ChartTheme = {
  text: '#8296a1', textStrong: '#e6f1f3', grid: 'rgba(104, 155, 166, 0.09)',
  border: 'rgba(112, 162, 172, 0.18)', crosshair: 'rgba(34, 211, 238, 0.48)',
  crosshairLabelBg: '#123640', tooltipBg: 'rgba(12, 20, 26, 0.96)',
  tooltipBorder: 'rgba(34, 211, 238, 0.28)', tooltipText: '#e6f1f3',
  infoBarBg: 'rgba(12, 20, 26, 0.82)', zoomFill: 'rgba(34, 211, 238, 0.10)',
  fillSubtle: 'rgba(255, 255, 255, 0.025)',
}
```

Apply the same semantic relationship to `LIGHT`, then change `frontend/index.html` theme color to `#0e7490`.

Use this exact light chart palette:

```ts
const LIGHT: ChartTheme = {
  text: '#61727b', textStrong: '#17252b', grid: 'rgba(49, 94, 105, 0.10)',
  border: 'rgba(49, 94, 105, 0.20)', crosshair: 'rgba(8, 145, 178, 0.48)',
  crosshairLabelBg: '#0e7490', tooltipBg: 'rgba(255, 255, 255, 0.98)',
  tooltipBorder: 'rgba(8, 145, 178, 0.24)', tooltipText: '#17252b',
  infoBarBg: 'rgba(239, 246, 247, 0.90)', zoomFill: 'rgba(8, 145, 178, 0.09)',
  fillSubtle: 'rgba(49, 94, 105, 0.045)',
}
```

- [ ] **Step 5: Verify and commit the foundation**

Run:

```bash
cd frontend
pnpm build
pnpm lint
cd ..
git diff --check
```

Expected: build passes; lint introduces no new errors; whitespace check is empty.

Commit only the four foundation files:

```bash
git add frontend/src/index.css frontend/tailwind.config.ts frontend/src/lib/theme.ts frontend/index.html
git commit -m "Align the product shell with terminal data semantics"
```

### Task 2: Build shared terminal primitives and data states

**Files:**
- Create: `frontend/src/components/terminal/TerminalPrimitives.tsx`
- Create: `frontend/src/components/terminal/DataState.tsx`
- Modify: `frontend/src/components/PageHeader.tsx`
- Modify: `frontend/src/components/EmptyState.tsx`
- Modify: `frontend/src/components/data/Skeleton.tsx`

- [ ] **Step 1: Create the stateless terminal primitives**

Implement the following public contracts in `TerminalPrimitives.tsx`:

```tsx
import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

export function TerminalPanel({ title, icon: Icon, meta, actions, children, className }: {
  title?: string; icon?: LucideIcon; meta?: ReactNode; actions?: ReactNode
  children: ReactNode; className?: string
}) {
  return <section className={cn('terminal-panel min-w-0 overflow-hidden', className)}>
    {(title || Icon || meta || actions) && <header className="terminal-panel-header flex items-center gap-2 px-3 py-1.5">
      {Icon && <Icon className="h-3.5 w-3.5 text-accent" />}
      {title && <h2 className="text-xs font-semibold text-foreground">{title}</h2>}
      {meta && <div className="font-mono text-[10px] text-muted">{meta}</div>}
      {actions && <div className="ml-auto flex items-center gap-1.5">{actions}</div>}
    </header>}
    {children}
  </section>
}

export function MetricCell({ label, value, detail, tone = 'default', className }: {
  label: ReactNode; value: ReactNode; detail?: ReactNode
  tone?: 'default' | 'accent' | 'bull' | 'bear' | 'warning' | 'danger'; className?: string
}) {
  const tones = { default: 'text-foreground', accent: 'text-accent', bull: 'text-bull', bear: 'text-bear', warning: 'text-warning', danger: 'text-danger' }
  return <div className={cn('min-w-0 border-r border-border-subtle px-3 py-2 last:border-r-0', className)}>
    <div className="truncate text-[10px] text-muted">{label}</div>
    <div className={cn('mt-0.5 truncate font-mono text-base font-semibold tabular-nums', tones[tone])}>{value}</div>
    {detail && <div className="mt-0.5 truncate text-[10px] text-secondary">{detail}</div>}
  </div>
}

export function StatusBadge({ children, tone = 'neutral' }: {
  children: ReactNode; tone?: 'neutral' | 'live' | 'warning' | 'danger' | 'bull' | 'bear'
}) {
  const tones = { neutral: 'border-border text-secondary', live: 'border-accent/35 bg-accent/8 text-accent', warning: 'border-warning/35 bg-warning/8 text-warning', danger: 'border-danger/35 bg-danger/8 text-danger', bull: 'border-bull/35 bg-bull/8 text-bull', bear: 'border-bear/35 bg-bear/8 text-bear' }
  return <span className={cn('inline-flex items-center gap-1 rounded-sm border px-1.5 py-0.5 text-[10px] font-medium', tones[tone])}>{children}</span>
}
```

Add this exact Tailwind color mapping because `MetricCell` uses it:

```ts
'border-subtle': 'hsl(var(--border-subtle) / <alpha-value>)',
```

- [ ] **Step 2: Create explicit loading, empty, error, delayed and simulated states**

Implement `DataState` with `role="status"` for loading/delay and `role="alert"` for errors:

```tsx
import type { ReactNode } from 'react'
import { CircleAlert, Clock3, Database, FlaskConical, Loader2 } from 'lucide-react'
import { cn } from '@/lib/cn'

export type DataStateKind = 'loading' | 'empty' | 'error' | 'delayed' | 'simulated'

const stateMeta = {
  loading: { icon: Loader2, color: 'text-accent', spin: true },
  empty: { icon: Database, color: 'text-muted', spin: false },
  error: { icon: CircleAlert, color: 'text-danger', spin: false },
  delayed: { icon: Clock3, color: 'text-warning', spin: false },
  simulated: { icon: FlaskConical, color: 'text-warning', spin: false },
} satisfies Record<DataStateKind, { icon: typeof Database; color: string; spin: boolean }>

export function DataState({ kind, title, detail, action }: {
  kind: DataStateKind; title: string; detail?: string; action?: ReactNode
}) {
  const meta = stateMeta[kind]
  const Icon = meta.icon
  return <div role={kind === 'error' ? 'alert' : 'status'} className="grid min-h-32 place-items-center px-6 py-8 text-center">
    <div className="max-w-md">
      <Icon className={cn('mx-auto h-6 w-6', meta.color, meta.spin && 'animate-spin')} />
      <div className="mt-2 text-sm font-medium text-foreground">{title}</div>
      {detail && <p className="mt-1 text-xs leading-relaxed text-secondary">{detail}</p>}
      {action && <div className="mt-3 flex justify-center">{action}</div>}
    </div>
  </div>
}
```

- [ ] **Step 3: Make existing shared components delegate to the new language**

Update `PageHeader` so the title area can wrap without pushing actions off-screen:

```tsx
<header className={cn('flex min-h-11 flex-wrap items-center justify-between gap-2 border-b border-border bg-surface/92 px-4 py-2', className)}>
  <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1">
    <h1 className="text-sm font-semibold text-foreground">{title}</h1>
    {titleExtra}
    {subtitle && <span className="truncate text-[11px] text-muted">{subtitle}</span>}
  </div>
  {right && <div className="flex max-w-full flex-wrap items-center gap-2">{right}</div>}
</header>
```

Have `EmptyState` render `DataState kind="empty"`; replace the skeleton pulse with a cyan-neutral sheen that is disabled by reduced motion.

- [ ] **Step 4: Verify and commit shared primitives**

Run `cd frontend && pnpm build && pnpm lint`, then `git diff --check` from the repository root. Expected: all commands pass without new diagnostics.

```bash
git add frontend/src/components/terminal frontend/src/components/PageHeader.tsx frontend/src/components/EmptyState.tsx frontend/src/components/data/Skeleton.tsx frontend/tailwind.config.ts
git commit -m "Give financial data one shared visual grammar"
```

### Task 3: Convert Layout into a responsive terminal shell

**Files:**
- Create: `frontend/src/components/terminal/MarketStatusBar.tsx`
- Modify: `frontend/src/components/Layout.tsx`

- [ ] **Step 1: Implement a pure MarketStatusBar**

Use the existing `QuoteStreamStatus` type and keep all queries in `Layout`:

```tsx
import { RadioTower } from 'lucide-react'
import type { QuoteStreamStatus } from '@/lib/useQuoteStream'
import { StatusBadge } from './TerminalPrimitives'

export interface MarketStatusBarProps {
  marketLabel: string
  sourceLabel: string
  streamStatus: QuoteStreamStatus
  trading: boolean
  phase?: string
  quoteAgeMs?: number | null
  lastFetchMs?: number | null
}

function ageLabel(ms?: number | null) {
  if (ms == null) return '未同步'
  if (ms < 5_000) return '刚刚'
  if (ms < 60_000) return `${Math.floor(ms / 1_000)}s`
  return `${Math.floor(ms / 60_000)}m`
}

function clockLabel(epochMs?: number | null) {
  if (!epochMs) return '未同步'
  return new Date(epochMs).toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function MarketStatusBar(props: MarketStatusBarProps) {
  const connection = props.streamStatus === 'connected'
    ? { label: '实时连接', tone: 'live' as const }
    : props.streamStatus === 'reconnecting'
      ? { label: '正在重连', tone: 'warning' as const }
      : { label: '连接断开', tone: 'danger' as const }

  return <div className="flex min-h-8 flex-wrap items-center gap-x-4 gap-y-1 border-b border-border bg-surface/90 px-3 py-1 text-[10px] text-secondary">
    <span className="font-semibold text-foreground">{props.marketLabel}</span>
    <span>数据源 <b className="font-medium text-foreground">{props.sourceLabel}</b></span>
    <span>{props.trading ? '交易中' : '非交易时段'}{props.phase ? ` · ${props.phase}` : ''}</span>
    <span className="ml-auto font-mono">行情 {ageLabel(props.quoteAgeMs)} · 更新 {clockLabel(props.lastFetchMs)}</span>
    <StatusBadge tone={connection.tone}><RadioTower className="h-3 w-3" />{connection.label}</StatusBadge>
  </div>
}
```

- [ ] **Step 2: Replace decorative branding and purple navigation states**

In `Layout.tsx`:

- Change `BRAND` to the accent cyan value.
- Remove gradient cards, blurred circles, purple text shadows and always-running pulses.
- Use a compact wordmark, one live status dot and thin borders.
- Replace active navigation with `border-l-2 border-accent bg-accent/8 text-foreground`.
- Keep badges semantic: hot/limit events use bull red, `9:25` uses warning, beta uses neutral accent.
- Preserve every existing query, mutation, navigation group, capability badge and settings link.

- [ ] **Step 3: Add the market status bar without adding requests**

Insert below the shell header and pass existing values:

```tsx
<MarketStatusBar
  marketLabel={marketLabel(market)}
  sourceLabel={activeProviderName}
  streamStatus={streamStatus}
  trading={isTrading}
  phase={quoteStatus?.market_phase}
  quoteAgeMs={quoteStatus?.quote_age_ms}
  lastFetchMs={quoteStatus?.last_fetch_ms}
/>
```

Do not introduce another `useQuoteStatus`, data-source query or timer.

- [ ] **Step 4: Add narrow-screen navigation**

Keep the desktop sidebar for `lg` screens. On smaller screens, render a fixed-height top bar with a `Menu` icon button and show the same sidebar content in an overlay drawer. Use one `mobileNavOpen` state; close it on route changes and Escape. The main grid must become:

```tsx
<div className="grid h-screen grid-cols-1 overflow-hidden bg-base text-foreground lg:grid-cols-[14rem_minmax(0,1fr)]">
```

The drawer must have `aria-label="主导航"`, a visible close button, and no body-horizontal overflow.

- [ ] **Step 5: Verify shell behavior and commit**

Run build and lint. Start the existing dev stack, then inspect `/`, `/trade-plan`, and `/darkpool` at `1440x900` and `390x844`. Confirm navigation, status text, theme toggle and content scrolling remain usable.

```bash
git add frontend/src/components/terminal/MarketStatusBar.tsx frontend/src/components/Layout.tsx
git commit -m "Keep market state visible across the terminal"
```

### Task 4: Standardize financial tables and chart containers

**Files:**
- Modify: `frontend/src/components/stock-table/StockDataTable.tsx`
- Modify: `frontend/src/components/stock-table/primitives.tsx`
- Modify: `frontend/src/components/CandlestickChart.tsx`
- Modify: `frontend/src/components/EChartsCandlestick.tsx`
- Modify: `frontend/src/components/EChartsIntraday.tsx`
- Modify: `frontend/src/components/StockDailyKChart.tsx`
- Modify: `frontend/src/components/StockIntradayChart.tsx`

- [ ] **Step 1: Stabilize shared table geometry**

Use a single outer wrapper:

```tsx
<div className="terminal-panel min-w-0 overflow-x-auto overscroll-x-contain">
  <table className="w-full min-w-max border-separate border-spacing-0 text-xs tabular-nums">
```

Use sticky `top-0 z-10 bg-surface/98`, `h-8` header rows, `h-9` body rows, `hover:bg-accent/[0.045]`, and `focus-within:bg-accent/[0.06]`. Do not change sorting, virtualization, columns or row actions.

- [ ] **Step 2: Remove non-semantic hardcoded table colors**

Keep `priceColorClass` as the source of A-share red/green. Map board tags to accent, warning and neutral variants; do not use purple for Beijing-board identity. Preserve RSI threshold behavior while changing UI-only accent highlights from raw Tailwind colors to semantic tokens.

- [ ] **Step 3: Apply the chart theme consistently**

Every canvas chart must obtain colors from `useChartTheme()` and rerender on theme changes. Remove local purple crosshair, tooltip and grid values. Keep bullish candles red and bearish candles green.

- [ ] **Step 4: Verify hot-path performance and commit**

Run `pnpm build` and inspect a virtualized screener/watchlist table while scrolling. Expected: row height does not change on hover; no new request occurs; charts switch theme without reload.

```bash
git add frontend/src/components/stock-table frontend/src/components/CandlestickChart.tsx frontend/src/components/EChartsCandlestick.tsx frontend/src/components/EChartsIntraday.tsx frontend/src/components/StockDailyKChart.tsx frontend/src/components/StockIntradayChart.tsx
git commit -m "Stabilize dense tables and charts for continuous scanning"
```

### Task 5: Redesign Dashboard around scan-first information hierarchy

**Files:**
- Modify: `frontend/src/pages/Dashboard.tsx`

- [ ] **Step 1: Preserve existing behavior before visual edits**

Review the saved pre-existing patch and the current `Dashboard.tsx`. List the existing queries, mutations, modal states and click handlers; after edits, the same identifiers must remain. Do not replace the file wholesale.

- [ ] **Step 2: Replace the page header and KPI row**

Use `PageHeader`, `StatusBadge` and six `MetricCell` units for breadth, strong/weak stocks, limit moves, max boards, amount and turnover/volume ratio. Use this stable responsive grid:

```tsx
<div className="terminal-panel grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6">
  {/* existing metric values rendered through MetricCell */}
</div>
```

Keep date selection, refresh, market emotion and quote snapshot/live status in the header.

- [ ] **Step 3: Convert the body to terminal panels**

Preserve the existing `xl:grid-cols-[minmax(0,1fr)_20rem]` hierarchy. Replace per-card gradients, backdrop blur and hover elevation with `TerminalPanel`. Keep distribution, emotion radar, trend, activity, sector, news/monitor and risk content unchanged.

- [ ] **Step 4: Make loading/error/stale states explicit**

Use `DataState kind="loading"` while the overview is pending, `kind="error"` with the existing refetch action on failure, and `StatusBadge tone="warning"` for watchlist-only or stale snapshots.

- [ ] **Step 5: Verify and stage only visual hunks**

Run build and lint. Compare `git diff -- Dashboard.tsx` with `/tmp/tickflow-preexisting-ui-pages.patch`; confirm no business hunk disappeared. Stage only the new visual hunks and inspect `git diff --cached` before committing:

```bash
git add -p frontend/src/pages/Dashboard.tsx
git diff --cached -- frontend/src/pages/Dashboard.tsx
git commit -m "Prioritize scan signals on the market dashboard"
```

### Task 6: Redesign TradePlan around entry, risk and execution

**Files:**
- Modify: `frontend/src/pages/TradePlan.tsx`
- Modify: `frontend/src/components/Modal.tsx`

- [ ] **Step 1: Establish a fixed hierarchy without changing calculations**

Keep all existing query/mutation calls, plan construction, position sizing, stop-loss, take-profit and modal handlers. Replace the current gradient title banner with this explicit header composition:

```tsx
<PageHeader
  title="短线趋势资金共振交易系统"
  subtitle="系统生成计划 · 人工逐笔确认 · 14:30 尾盘选股"
  titleExtra={<StatusBadge tone={marketStatus.status.includes('交易') ? 'live' : 'neutral'}>{marketStatus.status}</StatusBadge>}
  right={<div className="flex items-center gap-2">
    <span className="font-mono text-xs text-secondary">{timeStr || '09:30:00'}</span>
    <button onClick={() => { refetchDaily(); refetchCopilot(); refetchTailMarket() }} className="inline-flex h-7 items-center gap-1 rounded-btn border border-border bg-surface px-2.5 text-xs text-secondary hover:border-accent/40 hover:text-accent">
      <RefreshCw className="h-3.5 w-3.5" />刷新
    </button>
    <button onClick={() => setSettingsOpen(true)} className="inline-flex h-7 items-center gap-1 rounded-btn border border-accent/30 bg-accent/8 px-2.5 text-xs text-accent hover:bg-accent/12">
      <Sliders className="h-3.5 w-3.5" />风控参数
    </button>
  </div>}
/>
```

Place the existing market gate, position limit and single-trade risk values in a `terminal-panel grid grid-cols-1 md:grid-cols-3`. Place the existing plan list and existing risk/position rail in `grid gap-3 xl:grid-cols-[minmax(0,1fr)_22rem]`; move JSX only, without changing expressions or handlers.

- [ ] **Step 2: Replace violet/indigo visual roles with semantics**

- Entry and selected states: accent cyan.
- Profit and A-share rise: bull red.
- Loss and A-share fall: bear green.
- Risk breach: danger magenta.
- Pending confirmation: warning amber.
- Neutral AI/source labels: border and secondary text.

Remove large gradients, oversized rounded cards and continuous pulse effects.

- [ ] **Step 3: Make execution controls precise**

Use compact inputs with `rounded-input`, visible labels and `focus:border-accent`. Keep destructive/close actions text-labeled. Ensure buy, close and custom-plan modals fit `390x844` with an internal scroll region and sticky action footer.

- [ ] **Step 4: Verify all modal and mutation paths**

Manually exercise open/close for custom plan, buy confirmation and close-position dialogs without submitting live actions. Confirm Escape/backdrop behavior, disabled states, calculated shares and expected loss remain unchanged. Run build and lint.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/TradePlan.tsx frontend/src/components/Modal.tsx
git commit -m "Make risk and confirmation dominant in trade plans"
```

### Task 7: Unify Screener and Backtest research workspaces

**Files:**
- Modify: `frontend/src/pages/Screener.tsx`
- Modify: `frontend/src/components/screener/ScreenerFilter.tsx`
- Modify: `frontend/src/components/screener/ScreenerTable.tsx`
- Modify: `frontend/src/pages/Backtest.tsx`
- Modify: `frontend/src/pages/backtest/FactorBacktest.tsx`
- Modify: `frontend/src/pages/backtest/StrategyBacktest.tsx`
- Modify: `frontend/src/pages/backtest/StrategyOptimizer.tsx`
- Modify: `frontend/src/pages/backtest/StrategyWalkForward.tsx`
- Modify: `frontend/src/pages/backtest/charts/FactorGroupNavChart.tsx`
- Modify: `frontend/src/pages/backtest/charts/FactorICChart.tsx`
- Modify: `frontend/src/pages/backtest/charts/ReturnDistributionChart.tsx`
- Modify: `frontend/src/pages/backtest/charts/StrategyNavChart.tsx`

- [ ] **Step 1: Make Screener scan-first**

Keep `ScreenerFilter` controls and result logic. Use a compact header, a collapsible filter panel, a result status strip showing result count/date/sort/data state, and the shared dense table. On narrow screens, filters stack above results and the table scrolls horizontally.

- [ ] **Step 2: Make Backtest risk-first**

Keep the four existing modes. Change the segmented control active state to accent cyan and present result metrics in this order: total return, maximum drawdown, win rate, profit factor, sample/trade count, then Sharpe/Sortino. Every result summary must display sample size beside performance.

- [ ] **Step 3: Apply chart and status semantics**

Use `TerminalPanel` around charts, `DataState` for worker/reconnect/error states and `StatusBadge tone="warning"` for beta modes. Preserve all worker lifecycle, parameter inputs, signals, date rules, T+1 behavior and result calculations.

- [ ] **Step 4: Verify research workflows and commit**

Run build/lint. Open each Backtest tab and confirm tab switching does not resize the header. Run one existing short backtest if local data is available; otherwise verify empty and unavailable states explicitly.

```bash
git add frontend/src/pages/Screener.tsx frontend/src/components/screener/ScreenerFilter.tsx frontend/src/components/screener/ScreenerTable.tsx frontend/src/pages/Backtest.tsx frontend/src/pages/backtest
git commit -m "Align screening and backtesting around comparable evidence"
```

### Task 8: Convert Monitor, Dark Pool and Regime to evidence-first panels

**Files:**
- Modify: `frontend/src/pages/Monitor.tsx`
- Modify: `frontend/src/pages/DarkPoolRanking.tsx`
- Modify: `frontend/src/pages/Regime.tsx`

- [ ] **Step 1: Update Monitor without changing alert lifecycle**

Keep unread badge, `markSeen`, `leaveMonitorPage`, filters, rule editor and clear confirmation. Replace two floating rounded panels with a stable `xl:grid-cols-[minmax(0,1fr)_24rem]` layout using `TerminalPanel`; show alert count, last update and connection state in the header.

- [ ] **Step 2: Correct Dark Pool visual certainty**

Replace the promotional hero with `PageHeader`. Change wording and hierarchy so derived values are visibly labeled `推导指标`, `估算`, `置信度` and `更新时间` when those fields are available. Replace the purple-pink-red inflow bar with an accent-to-bull scale; do not change `dark_inflow_wan`, `dai_score`, institutional-position or sorting calculations.

- [ ] **Step 3: Clarify Regime evidence and limits**

Use one metric strip for latest state, momentum, confidence/evidence count and range. Keep history/calendar and recompute behavior. Present strategy guidance and risk limits in separate panels so recommendations cannot be mistaken for observed market facts.

- [ ] **Step 4: Verify and commit**

Run build/lint. Check Monitor with no alerts and populated alerts, Dark Pool loading/error/results, and Regime with no history/latest data. Confirm all three work at desktop and narrow widths.

```bash
git add frontend/src/pages/Monitor.tsx frontend/src/pages/DarkPoolRanking.tsx frontend/src/pages/Regime.tsx
git commit -m "Separate observed evidence from trading interpretation"
```

### Task 9: Complete the route-wide visual compatibility sweep

**Files:**
- Modify: route-wide compatibility files listed in File Structure

- [ ] **Step 1: Find remaining legacy visual vocabulary**

Run:

```bash
rg -n "purple-|violet-|indigo-|glass-card|glass-panel|rounded-(xl|2xl|3xl)|bg-gradient" frontend/src --glob '*.tsx'
```

Classify every match as brand/status, data visualization or decoration. Keep a gradient only when it encodes ordered data magnitude; replace decorative gradients and purple/violet/indigo UI states.

- [ ] **Step 2: Apply one explicit replacement map**

Use these transformations across the listed routes and shared dialogs:

```text
selected/active purple or violet  -> accent
AI/source identity purple         -> accent-neutral border + secondary text
warning yellow/amber              -> warning
destructive/risk                  -> danger
market rise/profit                -> bull
market fall/loss                  -> bear
rounded-xl/2xl content panels     -> rounded-card or terminal-panel
decorative backdrop blur          -> opaque surface/elevated hierarchy
```

Do not replace chart series colors that communicate distinct datasets unless they conflict with bull/bear semantics.

Apply the hierarchy route by route:

- `AuctionSnatch.tsx`：9:25 交易窗口、抢筹分数、量价证据和风险提示置于第一层。
- `TomorrowCatalyst.tsx`：催化剂、证据来源、时效和不确定性分开显示。
- `LimitUpLadder.tsx`：连板高度、封板/炸板、最近涨停价守价状态使用固定列语义。
- `Watchlist.tsx`：复用共享密集表格，不再建立独立卡片语言。
- `Review.tsx`：事实记录、策略解释和后续计划分区，避免解释覆盖原始行情。
- `ConceptAnalysis.tsx`、`IndustryAnalysis.tsx`：热力、资金方向和样本覆盖数使用同一证据层级。
- `StockAnalysis.tsx`、`Financials.tsx`：价格、财务事实、AI 解释分别置于独立终端面板。
- `Data.tsx`、`settings/*.tsx`：配置、连接、权限和数据状态使用同一状态标签与紧凑表单。
- `components/screener/*.tsx`、`components/financials/*.tsx`、`components/stock-analysis/*.tsx`：弹窗、分段控件和按钮遵循全局语义色与小圆角。

- [ ] **Step 3: Preserve dirty AuctionSnatch behavior**

Apply the same hunk-preservation procedure used for Dashboard. Keep the pre-existing auction logic and only stage visual hunks for this task.

- [ ] **Step 4: Re-run the legacy vocabulary audit**

Run the `rg` command from Step 1 again. Expected: no decorative `glass-*`, violet or indigo classes remain in application routes; remaining gradients are limited to magnitude legends or chart fills and are documented in the final diff review.

- [ ] **Step 5: Build and commit the route sweep**

Run `pnpm build`, `pnpm lint` and `git diff --check`. Stage the reviewed visual hunks only and commit:

```bash
git commit -m "Finish the terminal visual language across every route"
```

### Task 10: Perform visual, responsive and regression verification

**Files:**
- No production files unless verification exposes a defect
- Evidence: `screenshots/terminal-dense/` only if the repository convention accepts updated screenshots; otherwise keep evidence outside the commit

- [ ] **Step 1: Run static verification**

```bash
cd frontend
pnpm build
pnpm lint
cd ..
git diff --check
```

Expected: build passes, lint has no new errors and whitespace check is empty.

- [ ] **Step 2: Start the application and verify route coverage**

Use the existing `./dev.sh` workflow and open `http://localhost:3011`. Check at minimum:

```text
/
/trade-plan
/screener
/backtest
/monitor
/darkpool
/regime
/auction
/watchlist
/data
/settings
```

For each route, verify loading, populated, empty and error/delayed states that can be produced safely.

- [ ] **Step 3: Capture the required viewport matrix**

Capture screenshots at `1440x900` and `390x844` for Dashboard, TradePlan, Screener, Backtest, Monitor, Dark Pool and Regime in both themes. Check:

- no horizontal page overflow except intentional data-table scrolling;
- no clipped Chinese labels or button text;
- no overlapping fixed navigation, modal or toast content;
- stable chart/table dimensions during hover and refresh;
- visible keyboard focus;
- explicit disconnected, delayed and simulated labels;
- red-rise/green-fall consistency.

- [ ] **Step 4: Verify reduced motion**

Emulate `prefers-reduced-motion: reduce`. Confirm page transitions, water lines, ticker flashes and pulses stop while connection, risk and signal states remain readable.

- [ ] **Step 5: Review the final diff and remaining risk**

Run:

```bash
git status --short
git diff --stat
git diff -- frontend/src/lib/api.ts backend packaging
```

Expected: the redesign has not added API/backend/packaging changes. Existing user-owned modifications in those areas remain present and untouched. Document any route that could not show real data locally.

- [ ] **Step 6: Commit verification fixes only if needed**

Stage fixes interactively so only files changed for verified UI defects are included, then review the staged diff:

```bash
git add -p frontend/src
git diff --cached --check
git diff --cached --stat
git commit -m "Close responsive and theme gaps found in visual QA"
```

Skip this commit when verification required no fixes.
