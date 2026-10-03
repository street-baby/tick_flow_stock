import { useEffect, useRef, useState, Suspense } from 'react'
import { NavLink, Outlet, useNavigate, useLocation } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { motion, AnimatePresence } from 'framer-motion'
import { useQuoteStream, useQuoteStreamStatus } from '@/lib/useQuoteStream'
import { ToastContainer } from '@/components/Toast'
import { AlertToastContainer } from '@/components/AlertToast'
import { AiAnalysisHost } from '@/components/financials/AiAnalysisHost'
import { AiReportBubble } from '@/components/financials/AiReportBubble'
import { StockAnalysisHost } from '@/components/stock-analysis/StockAnalysisHost'
import { StockAnalysisBubble } from '@/components/stock-analysis/StockAnalysisBubble'
import {
  useCapabilities,
  useSettings,
  usePreferences,
  useQuoteStatus,
  useVersion,
} from '@/lib/useSharedQueries'
import {
  useToggleRealtimeQuotes,
} from '@/lib/useSharedMutations'
import { QK } from '@/lib/queryKeys'
import { tierRank } from '@/lib/capability-labels'
import {
  Star,
  Newspaper,
  ScanSearch,
  History,
  FileText,
  Settings,
  Key,
  Database,
  Loader2,
  LayoutDashboard,
  Tags,
  TrendingUp,
  Flame,
  Zap,
  Target,
  BarChart3,
  Gauge,
  Sparkles,
  Layers3,
  Landmark,
  RadioTower,
  CheckCircle2,
  BookOpenCheck,
  ExternalLink,
  Sun,
  Moon,
  X,
  WifiOff,
  EyeOff,
  ChevronDown,
  Trophy,
  Compass,
} from 'lucide-react'
import { Logo } from './Logo'
import { api, type IndexQuote } from '@/lib/api'
import { cn } from '@/lib/cn'
import { toggleTheme, useTheme } from '@/lib/theme'
import { setCurrentTotal as setAlertTotal, useUnreadAlerts } from '@/lib/monitorBadge'
import { useMarket } from '@/lib/market'

const TICKFLOW_REGISTER_URL = 'https://tickflow.org/auth/register?ref=V3KDKGXPEA'

const CORE_INDEXES = [
  { symbol: '000001.SH', name: '上证指数' },
  { symbol: '399001.SZ', name: '深证成指' },
  { symbol: '399006.SZ', name: '创业板指' },
  { symbol: '000680.SH', name: '科创综指' },
] as const

const CRYPTO_INDEXES = [
  { symbol: 'BTCUSDT', name: 'BTC/USDT' },
  { symbol: 'ETHUSDT', name: 'ETH/USDT' },
  { symbol: 'SOLUSDT', name: 'SOL/USDT' },
  { symbol: 'BNBUSDT', name: 'BNB/USDT' },
] as const

type CoreIndex = { symbol: string; name: string }

interface NavItemDef {
  to: string
  label: string
  icon: any
  badge?: string
}

interface NavCategoryDef {
  category: string
  items: NavItemDef[]
}

const NAV_GROUPS: NavCategoryDef[] = [
  {
    category: '行情',
    items: [
      { to: '/', label: '看板', icon: LayoutDashboard },
      { to: '/watchlist', label: '自选', icon: Star },
      { to: '/speed-rank', label: '五分钟涨速', icon: Flame, badge: '5m' },
      { to: '/indices', label: '指数', icon: BarChart3 },
      { to: '/stock-analysis', label: '个股分析', icon: TrendingUp },
    ],
  },
  {
    category: '策略研究',
    items: [
      { to: '/screener', label: '策略', icon: ScanSearch },
      { to: '/backtest', label: '回测', icon: History },
      { to: '/monitor', label: '监控中心', icon: RadioTower },
    ],
  },
  {
    category: '市场分析',
    items: [
      { to: '/news-brief', label: '资讯', icon: Newspaper, badge: 'AI' },
      { to: '/limit-ladder', label: '连板梯队', icon: Flame },
      { to: '/longhubang', label: '龙虎榜', icon: Trophy, badge: '资金' },
      { to: '/concept-analysis', label: '概念分析', icon: Layers3 },
      { to: '/industry-analysis', label: '行业分析', icon: Landmark },
      { to: '/financials', label: '财务分析', icon: FileText },
      { to: '/regime', label: '市场环境', icon: Gauge, badge: 'beta' },
      { to: '/review', label: '复盘', icon: BookOpenCheck },
    ],
  },
  {
    category: '实战工具',
    items: [
      { to: '/trade-plan', label: '开盘交易面板', icon: Target, badge: '实战' },
      { to: '/tomorrow-catalysts', label: '明天炒什么', icon: Zap, badge: '热' },
      { to: '/game-theory', label: '博弈分析', icon: Compass, badge: '对手盘' },
      { to: '/auction', label: '竞价抢筹', icon: Zap, badge: '9:25' },
      { to: '/darkpool', label: '暗盘资金', icon: EyeOff, badge: '主力' },
      { to: '/data', label: '数据', icon: Database },
    ],
  },
]

const nav = NAV_GROUPS.flatMap(g => g.items)

/** 亮/暗主题切换 — 状态存 localStorage, 生效见 lib/theme.ts */
function ThemeToggle() {
  const theme = useTheme()
  const dark = theme === 'dark'
  return (
    <button
      onClick={() => toggleTheme()}
      className="flex items-center justify-center rounded-btn p-2 text-foreground/80 transition-colors duration-150 ease-smooth hover:bg-elevated hover:text-foreground cursor-pointer"
      title={dark ? '切换到亮色模式' : '切换到暗色模式'}
    >
      {dark ? <Sun className="h-4 w-4 shrink-0" /> : <Moon className="h-4 w-4 shrink-0" />}
    </button>
  )
}

function fmtIndexValue(v: number | null | undefined) {
  if (v == null || Number.isNaN(Number(v))) return '--'
  return Number(v).toFixed(2)
}

function fmtIndexPct(v: number | null | undefined) {
  if (v == null || Number.isNaN(Number(v))) return '--'
  return `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(2)}%`
}

function indexPctClass(v: number | null | undefined) {
  if (v == null || Number.isNaN(Number(v))) return 'text-muted'
  const n = Number(v)
  if (n === 0) return 'text-foreground'
  return n > 0 ? 'text-bull' : 'text-bear'
}

/** 全局市场切换器（多市场扩展）：A股 / 港股 / 美股 / 加密货币 */
function MarketSwitcher() {
  const { market, setMarket } = useMarket()
  const opts: [('cn' | 'hk' | 'us' | 'crypto'), string][] = [
    ['cn', 'A股'], ['hk', '港股'], ['us', '美股'], ['crypto', '加密'],
  ]
  return (
    <div className="mt-3 flex items-center h-7 rounded-btn border border-border overflow-hidden">
      {opts.map(([m, label]) => (
        <button
          key={m}
          onClick={() => setMarket(m)}
          className={`h-full flex-1 px-1 text-[11px] font-medium transition-colors cursor-pointer
            ${market === m ? 'bg-accent/10 text-accent font-semibold' : 'text-muted hover:text-foreground hover:bg-elevated'}`}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

/** 监控中心未读徽标 — 仅在非监控页且有未读时显示。 */
function MonitorBadge({ active }: { active: boolean }) {  const unread = useUnreadAlerts()
  // 尊重用户设置: 可在菜单设置里关闭数字提示
  const badgeEnabled = (() => {
    try { return localStorage.getItem('monitor_badge_enabled') !== '0' } catch { return true }
  })()
  if (active || unread <= 0 || !badgeEnabled) return null
  return (
    <span className="inline-flex h-4 min-w-4 items-center justify-center rounded-full bg-danger px-1 text-[9px] font-bold text-white animate-pulse">
      {unread > 99 ? '99+' : unread}
    </span>
  )
}

function SidebarIndexQuotes({ rows, items }: { rows: IndexQuote[] | undefined; items: CoreIndex[] }) {
  if (items.length === 0) return null
  const quoteBySymbol = new Map((rows ?? []).map(q => [q.symbol, q]))
  return (
    <div className="mt-2 grid grid-cols-2 gap-1.5">
      {items.map(item => {
        const q = quoteBySymbol.get(item.symbol)
        const value = q?.last_price ?? q?.close
        const pct = q?.change_pct
        return (
          <NavLink
            key={item.symbol}
            to={item.symbol.includes('USDT') ? '/watchlist' : `/indices?symbol=${encodeURIComponent(item.symbol)}`}
            className="block rounded bg-elevated/60 px-2 py-1.5 transition-colors hover:bg-elevated"
            title={`${item.name} ${item.symbol}`}
          >
            <div className="flex items-center justify-between gap-1">
              <span className="text-[10px] text-secondary">{item.name}</span>
              <span className={`text-[10px] font-mono ${indexPctClass(pct)}`}>{fmtIndexPct(pct)}</span>
            </div>
            <div className={`mt-0.5 truncate font-mono text-[10px] ${indexPctClass(pct)}`}>
              {fmtIndexValue(value)}
            </div>
          </NavLink>
        )
      })}
    </div>
  )
}

// ===== 档位卡片 =====
function TierBadge({ label, hasKey }: { label: string; hasKey?: boolean }) {
  const base = label.split(' ')[0].split('+')[0].toLowerCase()
  const isNone = base === 'none'

  const tierConfig: Record<string, {
    desc: string
    tagBg: React.CSSProperties
    dotStyle: React.CSSProperties
    labelTextStyle: React.CSSProperties
  }> = {
    none: {
      desc: '未配置 Key · 仅历史日K',
      tagBg: { background: 'rgba(113,113,122,0.15)' },
      dotStyle: { background: '#52525b' },
      labelTextStyle: { color: '#71717a' },
    },
    free: {
      desc: '基础日K · 自选实时',
      tagBg: { background: 'rgba(113,113,122,0.3)' },
      dotStyle: { background: '#71717a' },
      labelTextStyle: { color: '#a1a1aa' },
    },
    starter: {
      desc: '批量同步 · 行情池',
      tagBg: { background: 'rgba(59,130,246,0.2)' },
      dotStyle: { background: '#3b82f6' },
      labelTextStyle: { color: '#60a5fa' },
    },
    pro: {
      desc: '分钟K · 实时行情 · 盘口',
      tagBg: { background: 'linear-gradient(135deg, rgba(14, 165, 233, 0.2), rgba(124,58,237,0.15))' },
      dotStyle: { background: 'linear-gradient(135deg, #a855f7, #7c3aed)' },
      labelTextStyle: { background: 'linear-gradient(135deg, #c084fc, #a855f7)', WebkitBackgroundClip: 'text', backgroundClip: 'text', color: 'transparent' },
    },
    expert: {
      desc: 'WebSocket · 财务数据',
      tagBg: { background: 'linear-gradient(135deg, rgba(59,130,246,0.2), rgba(14, 165, 233, 0.2), rgba(245,158,11,0.2))' },
      dotStyle: { background: 'linear-gradient(135deg, #3b82f6, #a855f7, #f59e0b)' },
      labelTextStyle: { background: 'linear-gradient(135deg, #60a5fa, #c084fc, #fbbf24)', WebkitBackgroundClip: 'text', backgroundClip: 'text', color: 'transparent' },
    },
  }

  const t = tierConfig[base] || tierConfig.none
  // none 档显示英文「None」,无 label 时也显示「None」
  const displayLabel = isNone ? 'None' : (label || 'None')

  return (
    <NavLink
      to="/settings?tab=account"
      className="mt-2.5 group block -mx-2.5"
      title="API 设置"
    >
      <div className="relative overflow-hidden rounded-lg border border-blue-400/20 bg-gradient-to-br from-blue-500/[0.12] via-surface to-surface px-3 py-2 transition-all hover:border-blue-400/35 hover:from-blue-500/[0.16]">
        <div className="absolute -right-5 -top-6 h-14 w-14 rounded-full bg-blue-500/10 blur-2xl" />
        <div className="relative flex items-center gap-2">
          <div className="flex h-6 w-6 items-center justify-center rounded-md bg-blue-400/10 text-blue-300 ring-1 ring-blue-400/20">
            <Key className="h-3.5 w-3.5" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <span className="text-xs font-medium text-foreground">TickFlow</span>
              <span
                className="h-1.5 w-1.5 rounded-full"
                style={{ ...t.dotStyle, ...(base === 'expert' ? { animation: 'pulse 2s infinite' } : {}) }}
              />
            </div>
            <div className="mt-0.5 truncate text-[10px] leading-tight text-muted">
              {isNone && !hasKey ? '配置 Key 解锁更多能力' : t.desc}
            </div>
          </div>
          <span
            className="inline-flex h-[18px] max-w-[68px] shrink-0 items-center overflow-hidden rounded px-1.5 text-[10px] font-bold font-mono leading-none"
            style={t.tagBg}
          >
            <span className="truncate" style={t.labelTextStyle}>{displayLabel}</span>
          </span>
          <Settings className="h-3 w-3 shrink-0 text-muted group-hover:text-blue-300 transition-colors" />
        </div>

      </div>
    </NavLink>
  )
}

function AIConfigBadge({ configured, model }: { configured?: boolean; model?: string }) {
  return (
    <NavLink
      to="/settings?tab=ai"
      className="mt-2 group block -mx-2.5"
      title="AI 配置"
    >
      <div className="relative overflow-hidden rounded-lg border border-sky-400/20 bg-gradient-to-br from-sky-500/[0.12] via-surface to-surface px-3 py-2 transition-all hover:border-sky-400/35 hover:from-sky-500/[0.16]">
        <div className="absolute -right-5 -top-6 h-14 w-14 rounded-full bg-sky-500/10 blur-2xl" />
        <div className="relative flex items-center gap-2">
          <div className="flex h-6 w-6 items-center justify-center rounded-md bg-sky-400/10 text-sky-300 ring-1 ring-sky-400/20">
            <Sparkles className="h-3.5 w-3.5" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <span className="text-xs font-medium text-foreground">AI 配置</span>
              <span className={`h-1.5 w-1.5 rounded-full ${configured ? 'bg-bear' : 'bg-warning'}`} />
            </div>
            <div className="mt-0.5 truncate text-[10px] leading-tight text-muted">
              {configured ? (model || '已接入模型') : '接入策略生成模型'}
            </div>
          </div>
          <Settings className="h-3 w-3 text-muted group-hover:text-sky-300 transition-colors" />
        </div>
      </div>
    </NavLink>
  )
}

export function Layout() {
  // ===== 共享 hooks (替代内联 useQuery) =====
  const { data: caps } = useCapabilities()
  const { data: settingsState } = useSettings()
  const { data: versionData } = useVersion()
  const { data: prefs } = usePreferences()
  // 数据源列表 (用于实时行情状态显示当前数据源名称)
  const { data: dataSources } = useQuery({
    queryKey: QK.dataSources,
    queryFn: api.dataSources,
    staleTime: 60_000,
  })
  // poll=true: 全局唯一开启条件轮询 (非交易时段 60s 兜底, 交易时段靠 SSE)
  const { data: quoteStatus } = useQuoteStatus({ poll: true })
  const { data: analysisMenus } = useQuery({
    queryKey: QK.analysisMenus,
    queryFn: api.analysisMenus,
  })

  // 数据同步状态轮询: 有活跃 job 时「数据」菜单项显示转圈
  const { data: pipelineJobs } = useQuery({
    queryKey: QK.pipelineJobs,
    queryFn: () => api.pipelineJobs(1),
    refetchInterval: (query) => (query.state.data?.active_id ? 2000 : 15000),
    refetchIntervalInBackground: true,
  })
  const isDataSyncing = !!pipelineJobs?.active_id

  // 数据同步完成的"瞬时反馈": isDataSyncing 从 true→false 时显示绿色对勾,
  // 闪烁约 3 秒后自动消失。
  const [dataSyncJustDone, setDataSyncJustDone] = useState(false)
  const prevSyncingRef = useRef(false)
  useEffect(() => {
    // 仅在"刚结束"(true→false)且非首次挂载时触发
    if (prevSyncingRef.current && !isDataSyncing) {
      setDataSyncJustDone(true)
      const t = setTimeout(() => setDataSyncJustDone(false), 3000)
      prevSyncingRef.current = isDataSyncing
      return () => clearTimeout(t)
    }
    prevSyncingRef.current = isDataSyncing
  }, [isDataSyncing])

  const qc = useQueryClient()
  const navigate = useNavigate()
  const location = useLocation()
  const version = versionData?.version
  const realtimeEnabled = prefs?.realtime_quotes_enabled ?? false

  // 导航折叠状态 (持久化存 localStorage, 默认全展开)
  const [collapsedGroups, setCollapsedGroups] = useState<Record<string, boolean>>(() => {
    try {
      const saved = localStorage.getItem('tf_collapsed_nav_groups')
      return saved ? JSON.parse(saved) : {}
    } catch {
      return {}
    }
  })

  const toggleGroup = (category: string) => {
    setCollapsedGroups(prev => {
      const next = { ...prev, [category]: !prev[category] }
      try {
        localStorage.setItem('tf_collapsed_nav_groups', JSON.stringify(next))
      } catch {}
      return next
    })
  }
  // Free 档监控限制提示: 可手动关闭, 不持久化 (刷新后恢复显示)
  const [dismissFreeHint, setDismissFreeHint] = useState(false)
  const indicesPinned = prefs?.indices_nav_pinned ?? true
  const { market } = useMarket()
  const activeIndexes = market === 'crypto' ? CRYPTO_INDEXES : CORE_INDEXES
  const sidebarIndexSymbols = market === 'crypto'
    ? CRYPTO_INDEXES.map(p => p.symbol)
    : (prefs?.sidebar_index_symbols ?? CORE_INDEXES.map(p => p.symbol))
  const sidebarIndexes = activeIndexes.filter(item => sidebarIndexSymbols.includes(item.symbol))
  // 卡片数据：固定显示时也拉取（即使实时行情关闭）
  const showSidebarQuotes = indicesPinned || realtimeEnabled
  const { data: sidebarIndexQuotes } = useQuery({
    queryKey: [...QK.indexQuotes, 'sidebar', sidebarIndexSymbols.join(',')] as const,
    queryFn: () => api.indexQuotes(sidebarIndexes.map(p => p.symbol)),
    enabled: showSidebarQuotes && sidebarIndexes.length > 0,
    refetchInterval: 3_000,
    placeholderData: (prev) => prev,
  })

  // SSE: 行情更新时自动刷新相关 queries + 告警通知
  useQuoteStream(realtimeEnabled, prefs?.sse_refresh_pages)
  // 实时 SSE 连接状态 — 断开时底部显示提示, 提示可能漏策略告警
  const streamStatus = useQuoteStreamStatus()

  const toggleQuote = useToggleRealtimeQuotes()
  const isRunning = quoteStatus?.running ?? false
  const isTrading = quoteStatus?.is_trading_hours ?? false
  // 管道/数据修正运行期间实时行情被临时暂停 — 此时禁止开启
  const isPaused = quoteStatus?.paused ?? false
  const tier = tierRank(caps?.label ?? '')
  const isNoneTier = tier < 0
  const isWatchlistMode = tier === 0
  const realtimeModeLabel = isWatchlistMode ? '自选股' : '全市场'
  // 当前实时行情数据源名称 (custom 时显示源名, tickflow 时不显示)
  const realtimeProvider = prefs?.realtime_data_provider
  const realtimeProviderName = realtimeProvider && realtimeProvider !== 'tickflow'
    ? (dataSources?.custom?.find(s => s.name === realtimeProvider)?.display_name || realtimeProvider)
    : null

  // 当前主数据源 (用于菜单底部状态条)
  const activeProvider = prefs?.daily_data_provider || 'tickflow'
  const activeProviderName = activeProvider === 'tickflow'
    ? 'TickFlow'
    : (dataSources?.custom?.find(s => s.name === activeProvider)?.display_name || activeProvider)
  const activeProviderDatasets = activeProvider === 'tickflow'
    ? ['daily', 'adj_factor', 'realtime', 'minute']
    : (dataSources?.custom?.find(s => s.name === activeProvider)?.datasets || [])
  const isCustomActive = activeProvider !== 'tickflow'

  // 轮询触发记录总数 → 更新监控中心徽标 (每 15 秒)
  const alertsTotalQuery = useQuery({
    queryKey: ['alerts-total'],
    queryFn: () => api.alertsList({ days: 7, limit: 1 }),
    refetchInterval: 15000,
    refetchIntervalInBackground: true,
    select: (data) => data.total,
  })
  // 只在拿到真实总数时同步徽标 (避免 data=undefined 时传 0 重置 lastSeen)
  const alertsTotal = alertsTotalQuery.data
  useEffect(() => {
    if (alertsTotal != null) setAlertTotal(alertsTotal)
  }, [alertsTotal])

  // 合并内置页面 + 可见的扩展分析菜单
  type NavItem = { to: string; label: string; icon: typeof Gauge; badge?: string }
  const analysisNav: NavItem[] = (analysisMenus?.items ?? [])
    .filter(m => m.visible)
    .map(m => ({ to: `/analysis/${m.id}`, label: m.label, icon: m.icon === 'tags' ? Tags : BarChart3 }))

  const allNav: NavItem[] = [...nav, ...analysisNav]
  const savedOrder = prefs?.nav_order ?? []

  const navItems = savedOrder.length > 0
    ? (() => {
        const byTo = new Map(allNav.map(n => [n.to, n]))
        const ordered = savedOrder
          .map(id => byTo.get(id) ?? byTo.get(`/analysis/${id}`))
          .filter(Boolean) as NavItem[]
        const seen = new Set(ordered.map(n => n.to))
        
        // 如果暗盘未在 savedOrder 中，插入到竞价抢筹后面或顶部
        if (!seen.has('/darkpool') && byTo.has('/darkpool')) {
          const darkItem = byTo.get('/darkpool')!
          const auctionIdx = ordered.findIndex(item => item.to === '/auction')
          if (auctionIdx !== -1) {
            ordered.splice(auctionIdx + 1, 0, darkItem)
          } else {
            ordered.splice(3, 0, darkItem)
          }
          seen.add('/darkpool')
        }

        // 如果五分钟涨速未在 savedOrder 中，插入到自选后面
        if (!seen.has('/speed-rank') && byTo.has('/speed-rank')) {
          const speedItem = byTo.get('/speed-rank')!
          const watchlistIdx = ordered.findIndex(item => item.to === '/watchlist')
          if (watchlistIdx !== -1) {
            ordered.splice(watchlistIdx + 1, 0, speedItem)
          } else {
            ordered.splice(2, 0, speedItem)
          }
          seen.add('/speed-rank')
        }

        const remaining = allNav.filter(n => !seen.has(n.to))
        return [...ordered, ...remaining]
      })()
    : allNav

  const hiddenIds = new Set(prefs?.nav_hidden ?? [])
  const visibleNavItems = navItems.filter(n => !hiddenIds.has(n.to) && !hiddenIds.has(n.to.replace(/^\/analysis\//, '')))

  const handleToggle = async (enabled: boolean) => {
    // 开启时重新校验档位
    if (enabled) {
      const fresh = await qc.fetchQuery({
        queryKey: QK.capabilities,
        queryFn: api.capabilities,
      })
      const freshTier = tierRank(fresh.label ?? '')
      if (freshTier < 0) return
      if (freshTier === 0 && (prefs?.realtime_watchlist_symbols?.length ?? 0) === 0) {
        navigate('/watchlist')
        return
      }
    }
    await toggleQuote.mutateAsync(enabled)
    // 仅在交易时段立即获取一次行情
    if (enabled && isTrading) {
      api.intradayRefresh().catch(() => {})
    }
  }

  return (
    <div className="h-screen grid grid-cols-[14.5rem_1fr] bg-base text-foreground overflow-hidden relative">
      {/* 🌌 顶部全景超能激光光轨 🌌 */}
      <div className="fixed top-0 left-0 right-0 h-[2px] bg-gradient-to-r from-transparent via-cyan-400 via-sky-400 to-transparent z-[9999] opacity-90 shadow-[0_0_16px_rgba(0,229,255,0.9)]" />

      <aside className="border-r border-cyan-500/30 bg-gradient-to-b from-[#081224]/98 via-[#050c1b]/98 to-[#03060f]/99 backdrop-blur-3xl flex flex-col h-full min-h-0 overflow-hidden shadow-[6px_0_30px_rgba(0,0,0,0.85)] relative z-10">
        <div className="px-4 py-3.5 border-b border-cyan-500/25 shrink-0 bg-gradient-to-b from-cyan-500/[0.16] via-sky-950/[0.12] to-transparent relative">
          <div className="absolute top-0 left-0 right-0 h-[1px] bg-gradient-to-r from-transparent via-cyan-400/80 to-transparent" />
          {/* Brand block — 官方云之心量化 logo 标识 */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="relative group">
                <div className="absolute -inset-1 rounded-xl bg-gradient-to-r from-cyan-400/50 to-blue-600/50 blur-md opacity-85 group-hover:opacity-100 transition-opacity animate-pulse" />
                <div className="relative p-0.5 rounded-xl bg-gradient-to-br from-cyan-400/30 via-slate-900 to-slate-950 border border-cyan-400/40 shadow-[0_0_16px_rgba(0,229,255,0.4)]">
                  <Logo
                    size={32}
                    className="shrink-0 drop-shadow-[0_0_18px_rgba(0,229,255,0.9)]"
                  />
                  <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-emerald-400 animate-quant-pulse shadow-[0_0_10px_#10b981]" />
                </div>
              </div>
              <div className="font-bold tracking-[0.04em] text-foreground leading-tight">
                <div className="bg-gradient-to-r from-white via-cyan-100 to-cyan-300 bg-clip-text text-transparent font-sans text-[14px] font-extrabold tracking-wide drop-shadow-[0_0_14px_rgba(0,229,255,0.5)]">
                  云之心量化
                </div>
                <div className="text-[8.5px] text-cyan-300 font-bold tracking-wider font-mono flex items-center gap-1">
                  <span>CLOUD HEART QUANT</span>
                </div>
              </div>
            </div>
            
            {/* 行情引擎状态微灯 */}
            <div className="flex items-center gap-1 rounded-full bg-emerald-500/20 border border-emerald-400/50 px-1.5 py-0.5 text-[9px] font-mono text-emerald-300 shadow-[0_0_12px_rgba(16,185,129,0.45)]">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse shadow-[0_0_8px_#10b981]" />
              LIVE
            </div>
          </div>

          <TierBadge
            label={caps?.label ?? ''}
            hasKey={settingsState?.mode !== 'none'}
          />
          <AIConfigBadge
            configured={settingsState?.ai_configured ?? settingsState?.has_ai_key}
            model={settingsState?.ai_model}
          />

          {/* 全局市场切换（多市场扩展）：A股 / 港股 / 美股 */}
          <MarketSwitcher />
        </div>

        <nav className="flex-1 min-h-0 overflow-y-auto px-2 py-2 space-y-2 scrollbar-thin">
          {NAV_GROUPS.map((group) => {
            const groupVisibleItems = group.items.filter(item => 
              visibleNavItems.some(v => v.to === item.to)
            )
            if (groupVisibleItems.length === 0) return null

            // 检查当前激活路由是否在该组内
            const hasActiveChild = groupVisibleItems.some(item => 
              item.to === '/' ? location.pathname === '/' : location.pathname.startsWith(item.to)
            )

            const isCollapsed = !!collapsedGroups[group.category]

            return (
              <div key={group.category} className="space-y-0.5 select-none">
                {/* 可点击折叠的分类标题栏 */}
                <button
                  type="button"
                  onClick={() => toggleGroup(group.category)}
                  className="w-full px-2 py-1 rounded-lg text-[10px] font-bold text-muted/75 hover:text-foreground tracking-wider uppercase font-mono flex items-center justify-between transition-colors hover:bg-elevated/40 cursor-pointer group"
                >
                  <div className="flex items-center gap-1.5 min-w-0">
                    <span className="truncate">{group.category}</span>
                    {/* 折叠时若内部有当前活跃路由，显示微光提示点 */}
                    {isCollapsed && hasActiveChild && (
                      <span className="h-1.5 w-1.5 rounded-full bg-sky-400 animate-pulse shadow-[0_0_6px_#a855f7]" />
                    )}
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="text-[9px] font-normal text-muted/50 group-hover:text-muted/80 font-sans">
                      {groupVisibleItems.length}
                    </span>
                    <ChevronDown className={cn(
                      'h-3 w-3 text-muted/70 transition-transform duration-200 group-hover:text-foreground',
                      isCollapsed ? '-rotate-90' : 'rotate-0'
                    )} />
                  </div>
                </button>

                {/* 折叠动画容器 */}
                <AnimatePresence initial={false}>
                  {!isCollapsed && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
                      className="space-y-0.5 overflow-hidden"
                    >
                      {groupVisibleItems.map(({ to, label, icon: Icon, badge }) => (
                        <NavLink
                          key={to}
                          to={to}
                          className={({ isActive }) =>
                            cn(
                              'group relative flex items-center gap-2.5 px-3 py-1.5 rounded-xl text-xs font-medium transition-all duration-200',
                              isActive
                                ? 'bg-gradient-to-r from-cyan-500/30 via-sky-600/20 to-transparent text-white font-extrabold border-l-[3px] border-cyan-400 shadow-[0_0_22px_rgba(0,229,255,0.45)] pl-3.5'
                                : 'text-foreground/80 hover:bg-gradient-to-r hover:from-cyan-500/15 hover:to-transparent hover:text-white hover:translate-x-1',
                            )
                          }
                        >
                          {({ isActive }) => (
                            <>
                              <Icon className={cn('h-4 w-4 shrink-0 transition-transform group-hover:scale-110 duration-200', isActive ? 'text-cyan-300 drop-shadow-[0_0_8px_rgba(0,229,255,0.8)]' : 'text-muted group-hover:text-foreground')} />
                              <span className="flex-1 tracking-wide">{label}</span>
                              {badge && (
                                <span className={cn(
                                  'ml-auto inline-flex items-center rounded-full px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider shrink-0 transition-all',
                                  badge === '热' || badge === '主力'
                                    ? 'border border-red-500/40 bg-red-500/15 text-red-300 shadow-[0_0_8px_rgba(239,68,68,0.25)]'
                                    : badge === '9:25'
                                    ? 'border border-amber-400/40 bg-amber-400/15 text-amber-300 shadow-[0_0_8px_rgba(251,191,36,0.25)]'
                                    : 'border border-sky-400/30 bg-sky-400/10 text-sky-300'
                                )}>
                                  {badge}
                                </span>
                              )}
                              {/* 数据同步状态: 同步中转圈, 刚完成显示绿色对勾闪烁 3 秒 */}
                              {to === '/data' && isDataSyncing && (
                                <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-accent" />
                              )}
                              {to === '/data' && !isDataSyncing && dataSyncJustDone && (
                                <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-bull animate-pulse" />
                              )}
                              {/* 监控中心徽标: 仅非监控页且有未读时显示 */}
                              {to === '/monitor' && <MonitorBadge active={isActive} />}
                            </>
                          )}
                        </NavLink>
                      ))}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>
            )
          })}
        </nav>

        {/* 数据源状态条 */}
        <button
          onClick={() => navigate('/settings?tab=data-sources')}
          className="mx-2 mb-1 flex items-center gap-2 rounded-btn px-2.5 py-2 text-left transition-colors hover:bg-elevated/60 shrink-0 group"
          title="数据源设置"
        >
          <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-md ${
            isCustomActive ? 'bg-accent/15' : 'bg-elevated'
          }`}>
            <Database className={`h-3 w-3 ${isCustomActive ? 'text-accent' : 'text-muted'}`} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1.5">
              <span className="text-[11px] font-medium text-secondary truncate group-hover:text-foreground transition-colors">
                {activeProviderName}
              </span>
              {isCustomActive && (
                <span className="shrink-0 rounded bg-accent/15 px-1 py-px text-[8px] font-semibold uppercase tracking-wider text-accent">
                  自定义
                </span>
              )}
            </div>
            <div className="mt-0.5 flex gap-0.5">
              {(['daily', 'adj_factor', 'realtime', 'minute'] as const).map(ds => {
                const supported = ds === 'daily' || ds === 'adj_factor' || ds === 'realtime' || ds === 'minute'
                const active = supported && (
                  isCustomActive ? activeProviderDatasets.includes(ds) : true
                )
                return (
                  <span
                    key={ds}
                    title={ds}
                    className={`h-1 flex-1 rounded-full transition-colors ${
                      active ? 'bg-accent/60' : 'bg-muted/20'
                    }`}
                  />
                )
              })}
            </div>
          </div>
        </button>

        {/* 全局行情开关 */}
        <div className="border-t border-border px-3 py-2.5 shrink-0">
          {isNoneTier && !realtimeProviderName ? (
            <div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-secondary truncate">实时行情</span>
                <span className="text-[10px] text-accent/70 font-medium bg-accent/10 px-1.5 py-0.5 rounded">
                  Free+
                </span>
              </div>
              <div className="mt-1.5 text-[10px] leading-snug text-muted">
                免费注册
                <a
                  href={TICKFLOW_REGISTER_URL}
                  target="_blank"
                  rel="noreferrer"
                  className="mx-1 inline-flex items-baseline gap-0.5 text-accent/80 hover:text-accent hover:underline"
                >
                  TickFlow
                  <ExternalLink className="h-2.5 w-2.5 self-center" />
                </a>
                开启个股监控
              </div>
            </div>
          ) : (
            /* Starter+ — 开关 + 跳转设置 */
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 min-w-0">
                <span className={`inline-block h-1.5 w-1.5 rounded-full shrink-0 ${
                  realtimeEnabled && isRunning && isTrading
                    ? 'bg-accent animate-pulse'
                    : realtimeEnabled
                      ? 'bg-warning/60'
                      : 'bg-muted'
                }`} />
                <span className="text-xs text-secondary truncate">
                  实时行情 · {realtimeProviderName || realtimeModeLabel}
                </span>
                <button
                  onClick={() => navigate('/settings?tab=monitoring')}
                  className="text-secondary hover:text-foreground transition-colors shrink-0"
                  title="实时监控设置"
                >
                  <Settings className="h-3 w-3" />
                </button>
              </div>
              <button
                onClick={() => handleToggle(!realtimeEnabled)}
                disabled={toggleQuote.isPending || isPaused}
                title={isPaused ? '数据同步运行中，实时行情已临时暂停' : undefined}
                className={`relative inline-flex h-4 w-7 items-center rounded-full shrink-0 transition-colors duration-200 ${
                  realtimeEnabled
                    ? 'bg-accent shadow-[0_0_6px_rgba(59,130,246,0.3)]'
                    : 'bg-elevated'
                } ${toggleQuote.isPending || isPaused ? 'opacity-50' : 'cursor-pointer'}`}
              >
                <span className={`inline-block h-3 w-3 rounded-full bg-white shadow-sm transition-transform duration-200 ${
                  realtimeEnabled ? 'translate-x-[14px]' : 'translate-x-0.5'
                }`} />
              </button>
            </div>
          )}

          {/* 状态提示 */}
          {realtimeEnabled && (!isNoneTier || realtimeProviderName) && (
            <div className="mt-1.5 text-[10px] leading-snug space-y-0.5">
              {isWatchlistMode && !dismissFreeHint && !realtimeProviderName && (
                <div className="flex items-start gap-1 text-amber-400/80">
                  <span className="flex-1">监控自选股前 5 只，全市场监控需 Starter+</span>
                  <button
                    onClick={() => setDismissFreeHint(true)}
                    className="text-amber-400/50 hover:text-amber-400 shrink-0 transition-colors"
                    title="关闭提示"
                  >
                    <X className="h-2.5 w-2.5" />
                  </button>
                </div>
              )}
              {isPaused ? (
                <div className="text-warning/80">数据同步运行中，实时行情已临时暂停</div>
              ) : isRunning && isTrading ? (
                <div className="text-accent">行情运行中</div>
              ) : realtimeEnabled && !isTrading ? (
                <div className="text-warning/70">非交易时段，将在交易时间自动开启</div>
              ) : null}
            </div>
          )}
          {showSidebarQuotes && !isWatchlistMode && (!isNoneTier || !!realtimeProviderName) && (
            <SidebarIndexQuotes rows={sidebarIndexQuotes?.rows} items={sidebarIndexes} />
          )}
        </div>

        <div className="border-t border-border px-2 py-3 shrink-0">
          <div className="flex items-center gap-1">
            <ThemeToggle />
            <NavLink
              to="/settings"
              className={({ isActive }) =>
                cn(
                  'flex flex-1 items-center justify-between gap-3 px-3 py-2 rounded-btn text-sm transition-colors duration-150 ease-smooth',
                  isActive
                    ? 'bg-elevated text-foreground font-medium'
                    : 'text-foreground/80 hover:bg-elevated hover:text-foreground',
                )
              }
            >
              <span className="flex items-center gap-3">
                <Settings className="h-4 w-4 shrink-0" />
                <span>设置</span>
              </span>
              <span className="font-mono text-[10px] text-muted/50 select-none">
                {version ?? ''}
              </span>
            </NavLink>
          </div>
        </div>
      </aside>

      <motion.main
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
        className="h-full overflow-auto scrollbar-gutter-stable"
      >
        {streamStatus === 'reconnecting' && (
          <div
            role="status"
            aria-live="polite"
            className="fixed bottom-4 left-1/2 z-[9998] flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-warning/30 bg-warning/10 px-2.5 py-1 text-[11px] font-medium text-warning shadow-lg backdrop-blur-md"
          >
            <WifiOff className="h-3 w-3 shrink-0 animate-pulse" />
            与服务连接已断开 · 正在重连
          </div>
        )}
        <Suspense
          fallback={
            <div className="flex items-center justify-center py-24">
              <Loader2 className="h-5 w-5 animate-spin text-muted" />
            </div>
          }
        >
          <Outlet />
        </Suspense>
      </motion.main>
      <ToastContainer />
      <AlertToastContainer />
      <AiAnalysisHost />
      <AiReportBubble />
      <StockAnalysisHost />
      <StockAnalysisBubble />
    </div>
  )
}
