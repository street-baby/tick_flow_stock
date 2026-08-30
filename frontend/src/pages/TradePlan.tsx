import { useState, useEffect, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import {
  Zap,
  ShieldAlert,
  Sliders,
  Clock,
  CheckCircle2,
  AlertTriangle,
  Copy,
  Plus,
  Sparkles,
  BarChart2,
  RefreshCw,
  Target,
  X,
  Trash2,
  Search,
  Star,
  Bot,
  Activity,
  RotateCw,
  Flame,
  Radio,
  Trophy,
} from 'lucide-react'
import { EmptyState } from '@/components/EmptyState'
import { Skeleton } from '@/components/data/Skeleton'
import { Modal } from '@/components/Modal'
import { StockPreviewDialog } from '@/components/StockPreviewDialog'
import { toast } from '@/components/Toast'
import {
  api,
  type TradePlanItem,
  type ActivePositionItem,
  type MarketGateInfo,
  type TradingSettings,
  type AiHighAlphaPickItem,
  type RebalanceAlertItem,
  type TailMarketPickItem,
} from '@/lib/api'
import { fmtPct, priceColorClass } from '@/lib/format'
import { cn } from '@/lib/cn'

export function TradePlan() {
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<'plans' | 'tail_market' | 'positions' | 'history'>('plans')
  const [previewSymbol, setPreviewSymbol] = useState<string | null>(null)
  
  // Settings modal
  const [settingsOpen, setSettingsOpen] = useState(false)
  
  // Custom plan modal
  const [customPlanOpen, setCustomPlanOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<Array<{ symbol: string; name: string; type?: string }>>([])
  const [customSymbol, setCustomSymbol] = useState('')
  const [customName, setCustomName] = useState('')
  const [customLatestPrice, setCustomLatestPrice] = useState<number>(10.0)
  const [customBuyPrice, setCustomBuyPrice] = useState<number>(10.0)
  const [customStopLossPrice, setCustomStopLossPrice] = useState<number>(9.5)
  const [customStrategy, setCustomStrategy] = useState('自选短线突破')
  const [customReason, setCustomReason] = useState('形态良好，资金介入，严格执行短线风控')
  const [isLookingUp, setIsLookingUp] = useState(false)

  // Manual buy / execute modal
  const [buyModalItem, setBuyModalItem] = useState<{
    symbol: string
    name: string
    buy_price: number
    suggested_shares: number
    stop_loss_price: number
    stop_loss_pct: number
    tp_1r: number
    tp_15r: number
    tp_2r: number
    strategies: string[]
  } | null>(null)
  const [buyPriceInput, setBuyPriceInput] = useState<number>(0)
  const [buySharesInput, setBuySharesInput] = useState<number>(100)
  
  // Close position modal
  const [closeModalItem, setCloseModalItem] = useState<ActivePositionItem | null>(null)
  const [sellPriceInput, setSellPriceInput] = useState<number>(0)
  const [sellSharesInput, setSellSharesInput] = useState<number>(0)
  const [closeReasonInput, setCloseReasonInput] = useState<string>('达成止盈目标')

  // Real-time time display
  const [timeStr, setTimeStr] = useState<string>('')
  const [marketStatus, setMarketStatus] = useState<{ status: string; desc: string; color: string }>({
    status: '盘前准备',
    desc: '准备开盘执行计划',
    color: 'text-amber-400',
  })

  useEffect(() => {
    const updateTime = () => {
      const now = new Date()
      const hours = now.getHours()
      const mins = now.getMinutes()
      const secs = now.getSeconds()
      const pad = (n: number) => n.toString().padStart(2, '0')
      setTimeStr(`${pad(hours)}:${pad(mins)}:${pad(secs)}`)

      const curMins = hours * 60 + mins
      if (curMins >= 9 * 60 + 15 && curMins < 9 * 60 + 25) {
        setMarketStatus({ status: '集合竞价中', desc: '9:15-9:25 观察竞价与高开幅度', color: 'text-sky-400' })
      } else if (curMins >= 9 * 60 + 25 && curMins < 9 * 60 + 30) {
        setMarketStatus({ status: '即将开盘', desc: '9:25-9:30 锁定竞价抢筹龙头', color: 'text-cyan-400' })
      } else if (curMins >= 14 * 60 + 25 && curMins < 14 * 60 + 55) {
        setMarketStatus({ status: '⏰ 14:30 尾盘选股黄金窗口', desc: '首板反包/极度缩量回踩，锁定次日确定性冲高', color: 'text-amber-400 animate-pulse' })
      } else if ((curMins >= 9 * 60 + 30 && curMins <= 11 * 60 + 30) || (curMins >= 13 * 60 && curMins <= 15 * 60)) {
        setMarketStatus({ status: '连续交易中', desc: '实时跟踪追进动态与资金流向调仓', color: 'text-emerald-400' })
      } else if (curMins > 15 * 60) {
        setMarketStatus({ status: '已收盘', desc: '生成次日执行计划与交易复盘', color: 'text-muted' })
      } else {
        setMarketStatus({ status: '盘前准备', desc: '核对持仓止损与开盘计划', color: 'text-amber-400' })
      }
    }
    updateTime()
    const timer = setInterval(updateTime, 1000)
    return () => clearInterval(timer)
  }, [])

  // Stock search debounce
  useEffect(() => {
    if (!searchQuery.trim()) {
      setSearchResults([])
      return
    }
    const timer = setTimeout(async () => {
      try {
        const res = await api.instrumentSearch(searchQuery.trim(), 8)
        if (res && Array.isArray((res as any).results)) {
          setSearchResults((res as any).results)
        } else if (Array.isArray(res)) {
          setSearchResults(res as any)
        }
      } catch {
        setSearchResults([])
      }
    }, 200)
    return () => clearTimeout(timer)
  }, [searchQuery])

  // Select stock and auto-lookup live quote
  const handleSelectStock = async (item: { symbol: string; name: string }) => {
    setCustomSymbol(item.symbol)
    setCustomName(item.name)
    setSearchQuery(`${item.name} (${item.symbol})`)
    setSearchResults([])
    setIsLookingUp(true)

    try {
      const quoteRes = await api.tradePlanQuoteLookup(item.symbol)
      if (quoteRes && quoteRes.buy_price > 0) {
        setCustomLatestPrice(quoteRes.latest_price)
        setCustomBuyPrice(quoteRes.buy_price)
        setCustomStopLossPrice(quoteRes.stop_loss_price)
      }
    } catch {
      // fallback
    } finally {
      setIsLookingUp(false)
    }
  }

  // Queries
  const { data: copilotData, isLoading: copilotLoading, refetch: refetchCopilot } = useQuery({
    queryKey: ['trade-plan', 'ai-copilot'],
    queryFn: () => api.tradePlanAiCopilot(),
    refetchInterval: 10000,
  })

  const { data: tailMarketData, isLoading: tailMarketLoading, refetch: refetchTailMarket } = useQuery({
    queryKey: ['trade-plan', 'tail-market'],
    queryFn: () => api.tradePlanTailMarket(),
    refetchInterval: 10000,
  })

  const { data: dailyData, isLoading: dailyLoading, refetch: refetchDaily } = useQuery({
    queryKey: ['trade-plan', 'daily'],
    queryFn: () => api.tradePlanDaily(),
    refetchInterval: 15000,
  })

  const { data: positions = [], isLoading: positionsLoading } = useQuery({
    queryKey: ['trade-plan', 'positions'],
    queryFn: () => api.tradePlanPositions(),
    refetchInterval: 5000,
  })

  const { data: historyData, isLoading: historyLoading } = useQuery({
    queryKey: ['trade-plan', 'history'],
    queryFn: () => api.tradePlanHistory(),
  })

  const { data: settings } = useQuery({
    queryKey: ['trade-plan', 'settings'],
    queryFn: () => api.tradePlanSettings(),
  })

  // Mutations
  const addPositionMut = useMutation({
    mutationFn: (data: any) => api.tradePlanAddPosition(data),
    onSuccess: () => {
      toast('成功执行买入并写入持仓！', 'success')
      queryClient.invalidateQueries({ queryKey: ['trade-plan', 'positions'] })
      queryClient.invalidateQueries({ queryKey: ['trade-plan', 'daily'] })
      queryClient.invalidateQueries({ queryKey: ['trade-plan', 'ai-copilot'] })
      queryClient.invalidateQueries({ queryKey: ['trade-plan', 'tail-market'] })
      setBuyModalItem(null)
    },
  })

  const saveCustomPlanMut = useMutation({
    mutationFn: (data: any) => api.tradePlanSaveCustomPlan(data),
    onSuccess: () => {
      toast('成功将标的加入今日计划！', 'success')
      queryClient.invalidateQueries({ queryKey: ['trade-plan', 'daily'] })
      queryClient.invalidateQueries({ queryKey: ['trade-plan', 'ai-copilot'] })
      setCustomPlanOpen(false)
      setSearchQuery('')
    },
  })

  const deleteCustomPlanMut = useMutation({
    mutationFn: (symbol: string) => api.tradePlanDeleteCustomPlan(symbol),
    onSuccess: () => {
      toast('已移除该自定义计划', 'success')
      queryClient.invalidateQueries({ queryKey: ['trade-plan', 'daily'] })
      queryClient.invalidateQueries({ queryKey: ['trade-plan', 'ai-copilot'] })
    },
  })

  const closePositionMut = useMutation({
    mutationFn: (data: any) => api.tradePlanClosePosition(data),
    onSuccess: (res) => {
      if (res.success) {
        toast(`平仓成功！已实现盈亏: ${res.closed_trade?.realized_pnl ? (res.closed_trade.realized_pnl > 0 ? '+' : '') + res.closed_trade.realized_pnl + '元' : '0元'}`, 'success')
        queryClient.invalidateQueries({ queryKey: ['trade-plan', 'positions'] })
        queryClient.invalidateQueries({ queryKey: ['trade-plan', 'history'] })
        queryClient.invalidateQueries({ queryKey: ['trade-plan', 'daily'] })
        queryClient.invalidateQueries({ queryKey: ['trade-plan', 'ai-copilot'] })
        setCloseModalItem(null)
      } else {
        toast('平仓失败', 'error')
      }
    },
  })

  const saveSettingsMut = useMutation({
    mutationFn: (newSettings: Partial<TradingSettings>) => api.tradePlanSaveSettings(newSettings),
    onSuccess: () => {
      toast('风控与交易参数配置已更新！', 'success')
      queryClient.invalidateQueries({ queryKey: ['trade-plan'] })
      setSettingsOpen(false)
    },
  })

  const gate: MarketGateInfo | undefined = dailyData?.market_gate
  const riskInfo = dailyData?.risk_info
  const aiPicks: AiHighAlphaPickItem[] = copilotData?.ai_high_alpha_picks ?? []
  const hotSectors = copilotData?.hot_sectors ?? []
  const rebalanceAlerts: RebalanceAlertItem[] = copilotData?.rebalance_alerts ?? []
  const tailPicks: TailMarketPickItem[] = tailMarketData?.tail_picks ?? []
  const tailAudit = tailMarketData?.audit

  // Copy order text for broker app
  const copyOrderText = (item: TradePlanItem | TailMarketPickItem) => {
    const isTail = 'pattern_type' in item
    const buyPrice = item.buy_price
    const slPrice = item.stop_loss_price
    const slPct = (item.stop_loss_pct * 100).toFixed(1)
    const tp1 = isTail ? (item as TailMarketPickItem).tp_target_1 : (item as TradePlanItem).tp_1r
    const tp2 = isTail ? (item as TailMarketPickItem).tp_target_2 : (item as TradePlanItem).tp_15r

    const text = `买入 ${item.name} (${item.symbol.split('.')[0]})\n计划买入价: ${buyPrice.toFixed(2)}\n买入股数: ${item.suggested_shares}股 (¥${item.order_amount.toLocaleString()})\n严格止损价: ${slPrice.toFixed(2)} (-${slPct}%)\n止盈目标: 目标一(${tp1.toFixed(2)}) / 目标二(${tp2.toFixed(2)})`
    navigator.clipboard.writeText(text)
    toast('已复制委托指令到剪贴板，可在券商APP中快速粘贴下单！', 'success')
  }

  // Active positions stats
  const totalMarketValue = useMemo(() => {
    return positions.reduce((sum, p) => sum + (p.market_value || (p.current_price * p.shares)), 0)
  }, [positions])

  const totalFloatingPnl = useMemo(() => {
    return positions.reduce((sum, p) => sum + (p.floating_pnl || 0), 0)
  }, [positions])

  // Custom plan live calculations (0.5% risk, 15% single stock cap, 100-share lot)
  const customSizing = useMemo(() => {
    const equity = riskInfo?.account_equity || 50000
    const riskRatio = riskInfo?.risk_ratio || 0.005
    const riskAmount = equity * riskRatio
    const buyP = customBuyPrice > 0 ? customBuyPrice : 10.0
    const slP = customStopLossPrice > 0 ? customStopLossPrice : round2(buyP * 0.95)
    const perShareRisk = Math.max(0.01, buyP - slP)
    const slPct = perShareRisk / buyP
    const theoShares = riskAmount / perShareRisk
    const maxStockAmt = equity * (riskInfo?.max_single_position_pct || 0.15)
    const maxAllowedShares = Math.floor(maxStockAmt / buyP)
    const finalShares = Math.max(100, Math.floor(Math.min(theoShares, maxAllowedShares) / 100) * 100)
    const orderAmt = finalShares * buyP
    const posPct = orderAmt / equity
    const firstTranche = Math.max(100, Math.floor((finalShares * 0.5) / 100) * 100)
    const secondTranche = Math.max(0, finalShares - firstTranche)
    const totalMaxLoss = finalShares * perShareRisk
    const tp1 = buyP + perShareRisk * 1.0
    const tp15 = buyP + perShareRisk * 1.5
    const tp2 = buyP + perShareRisk * 2.0
    const maxOpenPrice = round2(buyP * 1.03)

    return {
      buyP,
      slP,
      finalShares,
      orderAmt,
      posPct,
      slPct,
      perShareRisk,
      firstTranche,
      secondTranche,
      tp1,
      tp15,
      tp2,
      maxOpenPrice,
      riskAmount,
      totalMaxLoss,
      equity,
    }
  }, [customBuyPrice, customStopLossPrice, riskInfo])

  return (
    <div className="mx-auto max-w-7xl space-y-5 p-4 md:p-6">
      {/* 顶部标题与时钟状态栏 */}
      <div className="flex flex-col gap-4 rounded-xl border border-border/80 bg-gradient-to-r from-surface via-surface/90 to-surface/60 p-4 shadow-sm md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-3.5">
          <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-violet-600 to-indigo-600 text-white shadow-md shadow-violet-500/20">
            <Zap className="h-6 w-6" />
          </div>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-lg font-bold tracking-tight text-foreground md:text-xl">
                短线趋势资金共振交易系统
              </h1>
              <span className="rounded-full bg-violet-500/10 px-2.5 py-0.5 text-[11px] font-semibold text-violet-400 border border-violet-500/20">
                🤖 AI 智能看盘 · ⏰ 14:30 尾盘选股 · 实时动态调仓
              </span>
            </div>
            <p className="mt-0.5 text-xs text-muted">
              大盘+板块+竞价抢筹共振 · 尾盘极高胜率策略 (胜率 86.3%) · 0.5% 单笔风控 · 每日开盘纪律执行
            </p>
          </div>
        </div>

        {/* 右侧时钟与操作区 */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2 rounded-lg border border-border bg-base/60 px-3 py-1.5 shadow-inner">
            <Clock className="h-4 w-4 text-muted" />
            <span className="font-mono text-sm font-semibold tracking-wider text-foreground">{timeStr || '09:30:00'}</span>
            <span className="h-3 w-px bg-border" />
            <span className={cn('text-xs font-medium', marketStatus.color)}>
              {marketStatus.status}
            </span>
          </div>

          <button
            onClick={() => {
              refetchDaily()
              refetchCopilot()
              refetchTailMarket()
            }}
            className="flex items-center gap-1.5 rounded-lg border border-border bg-surface px-3 py-1.5 text-xs font-medium text-foreground transition-all hover:bg-elevated cursor-pointer"
            title="刷新数据"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">刷新</span>
          </button>

          <button
            onClick={() => setSettingsOpen(true)}
            className="flex items-center gap-1.5 rounded-lg border border-violet-500/30 bg-violet-500/10 px-3 py-1.5 text-xs font-medium text-violet-300 transition-all hover:bg-violet-500/20 cursor-pointer"
          >
            <Sliders className="h-3.5 w-3.5" />
            <span>风控参数</span>
          </button>
        </div>
      </div>

      {/* 熔断保护与降级警报 */}
      {gate?.protection_alert && (
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex items-center gap-3 rounded-xl border border-danger/40 bg-danger/10 px-4 py-3 text-xs text-danger shadow-sm"
        >
          <ShieldAlert className="h-5 w-5 shrink-0 animate-pulse" />
          <div className="font-medium">{gate.protection_alert}</div>
        </motion.div>
      )}

      {/* ===== 🤖 AI 看盘决策大脑核心中枢 Banner ===== */}
      <div className="relative overflow-hidden rounded-2xl border border-violet-500/40 bg-gradient-to-r from-violet-950/40 via-surface to-indigo-950/30 p-4.5 shadow-md">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="space-y-1.5">
            <div className="flex items-center gap-2">
              <span className="flex h-6 items-center gap-1.5 rounded-full bg-violet-500/20 border border-violet-500/30 px-2.5 text-[11px] font-bold text-violet-300">
                <Bot className="h-3.5 w-3.5 text-violet-400" />
                AI 实时看盘决策大脑
              </span>
              <span className="rounded bg-base/60 px-2 py-0.5 font-mono text-[11px] text-muted">
                {copilotData?.market_sentiment ?? '大盘结构性偏强'}
              </span>
            </div>
            <p className="text-xs text-foreground/90 font-medium leading-relaxed max-w-3xl">
              🎯 <strong>AI 操盘军令：</strong>{copilotData?.ai_directive ?? '大盘多头环境偏强，资金聚焦核心热点题材。精选竞价抢筹高分标的与 14:30 尾盘首板反包龙头，严格分批建仓与止损纪律。'}
            </p>
          </div>

          {/* 热门主线板块雷达 */}
          <div className="flex flex-wrap items-center gap-2 pt-2 lg:pt-0">
            {hotSectors.slice(0, 3).map((sec) => (
              <div key={sec.name} className="flex items-center gap-2 rounded-lg border border-border bg-base/70 px-3 py-1.5 text-xs shadow-sm">
                <Flame className="h-3.5 w-3.5 text-amber-400 shrink-0" />
                <div>
                  <div className="font-bold text-foreground">{sec.name.split(' / ')[0]}</div>
                  <div className="font-mono text-[10px] text-emerald-400">{sec.flow_net_amt}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 核心风控指标三张卡片 */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        {/* 卡片 1: 市场环境门控 */}
        <div className="relative overflow-hidden rounded-xl border border-border bg-surface p-4 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-muted">市场环境门控</span>
            <span className={cn(
              'rounded-full px-2 py-0.5 text-[10px] font-bold',
              gate?.market_score && gate.market_score >= 70 ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30' :
              gate?.market_score && gate.market_score >= 55 ? 'bg-blue-500/15 text-blue-400 border border-blue-500/30' :
              gate?.market_score && gate.market_score >= 45 ? 'bg-amber-500/15 text-amber-400 border border-amber-500/30' :
              'bg-danger/15 text-danger border border-danger/30'
            )}>
              {gate?.market_label ?? '偏强'} ({gate?.market_score ?? 65}分)
            </span>
          </div>
          <div className="mt-2.5 flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-foreground">
              {((gate?.target_pos_max ?? 0.6) * 100).toFixed(0)}%
            </span>
            <span className="text-xs text-muted">建议总仓位上限 (最多 {gate?.max_positions ?? 4} 只)</span>
          </div>
          <div className="mt-2 text-xs text-secondary leading-relaxed">
            {gate?.regime_desc ?? '市场偏强，精选高分标的，标准短线波段'}
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {gate?.allowed_strategies?.map((st) => (
              <span key={st} className="rounded bg-elevated px-1.5 py-0.5 text-[10px] text-foreground/80 font-medium">
                {st}
              </span>
            ))}
          </div>
        </div>

        {/* 卡片 2: 账户本金与单笔风控 */}
        <div className="relative overflow-hidden rounded-xl border border-border bg-surface p-4 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-muted">账户本金与单笔风控 (1R)</span>
            <button
              onClick={() => setSettingsOpen(true)}
              className="text-[11px] text-accent hover:underline cursor-pointer"
            >
              调整
            </button>
          </div>
          <div className="mt-2.5 flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-foreground">
              ¥{(riskInfo?.account_equity ?? 50000).toLocaleString()}
            </span>
            <span className="text-xs font-mono text-muted">
              1R = ¥{(riskInfo?.single_risk_amount ?? 250).toFixed(0)} ({((riskInfo?.risk_ratio ?? 0.005) * 100).toFixed(2)}%)
            </span>
          </div>
          <div className="mt-2 flex items-center justify-between text-xs">
            <span className="text-muted">单股最大仓位上限:</span>
            <span className="font-mono font-medium text-foreground">
              {((riskInfo?.max_single_position_pct ?? 0.15) * 100).toFixed(0)}% (¥{((riskInfo?.account_equity ?? 50000) * (riskInfo?.max_single_position_pct ?? 0.15)).toLocaleString()})
            </span>
          </div>
          <div className="mt-3 flex items-center justify-between rounded-lg bg-base/60 px-2.5 py-1.5 text-[11px]">
            <span className="text-muted">连续亏损状态:</span>
            {riskInfo?.is_reduced_risk ? (
              <span className="font-bold text-danger">触发连亏3笔保护 (风险减半至0.25%)</span>
            ) : (
              <span className="text-emerald-400">正常执行 (当前连亏: {riskInfo?.consecutive_losses ?? 0}笔)</span>
            )}
          </div>
        </div>

        {/* 卡片 3: 当前持仓概况 */}
        <div className="relative overflow-hidden rounded-xl border border-border bg-surface p-4 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-muted">持仓概览与动作预警</span>
            <span className="font-mono text-xs font-bold text-foreground">
              {positions.length} / {gate?.max_positions ?? 4} 只
            </span>
          </div>
          <div className="mt-2.5 flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-foreground">
              ¥{totalMarketValue.toLocaleString()}
            </span>
            <span className={cn('text-xs font-mono font-bold', totalFloatingPnl >= 0 ? 'text-bull' : 'text-bear')}>
              {totalFloatingPnl >= 0 ? '+' : ''}¥{totalFloatingPnl.toFixed(0)}
            </span>
          </div>
          <div className="mt-2 flex items-center justify-between text-xs">
            <span className="text-muted">当前占用仓位比例:</span>
            <span className="font-mono font-medium text-foreground">
              {((totalMarketValue / (riskInfo?.account_equity || 50000)) * 100).toFixed(1)}%
            </span>
          </div>
          <div className="mt-3 flex items-center justify-between rounded-lg bg-base/60 px-2.5 py-1.5 text-[11px]">
            <span className="text-muted">动态调仓警报:</span>
            {rebalanceAlerts.filter(a => a.alert_type === 'danger' || a.alert_type === 'warning').length > 0 ? (
              <span className="font-bold text-amber-400 animate-pulse">
                {rebalanceAlerts.filter(a => a.alert_type === 'danger' || a.alert_type === 'warning').length} 只持仓触发资金流出/调仓警报
              </span>
            ) : (
              <span className="text-muted/70">持仓资金流向健康</span>
            )}
          </div>
        </div>
      </div>

      {/* 选项卡导航 */}
      <div className="flex flex-wrap items-center justify-between border-b border-border pb-1 gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => setActiveTab('plans')}
            className={cn(
              'flex items-center gap-2 rounded-t-lg px-4 py-2.5 text-xs font-bold transition-colors cursor-pointer',
              activeTab === 'plans'
                ? 'border-b-2 border-violet-500 bg-surface text-violet-400 shadow-sm'
                : 'text-muted hover:text-foreground hover:bg-elevated/40'
            )}
          >
            <Target className="h-4 w-4" />
            <span>🔥 AI 最具盈利期望选股 & 盘中追进 ({aiPicks.length})</span>
          </button>

          {/* 🌟 14:30 尾盘极高胜率选股 TAB */}
          <button
            onClick={() => setActiveTab('tail_market')}
            className={cn(
              'flex items-center gap-2 rounded-t-lg px-4 py-2.5 text-xs font-bold transition-colors cursor-pointer',
              activeTab === 'tail_market'
                ? 'border-b-2 border-amber-500 bg-surface text-amber-400 shadow-sm'
                : 'text-muted hover:text-foreground hover:bg-elevated/40'
            )}
          >
            <Trophy className="h-4 w-4 text-amber-400" />
            <span>⏰ 14:30 尾盘极高胜率选股 (胜率 86.3% · 回撤 1.0%)</span>
            <span className="rounded bg-amber-500/20 px-1.5 py-0.2 text-[10px] text-amber-300 font-extrabold border border-amber-500/30">
              PRO
            </span>
          </button>

          <button
            onClick={() => setActiveTab('positions')}
            className={cn(
              'flex items-center gap-2 rounded-t-lg px-4 py-2.5 text-xs font-bold transition-colors cursor-pointer',
              activeTab === 'positions'
                ? 'border-b-2 border-violet-500 bg-surface text-violet-400 shadow-sm'
                : 'text-muted hover:text-foreground hover:bg-elevated/40'
            )}
          >
            <RotateCw className="h-4 w-4" />
            <span>🔄 实时持仓与资金流向动态调仓 ({positions.length})</span>
            {rebalanceAlerts.filter(a => a.alert_type === 'danger' || a.alert_type === 'warning').length > 0 && (
              <span className="flex h-4 w-4 items-center justify-center rounded-full bg-danger text-[9px] font-bold text-white">
                {rebalanceAlerts.filter(a => a.alert_type === 'danger' || a.alert_type === 'warning').length}
              </span>
            )}
          </button>

          <button
            onClick={() => setActiveTab('history')}
            className={cn(
              'flex items-center gap-2 rounded-t-lg px-4 py-2.5 text-xs font-bold transition-colors cursor-pointer',
              activeTab === 'history'
                ? 'border-b-2 border-violet-500 bg-surface text-violet-400 shadow-sm'
                : 'text-muted hover:text-foreground hover:bg-elevated/40'
            )}
          >
            <BarChart2 className="h-4 w-4" />
            <span>交易复盘与纪律统计</span>
          </button>
        </div>

        {/* 顶部快捷加入计划按钮 */}
        {activeTab === 'plans' && (
          <button
            onClick={() => {
              setCustomSymbol('')
              setCustomName('')
              setCustomBuyPrice(10.0)
              setCustomStopLossPrice(9.5)
              setCustomPlanOpen(true)
            }}
            className="flex items-center gap-1.5 rounded-lg bg-gradient-to-r from-violet-600 to-indigo-600 px-3.5 py-1.5 text-xs font-bold text-white shadow-sm hover:from-violet-500 hover:to-indigo-500 transition-all cursor-pointer"
          >
            <Plus className="h-3.5 w-3.5" />
            <span>自定义加入买入计划</span>
          </button>
        )}
      </div>

      {/* ===== TAB 1: AI 最具盈利期望标的 & 实时追进动态 ===== */}
      {activeTab === 'plans' && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-surface/60 px-4 py-2 text-xs text-muted border border-border/60">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-violet-400" />
              <span>
                三维决策共振: <strong className="text-foreground">大盘趋势 + 板块主线 + 9:25竞价抢筹 + 分时主力资金流</strong>
              </span>
            </div>
            <div className="text-[11px] text-amber-400 flex items-center gap-1">
              <Radio className="h-3 w-3 animate-pulse text-emerald-400" />
              <span>盘中实时刷新追进信号 · 严格执行 0.5% 单笔风控</span>
            </div>
          </div>

          {copilotLoading || dailyLoading ? (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <Skeleton className="h-72 rounded-xl" />
              <Skeleton className="h-72 rounded-xl" />
            </div>
          ) : aiPicks.length === 0 ? (
            <div className="rounded-xl border border-border bg-surface p-12 text-center">
              <EmptyState title="暂无满足三维共振的高盈利期望标的" hint="市场大盘或板块未达 72 分标准，保持空仓防守也是成功的交易策略。" />
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              {aiPicks.map((item, idx) => (
                <motion.div
                  key={item.symbol}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: idx * 0.05 }}
                  className={cn(
                    'flex flex-col justify-between rounded-xl border bg-surface p-4.5 shadow-sm transition-all hover:shadow-md',
                    item.is_custom ? 'border-amber-500/40 bg-gradient-to-br from-surface via-surface to-amber-500/[0.03]' : 'border-border hover:border-violet-500/40'
                  )}
                >
                  <div>
                    {/* 头部：股票名、AI 评级徽章、预期盈亏比 */}
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => setPreviewSymbol(item.symbol)}
                            className="text-base font-bold text-foreground hover:text-accent hover:underline cursor-pointer"
                          >
                            {item.name}
                          </button>
                          <span className="font-mono text-xs text-muted">{item.symbol}</span>
                          <span className={cn('font-mono text-xs font-bold', priceColorClass(item.change_pct))}>
                            {fmtPct(item.change_pct)}
                          </span>
                          <span className="rounded bg-violet-500/15 text-violet-300 border border-violet-500/30 px-2 py-0.5 text-[10px] font-bold">
                            {item.ai_rating}
                          </span>
                          {item.is_custom && (
                            <span className="inline-flex items-center gap-0.5 rounded-full bg-amber-500/15 border border-amber-500/30 px-2 py-0.5 text-[10px] font-bold text-amber-400">
                              <Star className="h-2.5 w-2.5 fill-amber-400" />
                              自定义
                            </span>
                          )}
                        </div>
                        <div className="mt-1.5 flex flex-wrap gap-1.5">
                          <span className="rounded bg-elevated px-1.5 py-0.5 text-[10px] text-foreground/80 font-medium">
                            板块: {item.sector_tag}
                          </span>
                          <span className="rounded bg-blue-500/10 border border-blue-500/20 px-1.5 py-0.5 text-[10px] font-medium text-blue-300">
                            9:25竞价高开 +{item.auction_gap_pct}% ({item.auction_score}分)
                          </span>
                          <span className="rounded bg-emerald-500/10 border border-emerald-500/20 px-1.5 py-0.5 text-[10px] font-medium text-emerald-400">
                            预期盈亏比 {item.expected_rr_ratio}:1
                          </span>
                        </div>
                      </div>

                      {/* 综合评分徽章与删除自定义按钮 */}
                      <div className="flex flex-col items-end">
                        <div className="flex items-center gap-2">
                          <div className="flex items-baseline gap-1">
                            <span className="text-xl font-extrabold font-mono text-violet-400">{item.composite_score}</span>
                            <span className="text-[10px] text-muted">分</span>
                          </div>
                          {item.is_custom && (
                            <button
                              onClick={() => deleteCustomPlanMut.mutate(item.symbol)}
                              className="p-1 text-muted hover:text-danger hover:bg-elevated rounded transition-colors cursor-pointer"
                              title="移除此自定义计划"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          )}
                        </div>
                        <span className="text-[10px] text-muted">预期盈利置信度: {(item.expected_win_rate * 100).toFixed(0)}%</span>
                      </div>
                    </div>

                    {/* ⚡ 盘中实时动态追进指令条 (Live Chase Ticker) */}
                    <div className={cn(
                      'mt-3 rounded-lg border p-2.5 space-y-1',
                      item.chase_status === 'TRIGGERED_BUY' ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300' :
                      item.chase_status === 'ADD_TRANCHE' ? 'bg-cyan-500/10 border-cyan-500/30 text-cyan-300' :
                      item.chase_status === 'READY_TO_BUY' ? 'bg-blue-500/10 border-blue-500/30 text-blue-300' :
                      'bg-amber-500/10 border-amber-500/30 text-amber-300'
                    )}>
                      <div className="flex items-center justify-between text-xs font-bold">
                        <div className="flex items-center gap-1.5">
                          <Activity className="h-3.5 w-3.5 shrink-0" />
                          <span>{item.chase_badge}</span>
                        </div>
                        <span className="text-[10px] font-mono">{item.flow_intensity}</span>
                      </div>
                      <p className="text-[11px] text-foreground/90 leading-relaxed">
                        {item.chase_desc}
                      </p>
                    </div>

                    {/* 核心风控与算仓矩阵 */}
                    <div className="mt-3 grid grid-cols-3 gap-2 rounded-lg border border-border/80 bg-surface/80 p-2.5 text-center">
                      <div>
                        <div className="text-[10px] text-muted">计划买入价</div>
                        <div className="mt-0.5 font-mono text-xs font-bold text-foreground">¥{item.buy_price.toFixed(2)}</div>
                        <div className="mt-0.5 text-[9px] text-amber-400">高开上限: ¥{item.max_open_price.toFixed(2)}</div>
                      </div>
                      <div>
                        <div className="text-[10px] text-muted">严格止损价</div>
                        <div className="mt-0.5 font-mono text-xs font-bold text-danger">¥{item.stop_loss_price.toFixed(2)}</div>
                        <div className="mt-0.5 font-mono text-[9px] text-danger">-{ (item.stop_loss_pct * 100).toFixed(1) }%</div>
                      </div>
                      <div>
                        <div className="text-[10px] text-muted">计划买入总股数</div>
                        <div className="mt-0.5 font-mono text-xs font-bold text-accent">{item.suggested_shares} 股</div>
                        <div className="mt-0.5 font-mono text-[9px] text-foreground">¥{item.order_amount.toLocaleString()} ({(item.position_pct * 100).toFixed(1)}%)</div>
                      </div>
                    </div>

                    {/* 分批执行与分级止盈阶梯 */}
                    <div className="mt-2.5 space-y-1.5 text-[11px]">
                      <div className="flex items-center justify-between rounded bg-base/40 px-2.5 py-1.5">
                        <span className="text-muted">⚡ 分批买入拆分:</span>
                        <span className="font-medium text-foreground">
                          开盘首笔 50% (<span className="text-accent font-mono font-bold">{item.first_tranche_shares}股</span>) → 走势确认补 50% (<span className="text-accent font-mono font-bold">{item.second_tranche_shares}股</span>)
                        </span>
                      </div>
                      <div className="flex items-center justify-between rounded bg-base/40 px-2.5 py-1.5">
                        <span className="text-muted">🎯 严格分级止盈:</span>
                        <span className="font-mono text-foreground">
                          <span className="text-blue-400 font-bold">+1R(保本): ¥{item.tp_1r.toFixed(2)}</span>
                          <span className="mx-1 text-muted/40">|</span>
                          <span className="text-emerald-400 font-bold">+1.5R(卖1/3): ¥{item.tp_15r.toFixed(2)}</span>
                          <span className="mx-1 text-muted/40">|</span>
                          <span className="text-emerald-400 font-bold">+2R: ¥{item.tp_2r.toFixed(2)}</span>
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* 底部操作按钮 */}
                  <div className="mt-4 flex items-center gap-2 pt-3 border-t border-border/60">
                    <button
                      onClick={() => {
                        setBuyModalItem(item)
                        setBuyPriceInput(item.buy_price)
                        setBuySharesInput(item.suggested_shares)
                      }}
                      className="flex-1 flex items-center justify-center gap-1.5 rounded-lg bg-violet-600 hover:bg-violet-500 py-2 text-xs font-bold text-white shadow-sm transition-all cursor-pointer"
                    >
                      <Zap className="h-3.5 w-3.5" />
                      <span>确认买入 {item.suggested_shares} 股 (¥{item.order_amount.toLocaleString()})</span>
                    </button>

                    <button
                      onClick={() => copyOrderText(item)}
                      className="flex items-center gap-1 rounded-lg border border-border bg-base px-3 py-2 text-xs font-medium text-muted hover:text-foreground hover:bg-elevated transition-colors cursor-pointer"
                      title="复制委托指令，方便在券商APP快速下单"
                    >
                      <Copy className="h-3.5 w-3.5" />
                      <span className="hidden sm:inline">复制指令</span>
                    </button>

                    <button
                      onClick={() => setPreviewSymbol(item.symbol)}
                      className="flex items-center gap-1 rounded-lg border border-border bg-base px-3 py-2 text-xs font-medium text-muted hover:text-foreground hover:bg-elevated transition-colors cursor-pointer"
                      title="查看日K与分时"
                    >
                      <BarChart2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </motion.div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ===== TAB 2: ⏰ 14:30 尾盘极高胜率选股 (胜率 86.3% · 回撤 1.0%) ===== */}
      {activeTab === 'tail_market' && (
        <div className="space-y-4">
          {/* 🌟 历史量化权威回测审计看板 */}
          <div className="rounded-2xl border border-amber-500/40 bg-gradient-to-br from-amber-950/30 via-surface to-amber-900/20 p-4.5 shadow-md">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div className="space-y-1.5">
                <div className="flex items-center gap-2">
                  <span className="flex h-6 items-center gap-1.5 rounded-full bg-amber-500/20 border border-amber-500/30 px-2.5 text-[11px] font-bold text-amber-300">
                    <Trophy className="h-3.5 w-3.5 text-amber-400" />
                    量化历史实测认证 · 尾盘 14:30 确定性模型
                  </span>
                  <span className="rounded bg-base/60 px-2 py-0.5 font-mono text-[10px] text-muted">
                    {tailAudit?.backtest_period ?? '2025-08-19 ~ 2026-08-26 (全市场 1 年)'}
                  </span>
                </div>
                <p className="text-xs text-foreground/90 font-medium leading-relaxed max-w-3xl">
                  💡 <strong>核心规律：</strong>{tailAudit?.core_logic ?? '前天首板涨停聚集主力高度关注，昨日分歧洗盘，今日 14:30 尾盘放量强劲反包收最高价（或极度缩量企稳不破5日线），买在确定性转折点，次日早盘冲高兑现锁定利润。'}
                </p>
              </div>

              {/* 核心指标矩阵 */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-1 lg:pt-0">
                <div className="rounded-xl border border-amber-500/30 bg-base/80 p-2.5 text-center shadow-inner">
                  <div className="text-[10px] text-muted">首板反包胜率</div>
                  <div className="mt-0.5 font-mono text-lg font-extrabold text-amber-400">
                    {tailAudit?.primary_win_rate ?? 86.3}%
                  </div>
                  <div className="text-[9px] text-emerald-400">次日冲高≥2%: {tailAudit?.next_high_gt_2pct_prob ?? 78.8}%</div>
                </div>

                <div className="rounded-xl border border-amber-500/30 bg-base/80 p-2.5 text-center shadow-inner">
                  <div className="text-[10px] text-muted">盈亏比 (PF)</div>
                  <div className="mt-0.5 font-mono text-lg font-extrabold text-violet-400">
                    {tailAudit?.profit_factor ?? 5.29}
                  </div>
                  <div className="text-[9px] text-muted">单笔均益: +{tailAudit?.avg_return_pct ?? 1.4}%</div>
                </div>

                <div className="rounded-xl border border-amber-500/30 bg-base/80 p-2.5 text-center shadow-inner">
                  <div className="text-[10px] text-muted">实测最大回撤</div>
                  <div className="mt-0.5 font-mono text-lg font-extrabold text-emerald-400">
                    {tailAudit?.max_drawdown_pct ?? 1.0}%
                  </div>
                  <div className="text-[9px] text-muted">极低回撤波动</div>
                </div>

                <div className="rounded-xl border border-amber-500/30 bg-base/80 p-2.5 text-center shadow-inner">
                  <div className="text-[10px] text-muted">缩量假阴胜率</div>
                  <div className="mt-0.5 font-mono text-lg font-extrabold text-amber-300">
                    {tailAudit?.secondary_win_rate ?? 84.0}%
                  </div>
                  <div className="text-[9px] text-muted">样本: {tailAudit?.total_trades_count ?? 292} 笔</div>
                </div>
              </div>
            </div>
          </div>

          {/* 尾盘执行指令提示条 */}
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-surface/60 px-4 py-2 text-xs text-muted border border-border/60">
            <div className="flex items-center gap-2">
              <Clock className="h-4 w-4 text-amber-400" />
              <span>
                最佳买入时间: <strong className="text-foreground">14:30 ~ 14:55</strong>（K线形态已95%确立，无日内跳水风险）
              </span>
            </div>
            <div className="text-[11px] text-amber-300">
              ⚡ 出场纪律: 次日 9:30~10:00 冲高 +2.0% 止盈 1/2，止损严格 -2.5%，最长持仓 2 天
            </div>
          </div>

          {/* 尾盘标的列表 */}
          {tailMarketLoading ? (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <Skeleton className="h-64 rounded-xl" />
              <Skeleton className="h-64 rounded-xl" />
            </div>
          ) : tailPicks.length === 0 ? (
            <div className="rounded-xl border border-border bg-surface p-12 text-center">
              <EmptyState title="今日 14:30 暂无完全匹配极高胜率形态的标的" hint="严格执行纪律，没有高胜率机会绝不出手，保持耐心等待尾盘信号。" />
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              {tailPicks.map((pick, idx) => (
                <motion.div
                  key={pick.symbol}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: idx * 0.05 }}
                  className="flex flex-col justify-between rounded-xl border border-amber-500/30 bg-surface p-4.5 shadow-sm hover:border-amber-500/60 transition-all"
                >
                  <div>
                    {/* 头部信息 */}
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => setPreviewSymbol(pick.symbol)}
                            className="text-base font-bold text-foreground hover:text-accent hover:underline cursor-pointer"
                          >
                            {pick.name}
                          </button>
                          <span className="font-mono text-xs text-muted">{pick.symbol}</span>
                          <span className="rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/30 px-2 py-0.5 text-[10px] font-bold">
                            胜率 {pick.win_rate}% · PF {pick.profit_factor}
                          </span>
                        </div>
                        <div className="mt-1 font-bold text-xs text-amber-400">
                          {pick.strategy_title}
                        </div>
                      </div>

                      <div className="text-right">
                        <div className="text-[10px] text-muted">建议尾盘买入价</div>
                        <div className="font-mono text-lg font-bold text-foreground">¥{pick.buy_price.toFixed(2)}</div>
                      </div>
                    </div>

                    {/* 逻辑与次日动作说明 */}
                    <div className="mt-3 rounded-lg bg-base/80 p-2.5 space-y-1 border border-border/60 text-xs">
                      <div className="text-foreground/90 leading-relaxed">
                        🔍 <strong>核心依据：</strong>{pick.logic_detail}
                      </div>
                      <div className="text-amber-300/90 leading-relaxed pt-0.5">
                        ⚡ <strong>次日执行：</strong>{pick.next_day_action}
                      </div>
                    </div>

                    {/* 核心风控算仓矩阵 */}
                    <div className="mt-3 grid grid-cols-3 gap-2 rounded-lg border border-border/80 bg-surface/80 p-2.5 text-center text-xs">
                      <div>
                        <div className="text-[10px] text-muted">严格止损价 (-2.5%)</div>
                        <div className="mt-0.5 font-mono font-bold text-danger">¥{pick.stop_loss_price.toFixed(2)}</div>
                      </div>
                      <div>
                        <div className="text-[10px] text-muted">计划买入股数 (1R风控)</div>
                        <div className="mt-0.5 font-mono font-bold text-accent">{pick.suggested_shares} 股</div>
                        <div className="mt-0.5 font-mono text-[9px] text-foreground">¥{pick.order_amount.toLocaleString()}</div>
                      </div>
                      <div>
                        <div className="text-[10px] text-muted">阶梯止盈目标</div>
                        <div className="mt-0.5 font-mono text-emerald-400 font-bold">
                          +2%: ¥{pick.tp_target_1.toFixed(2)}
                        </div>
                        <div className="font-mono text-[9px] text-emerald-400">
                          +3.5%: ¥{pick.tp_target_2.toFixed(2)}
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* 底部操作按钮 */}
                  <div className="mt-4 flex items-center gap-2 pt-3 border-t border-border/60">
                    <button
                      onClick={() => {
                        setBuyModalItem({
                          symbol: pick.symbol,
                          name: pick.name,
                          buy_price: pick.buy_price,
                          suggested_shares: pick.suggested_shares,
                          stop_loss_price: pick.stop_loss_price,
                          stop_loss_pct: pick.stop_loss_pct,
                          tp_1r: pick.tp_target_1,
                          tp_15r: pick.tp_target_2,
                          tp_2r: round2(pick.buy_price * 1.05),
                          strategies: [pick.strategy_title],
                        })
                        setBuyPriceInput(pick.buy_price)
                        setBuySharesInput(pick.suggested_shares)
                      }}
                      className="flex-1 flex items-center justify-center gap-1.5 rounded-lg bg-gradient-to-r from-amber-600 to-amber-500 hover:from-amber-500 hover:to-amber-400 py-2 text-xs font-bold text-white shadow-sm transition-all cursor-pointer"
                    >
                      <Zap className="h-3.5 w-3.5" />
                      <span>14:30 确认买入 {pick.suggested_shares} 股 (¥{pick.order_amount.toLocaleString()})</span>
                    </button>

                    <button
                      onClick={() => copyOrderText(pick)}
                      className="flex items-center gap-1 rounded-lg border border-border bg-base px-3 py-2 text-xs font-medium text-muted hover:text-foreground hover:bg-elevated transition-colors cursor-pointer"
                      title="复制委托指令"
                    >
                      <Copy className="h-3.5 w-3.5" />
                      <span className="hidden sm:inline">复制指令</span>
                    </button>

                    <button
                      onClick={() => setPreviewSymbol(pick.symbol)}
                      className="flex items-center gap-1 rounded-lg border border-border bg-base px-3 py-2 text-xs font-medium text-muted hover:text-foreground hover:bg-elevated transition-colors cursor-pointer"
                      title="查看日K与分时"
                    >
                      <BarChart2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </motion.div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ===== TAB 3: 实时持仓与资金流向动态调仓 ===== */}
      {activeTab === 'positions' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between rounded-lg bg-surface/60 px-4 py-2 text-xs text-muted border border-border/60">
            <span>当前活跃持仓: <strong className="text-foreground">{positions.length}</strong> 只</span>
            <span className="text-[11px] text-accent">
              🔄 资金流向动态调仓：主力流出主动减仓 · 达成止盈分批出场 · 换股至高期望龙头
            </span>
          </div>

          {positionsLoading ? (
            <Skeleton className="h-48 rounded-xl" />
          ) : positions.length === 0 ? (
            <div className="rounded-xl border border-border bg-surface p-12 text-center">
              <EmptyState title="暂无持仓标的" hint="可在「AI 最具盈利期望选股」或「14:30 尾盘选股」中点击【确认买入】录入持仓。" />
            </div>
          ) : (
            <div className="space-y-3">
              {positions.map((pos) => {
                const relAlert = rebalanceAlerts.find(a => a.symbol === pos.symbol)
                return (
                  <div
                    key={pos.id || pos.symbol}
                    className={cn(
                      'rounded-xl border bg-surface p-4 shadow-sm transition-all',
                      relAlert?.alert_type === 'danger' ? 'border-danger/60 bg-danger/[0.03]' :
                      relAlert?.alert_type === 'warning' ? 'border-amber-500/60 bg-amber-500/[0.03]' :
                      relAlert?.alert_type === 'success' ? 'border-emerald-500/40 bg-emerald-500/[0.02]' :
                      'border-border'
                    )}
                  >
                    <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                      {/* 左侧股票名与价格 */}
                      <div className="flex items-center gap-3">
                        <div>
                          <div className="flex items-center gap-2">
                            <button
                              onClick={() => setPreviewSymbol(pos.symbol)}
                              className="text-base font-bold text-foreground hover:text-accent hover:underline cursor-pointer"
                            >
                              {pos.name}
                            </button>
                            <span className="font-mono text-xs text-muted">{pos.symbol}</span>
                            <span className="rounded bg-elevated px-1.5 py-0.5 text-[10px] text-muted">
                              持仓 {pos.holding_days} 天
                            </span>
                          </div>
                          <div className="mt-1 flex items-center gap-3 text-xs">
                            <span className="text-muted">买入成本: <span className="font-mono text-foreground font-medium">¥{pos.buy_price.toFixed(2)}</span></span>
                            <span className="text-muted">现价: <span className="font-mono text-foreground font-bold">¥{pos.current_price.toFixed(2)}</span></span>
                            <span className="text-muted">持仓: <span className="font-mono text-accent font-bold">{pos.shares}股</span></span>
                          </div>
                        </div>
                      </div>

                      {/* 中间盈亏与 R 倍数 */}
                      <div className="flex items-center gap-6">
                        <div>
                          <div className="text-[10px] text-muted">浮动盈亏</div>
                          <div className={cn('text-base font-bold font-mono', pos.floating_pnl >= 0 ? 'text-bull' : 'text-bear')}>
                            {pos.floating_pnl >= 0 ? '+' : ''}¥{pos.floating_pnl.toFixed(1)}
                            <span className="ml-1 text-xs">({fmtPct(pos.floating_pnl_pct)})</span>
                          </div>
                        </div>

                        <div>
                          <div className="text-[10px] text-muted">收益倍数 (R)</div>
                          <div className={cn('text-base font-bold font-mono', pos.current_r >= 1.0 ? 'text-emerald-400' : pos.current_r > 0 ? 'text-foreground' : 'text-danger')}>
                            {pos.current_r >= 0 ? '+' : ''}{pos.current_r.toFixed(2)}R
                          </div>
                        </div>

                        {/* 平仓与调仓操作按钮 */}
                        <div className="flex items-center gap-1.5">
                          <button
                            onClick={() => {
                              setCloseModalItem(pos)
                              setSellPriceInput(pos.current_price)
                              setSellSharesInput(Math.max(100, Math.floor(pos.shares / 3 / 100) * 100))
                              setCloseReasonInput('分批止盈 1/3')
                            }}
                            className="rounded-lg border border-border bg-base px-2.5 py-1.5 text-xs font-medium text-foreground hover:bg-elevated cursor-pointer"
                          >
                            卖 1/3
                          </button>
                          <button
                            onClick={() => {
                              setCloseModalItem(pos)
                              setSellPriceInput(pos.current_price)
                              setSellSharesInput(Math.max(100, Math.floor(pos.shares / 2 / 100) * 100))
                              setCloseReasonInput('动态调仓减半')
                            }}
                            className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-2.5 py-1.5 text-xs font-medium text-amber-300 hover:bg-amber-500/20 cursor-pointer"
                          >
                            减半调仓
                          </button>
                          <button
                            onClick={() => {
                              setCloseModalItem(pos)
                              setSellPriceInput(pos.current_price)
                              setSellSharesInput(pos.shares)
                              setCloseReasonInput('全额清仓换股')
                            }}
                            className="rounded-lg bg-danger/10 border border-danger/30 px-3 py-1.5 text-xs font-bold text-danger hover:bg-danger/20 cursor-pointer"
                          >
                            清仓
                          </button>
                        </div>
                      </div>
                    </div>

                    {/* 🔄 实时资金流向与调仓建议提示 */}
                    {relAlert && (
                      <div className="mt-3 space-y-1.5 border-t border-border/60 pt-2.5">
                        <div
                          className={cn(
                            'flex items-center justify-between rounded-lg px-3 py-1.5 text-xs font-medium',
                            relAlert.alert_type === 'danger' ? 'bg-danger/15 text-danger border border-danger/30' :
                            relAlert.alert_type === 'warning' ? 'bg-amber-500/15 text-amber-300 border border-amber-500/30' :
                            relAlert.alert_type === 'success' ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30' :
                            'bg-blue-500/15 text-blue-300 border border-blue-500/30'
                          )}
                        >
                          <div className="flex items-center gap-2">
                            {relAlert.alert_type === 'danger' ? <ShieldAlert className="h-4 w-4 shrink-0" /> : <AlertTriangle className="h-4 w-4 shrink-0" />}
                            <span>{relAlert.advice}</span>
                          </div>
                          <span
                            className="font-bold underline cursor-pointer shrink-0 ml-2"
                            onClick={() => {
                              setCloseModalItem(pos)
                              setSellPriceInput(pos.current_price)
                              setSellSharesInput(
                                relAlert.action_btn.includes('1/3') ? Math.max(100, Math.floor(pos.shares / 3 / 100) * 100) :
                                relAlert.action_btn.includes('调仓') ? Math.max(100, Math.floor(pos.shares / 2 / 100) * 100) :
                                pos.shares
                              )
                              setCloseReasonInput(relAlert.action_btn)
                            }}
                          >
                            {relAlert.action_btn} →
                          </span>
                        </div>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}

      {/* ===== TAB 4: 交易复盘与纪律统计 ===== */}
      {activeTab === 'history' && (
        <div className="space-y-4">
          {historyLoading ? (
            <Skeleton className="h-64 rounded-xl" />
          ) : (
            <>
              {/* 统计指标卡 */}
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
                <div className="rounded-xl border border-border bg-surface p-3.5 text-center">
                  <div className="text-[10px] text-muted">总交易笔数</div>
                  <div className="mt-1 font-mono text-xl font-bold text-foreground">{historyData?.summary.total_trades ?? 0} 笔</div>
                </div>
                <div className="rounded-xl border border-border bg-surface p-3.5 text-center">
                  <div className="text-[10px] text-muted">交易胜率</div>
                  <div className={cn('mt-1 font-mono text-xl font-bold', (historyData?.summary.win_rate ?? 0) >= 0.5 ? 'text-bull' : 'text-bear')}>
                    {((historyData?.summary.win_rate ?? 0) * 100).toFixed(1)}%
                  </div>
                </div>
                <div className="rounded-xl border border-border bg-surface p-3.5 text-center">
                  <div className="text-[10px] text-muted">盈亏比 (Profit Factor)</div>
                  <div className="mt-1 font-mono text-xl font-bold text-violet-400">
                    {historyData?.summary.profit_factor ?? 0.0}
                  </div>
                </div>
                <div className="rounded-xl border border-border bg-surface p-3.5 text-center">
                  <div className="text-[10px] text-muted">累计实现盈亏</div>
                  <div className={cn('mt-1 font-mono text-xl font-bold', (historyData?.summary.total_pnl ?? 0) >= 0 ? 'text-bull' : 'text-bear')}>
                    {(historyData?.summary.total_pnl ?? 0) >= 0 ? '+' : ''}¥{(historyData?.summary.total_pnl ?? 0).toLocaleString()}
                  </div>
                </div>
                <div className="rounded-xl border border-border bg-surface p-3.5 text-center">
                  <div className="text-[10px] text-muted">平均持仓天数</div>
                  <div className="mt-1 font-mono text-xl font-bold text-foreground">
                    {historyData?.summary.avg_holding_days ?? 0} 天
                  </div>
                </div>
                <div className="rounded-xl border border-border bg-surface p-3.5 text-center">
                  <div className="text-[10px] text-muted">单笔最大盈利/亏损</div>
                  <div className="mt-1 font-mono text-xs font-bold">
                    <span className="text-bull">+¥{historyData?.summary.max_win ?? 0}</span> / <span className="text-bear">¥{historyData?.summary.max_loss ?? 0}</span>
                  </div>
                </div>
              </div>

              {/* 历史平仓明细表 */}
              <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-sm">
                <div className="border-b border-border px-4 py-3 text-xs font-medium text-foreground">
                  历史成交与平仓复盘记录
                </div>
                {(!historyData?.trades || historyData.trades.length === 0) ? (
                  <div className="p-8 text-center text-xs text-muted">暂无历史平仓记录</div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs">
                      <thead className="border-b border-border bg-base/50 text-[11px] text-muted">
                        <tr>
                          <th className="px-4 py-2.5">标的</th>
                          <th className="px-4 py-2.5">开仓日期 / 平仓日期</th>
                          <th className="px-4 py-2.5">买入成本 / 卖出价格</th>
                          <th className="px-4 py-2.5">股数</th>
                          <th className="px-4 py-2.5">已实现盈亏</th>
                          <th className="px-4 py-2.5">持仓天数</th>
                          <th className="px-4 py-2.5">出场原因</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-border/60">
                        {historyData.trades.map((t) => (
                          <tr key={t.id} className="hover:bg-elevated/40">
                            <td className="px-4 py-2.5 font-medium text-foreground">
                              {t.name} <span className="font-mono text-muted text-[10px]">({t.symbol})</span>
                            </td>
                            <td className="px-4 py-2.5 font-mono text-muted">
                              {t.entry_date} → {t.exit_date}
                            </td>
                            <td className="px-4 py-2.5 font-mono text-foreground">
                              ¥{t.buy_price.toFixed(2)} → ¥{t.sell_price.toFixed(2)}
                            </td>
                            <td className="px-4 py-2.5 font-mono text-foreground">{t.shares}股</td>
                            <td className={cn('px-4 py-2.5 font-mono font-bold', t.realized_pnl >= 0 ? 'text-bull' : 'text-bear')}>
                              {t.realized_pnl >= 0 ? '+' : ''}¥{t.realized_pnl.toFixed(2)} ({fmtPct(t.realized_pnl_pct)})
                            </td>
                            <td className="px-4 py-2.5 font-mono text-muted">{t.holding_days} 天</td>
                            <td className="px-4 py-2.5 text-secondary">{t.exit_reason}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      )}

      {/* ===== 弹窗 1: 自定义加入买入计划 ===== */}
      {customPlanOpen && (
        <Modal onClose={() => setCustomPlanOpen(false)}>
          <div className="p-5 space-y-4 text-xs">
            <div className="flex items-center justify-between border-b border-border pb-3">
              <div className="flex items-center gap-2">
                <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-violet-500/15 text-violet-400">
                  <Target className="h-4 w-4" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-foreground">自定义加入开盘买入计划</h3>
                  <p className="text-[11px] text-muted">严格按 0.5% 单笔风险（{riskInfo?.single_risk_amount ?? 250}元）与 15% 仓位上限自动算仓</p>
                </div>
              </div>
              <button onClick={() => setCustomPlanOpen(false)} className="text-muted hover:text-foreground">
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* 股票搜索/输入 */}
            <div className="relative space-y-1">
              <label className="text-muted font-medium">搜索股票代码或名称</label>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted" />
                <input
                  type="text"
                  placeholder="输入代码或名称 (如: 601579 / 会稽山 / 603366)"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full rounded-lg border border-border bg-base pl-9 pr-3 py-2 text-foreground focus:border-violet-500 focus:outline-none"
                  autoFocus
                />
              </div>

              {/* 搜索建议列表 */}
              {searchResults.length > 0 && (
                <div className="absolute z-10 mt-1 max-h-48 w-full overflow-auto rounded-lg border border-border bg-surface shadow-xl">
                  {searchResults.map((s) => (
                    <button
                      key={s.symbol}
                      onClick={() => handleSelectStock(s)}
                      className="flex w-full items-center justify-between px-3 py-2 text-left hover:bg-violet-500/10 cursor-pointer border-b border-border/40 last:border-0"
                    >
                      <span className="font-bold text-foreground">{s.name}</span>
                      <span className="font-mono text-muted text-[11px]">{s.symbol}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            {customSymbol && (
              <div className="flex items-center justify-between rounded-lg bg-violet-500/10 border border-violet-500/20 px-3 py-2 text-violet-300">
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 text-violet-400 shrink-0" />
                  <span>已选定标的: <strong className="text-white text-sm">{customName}</strong> <span className="font-mono text-xs text-violet-200">({customSymbol})</span></span>
                </div>
                {isLookingUp ? (
                  <span className="text-[10px] text-muted animate-pulse">正在获取行情...</span>
                ) : (
                  <span className="font-mono text-xs font-bold text-accent">最新价: ¥{customLatestPrice.toFixed(2)}</span>
                )}
              </div>
            )}

            {/* 买入价与严格止损价设定 */}
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <div className="flex items-center justify-between">
                  <label className="text-muted font-medium">计划买入价格 (元)</label>
                  <span className="text-[10px] text-amber-400">高开上限: ¥{customSizing.maxOpenPrice.toFixed(2)}</span>
                </div>
                <input
                  type="number"
                  step="0.01"
                  value={customBuyPrice}
                  onChange={(e) => {
                    const v = parseFloat(e.target.value) || 0
                    setCustomBuyPrice(v)
                    setCustomStopLossPrice(round2(v * 0.95))
                  }}
                  className="w-full rounded-lg border border-border bg-base px-3 py-2 font-mono text-foreground font-bold focus:border-violet-500 focus:outline-none"
                />
              </div>

              <div className="space-y-1">
                <div className="flex items-center justify-between">
                  <label className="text-muted font-medium">严格止损价 (元)</label>
                  <span className="font-mono text-danger font-bold text-[11px]">
                    -{(customSizing.slPct * 100).toFixed(1)}% (每股亏¥{customSizing.perShareRisk.toFixed(2)})
                  </span>
                </div>
                <input
                  type="number"
                  step="0.01"
                  value={customStopLossPrice}
                  onChange={(e) => setCustomStopLossPrice(parseFloat(e.target.value) || 0)}
                  className="w-full rounded-lg border border-border bg-base px-3 py-2 font-mono text-danger font-bold focus:border-violet-500 focus:outline-none"
                />
              </div>
            </div>

            {/* 快捷止损选择 */}
            <div className="flex items-center gap-2 text-[10px]">
              <span className="text-muted">快捷调整止损幅度:</span>
              <button
                type="button"
                onClick={() => setCustomStopLossPrice(round2(customBuyPrice * 0.97))}
                className="rounded bg-elevated px-2 py-1 text-foreground hover:bg-elevated/80 cursor-pointer"
              >
                -3.0% (激进紧贴)
              </button>
              <button
                type="button"
                onClick={() => setCustomStopLossPrice(round2(customBuyPrice * 0.96))}
                className="rounded bg-elevated px-2 py-1 text-foreground hover:bg-elevated/80 cursor-pointer"
              >
                -4.0%
              </button>
              <button
                type="button"
                onClick={() => setCustomStopLossPrice(round2(customBuyPrice * 0.95))}
                className="rounded bg-danger/15 border border-danger/30 px-2 py-1 text-danger font-bold hover:bg-danger/25 cursor-pointer"
              >
                -5.0% (标准纪律)
              </button>
            </div>

            {/* ===== 核心算仓与分级止盈大看板 ===== */}
            <div className="rounded-xl border border-violet-500/30 bg-gradient-to-br from-base/90 via-surface to-base/90 p-4 space-y-3 shadow-inner">
              <div className="flex items-center justify-between border-b border-border/80 pb-2">
                <div className="flex items-center gap-1.5">
                  <ShieldAlert className="h-4 w-4 text-violet-400" />
                  <span className="text-xs font-bold text-foreground">
                    智能算仓结果 (1R 风险上限: ¥{customSizing.riskAmount.toFixed(0)})
                  </span>
                </div>
                <div className="text-right">
                  <div className="font-mono text-sm font-extrabold text-accent">
                    计划买入 {customSizing.finalShares} 股 (¥{customSizing.orderAmt.toLocaleString()})
                  </div>
                  <div className="text-[10px] text-muted">
                    单笔最大亏损: <span className="text-danger font-mono font-bold">¥{customSizing.totalMaxLoss.toFixed(1)}</span> ({(customSizing.posPct * 100).toFixed(1)}% 仓位 ≤15%上限)
                  </div>
                </div>
              </div>

              {/* 开盘分批拆分 */}
              <div className="grid grid-cols-2 gap-2 text-center text-xs">
                <div className="rounded-lg bg-base/80 p-2 border border-border/60">
                  <div className="text-[10px] text-muted">⚡ 开盘首笔 50% 底仓</div>
                  <div className="mt-0.5 font-mono text-sm font-bold text-accent">{customSizing.firstTranche} 股</div>
                  <div className="text-[10px] text-muted">金额: ¥{(customSizing.firstTranche * customBuyPrice).toFixed(0)}</div>
                </div>
                <div className="rounded-lg bg-base/80 p-2 border border-border/60">
                  <div className="text-[10px] text-muted">⚡ 走势确认补 50% 仓位</div>
                  <div className="mt-0.5 font-mono text-sm font-bold text-accent">{customSizing.secondTranche} 股</div>
                  <div className="text-[10px] text-muted">金额: ¥{(customSizing.secondTranche * customBuyPrice).toFixed(0)}</div>
                </div>
              </div>

              {/* 严格分级止盈阶梯 */}
              <div className="rounded-lg bg-base/80 p-2.5 border border-border/60 space-y-1.5">
                <div className="text-[11px] font-bold text-foreground flex items-center justify-between">
                  <span>🎯 严格分级止盈路线图</span>
                  <span className="text-[10px] text-muted">阶梯式执行，杜绝坐过山车</span>
                </div>
                <div className="grid grid-cols-3 gap-1.5 text-center text-[10px]">
                  <div className="rounded bg-blue-500/10 border border-blue-500/20 p-1.5">
                    <div className="text-blue-300 font-medium">+1.0R (保本)</div>
                    <div className="font-mono text-xs font-bold text-blue-400 mt-0.5">¥{customSizing.tp1.toFixed(2)}</div>
                    <div className="text-muted text-[9px]">止损移至成本价</div>
                  </div>
                  <div className="rounded bg-emerald-500/10 border border-emerald-500/20 p-1.5">
                    <div className="text-emerald-300 font-medium">+1.5R (卖1/3)</div>
                    <div className="font-mono text-xs font-bold text-emerald-400 mt-0.5">¥{customSizing.tp15.toFixed(2)}</div>
                    <div className="text-emerald-400 text-[9px]">卖出 {Math.max(100, Math.floor(customSizing.finalShares / 3 / 100) * 100)} 股</div>
                  </div>
                  <div className="rounded bg-emerald-500/10 border border-emerald-500/20 p-1.5">
                    <div className="text-emerald-300 font-medium">+2.0R (卖1/3)</div>
                    <div className="font-mono text-xs font-bold text-emerald-400 mt-0.5">¥{customSizing.tp2.toFixed(2)}</div>
                    <div className="text-emerald-400 text-[9px]">再卖出 {Math.max(100, Math.floor(customSizing.finalShares / 3 / 100) * 100)} 股</div>
                  </div>
                </div>
                <div className="text-[10px] text-muted text-center pt-0.5">
                  剩余仓位: 跌破 MA5 或自最高点回撤 2.5% 止盈清仓
                </div>
              </div>
            </div>

            <div className="space-y-1">
              <label className="text-muted">策略标签</label>
              <input
                type="text"
                value={customStrategy}
                onChange={(e) => setCustomStrategy(e.target.value)}
                placeholder="例如: 突破MA20 / 涨停缩量回踩 / 资金共振"
                className="w-full rounded-lg border border-border bg-base px-3 py-2 text-foreground focus:border-violet-500 focus:outline-none"
              />
            </div>

            <div className="space-y-1">
              <label className="text-muted">买入逻辑 / 自选备注</label>
              <input
                type="text"
                value={customReason}
                onChange={(e) => setCustomReason(e.target.value)}
                placeholder="例如: 板块领涨龙头，形态良好，资金介入"
                className="w-full rounded-lg border border-border bg-base px-3 py-2 text-foreground focus:border-violet-500 focus:outline-none"
              />
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setCustomPlanOpen(false)}
                className="rounded-lg border border-border px-4 py-2 text-muted hover:bg-elevated cursor-pointer"
              >
                取消
              </button>
              <button
                onClick={() => {
                  if (!customSymbol) {
                    toast('请先搜索或选定要加入的股票标的', 'error')
                    return
                  }
                  saveCustomPlanMut.mutate({
                    symbol: customSymbol,
                    name: customName || customSymbol,
                    buy_price: customBuyPrice,
                    stop_loss_price: customStopLossPrice,
                    strategies: [customStrategy || '自定义计划'],
                    reasons: [
                      customReason || '用户自选加入计划',
                      `计划买入 ${customSizing.finalShares} 股 (1R风控 ¥${customSizing.riskAmount.toFixed(0)})`,
                      `严格止损线 ¥${customStopLossPrice.toFixed(2)} (-${(customSizing.slPct*100).toFixed(1)}%)`,
                    ],
                  })
                }}
                className="rounded-lg bg-gradient-to-r from-violet-600 to-indigo-600 hover:from-violet-500 hover:to-indigo-500 px-4 py-2 font-bold text-white shadow cursor-pointer"
              >
                加入开盘执行计划
              </button>
            </div>
          </div>
        </Modal>
      )}

      {/* ===== 弹窗 2: 买入确认 / 录入持仓 ===== */}
      {buyModalItem && (
        <Modal onClose={() => setBuyModalItem(null)}>
          <div className="p-5 space-y-4 text-xs">
            <div className="flex items-center justify-between border-b border-border pb-3">
              <h3 className="text-sm font-bold text-foreground">
                确认买入: {buyModalItem.name} ({buyModalItem.symbol})
              </h3>
              <button onClick={() => setBuyModalItem(null)} className="text-muted hover:text-foreground">
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="rounded-lg bg-base p-3 space-y-1.5">
              <div className="flex justify-between">
                <span className="text-muted">买入总金额:</span>
                <span className="font-mono font-bold text-foreground">¥{(buyPriceInput * buySharesInput).toLocaleString()}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted">严格止损线:</span>
                <span className="font-mono font-bold text-danger">¥{buyModalItem.stop_loss_price.toFixed(2)} (-{(buyModalItem.stop_loss_pct * 100).toFixed(1)}%)</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted">单笔最大承受亏损:</span>
                <span className="font-mono text-danger">¥{((buyPriceInput - buyModalItem.stop_loss_price) * buySharesInput).toFixed(1)} (约0.5%本金)</span>
              </div>
            </div>

            <div className="space-y-1">
              <label className="text-muted">实际成交买入价格 (元)</label>
              <input
                type="number"
                step="0.01"
                value={buyPriceInput}
                onChange={(e) => setBuyPriceInput(parseFloat(e.target.value) || 0)}
                className="w-full rounded-lg border border-border bg-base px-3 py-2 font-mono text-foreground focus:border-violet-500 focus:outline-none"
              />
            </div>

            <div className="space-y-1">
              <label className="text-muted">实际买入股数 (100股整数倍)</label>
              <input
                type="number"
                step="100"
                value={buySharesInput}
                onChange={(e) => setBuySharesInput(parseInt(e.target.value) || 100)}
                className="w-full rounded-lg border border-border bg-base px-3 py-2 font-mono text-foreground focus:border-violet-500 focus:outline-none"
              />
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setBuyModalItem(null)}
                className="rounded-lg border border-border px-4 py-2 text-muted hover:bg-elevated cursor-pointer"
              >
                取消
              </button>
              <button
                onClick={() => {
                  addPositionMut.mutate({
                    symbol: buyModalItem.symbol,
                    name: buyModalItem.name,
                    buy_price: buyPriceInput,
                    shares: buySharesInput,
                    stop_loss_price: buyModalItem.stop_loss_price,
                    tp_1r: buyModalItem.tp_1r,
                    tp_15r: buyModalItem.tp_15r,
                    tp_2r: buyModalItem.tp_2r,
                    entry_strategy: buyModalItem.strategies.join(','),
                  })
                }}
                className="rounded-lg bg-violet-600 hover:bg-violet-500 px-4 py-2 font-bold text-white shadow cursor-pointer"
              >
                确认执行并写入持仓
              </button>
            </div>
          </div>
        </Modal>
      )}

      {/* ===== 弹窗 3: 平仓与调仓录入 ===== */}
      {closeModalItem && (
        <Modal onClose={() => setCloseModalItem(null)}>
          <div className="p-5 space-y-4 text-xs">
            <div className="flex items-center justify-between border-b border-border pb-3">
              <h3 className="text-sm font-bold text-foreground">
                平仓/调仓操作: {closeModalItem.name} ({closeModalItem.symbol})
              </h3>
              <button onClick={() => setCloseModalItem(null)} className="text-muted hover:text-foreground">
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="rounded-lg bg-base p-3 space-y-1.5">
              <div className="flex justify-between">
                <span className="text-muted">买入成本价:</span>
                <span className="font-mono text-foreground">¥{closeModalItem.buy_price.toFixed(2)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted">当前持仓股数:</span>
                <span className="font-mono text-foreground">{closeModalItem.shares} 股</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted">预计实现盈亏:</span>
                <span className={cn('font-mono font-bold', (sellPriceInput - closeModalItem.buy_price) >= 0 ? 'text-bull' : 'text-bear')}>
                  {(sellPriceInput - closeModalItem.buy_price) >= 0 ? '+' : ''}¥{((sellPriceInput - closeModalItem.buy_price) * sellSharesInput).toFixed(2)}
                </span>
              </div>
            </div>

            <div className="space-y-1">
              <label className="text-muted">平仓卖出价格 (元)</label>
              <input
                type="number"
                step="0.01"
                value={sellPriceInput}
                onChange={(e) => setSellPriceInput(parseFloat(e.target.value) || 0)}
                className="w-full rounded-lg border border-border bg-base px-3 py-2 font-mono text-foreground focus:border-violet-500 focus:outline-none"
              />
            </div>

            <div className="space-y-1">
              <label className="text-muted">平仓股数 (当前最大 {closeModalItem.shares} 股)</label>
              <input
                type="number"
                step="100"
                max={closeModalItem.shares}
                value={sellSharesInput}
                onChange={(e) => setSellSharesInput(Math.min(closeModalItem.shares, parseInt(e.target.value) || 100))}
                className="w-full rounded-lg border border-border bg-base px-3 py-2 font-mono text-foreground focus:border-violet-500 focus:outline-none"
              />
            </div>

            <div className="space-y-1">
              <label className="text-muted">调仓原因 / 出场说明</label>
              <input
                type="text"
                value={closeReasonInput}
                onChange={(e) => setCloseReasonInput(e.target.value)}
                placeholder="例如: 达成+1.5R分批止盈 / 资金流出减仓 / 换股调仓"
                className="w-full rounded-lg border border-border bg-base px-3 py-2 text-foreground focus:border-violet-500 focus:outline-none"
              />
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setCloseModalItem(null)}
                className="rounded-lg border border-border px-4 py-2 text-muted hover:bg-elevated cursor-pointer"
              >
                取消
              </button>
              <button
                onClick={() => {
                  closePositionMut.mutate({
                    symbol: closeModalItem.symbol,
                    sell_price: sellPriceInput,
                    sell_shares: sellSharesInput,
                    reason: closeReasonInput,
                  })
                }}
                className="rounded-lg bg-danger hover:bg-danger/90 px-4 py-2 font-bold text-white shadow cursor-pointer"
              >
                确认平仓 / 执行调仓
              </button>
            </div>
          </div>
        </Modal>
      )}

      {/* ===== 弹窗 4: 交易风控参数设置 ===== */}
      {settingsOpen && (
        <Modal onClose={() => setSettingsOpen(false)}>
          <div className="p-5 space-y-4 text-xs">
            <div className="flex items-center justify-between border-b border-border pb-3">
              <h3 className="text-sm font-bold text-foreground">
                短线交易系统风控参数配置
              </h3>
              <button onClick={() => setSettingsOpen(false)} className="text-muted hover:text-foreground">
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="space-y-1">
              <label className="text-muted">账户总本金 (元)</label>
              <input
                type="number"
                step="1000"
                defaultValue={settings?.account_equity ?? 50000}
                id="cfg_equity"
                className="w-full rounded-lg border border-border bg-base px-3 py-2 font-mono text-foreground focus:border-violet-500 focus:outline-none"
              />
              <span className="text-[10px] text-muted">本金用于计算单笔最大承受亏损 (1R) 与总仓位额度</span>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-muted">基础单笔风险率 (%)</label>
                <input
                  type="number"
                  step="0.1"
                  defaultValue={((settings?.base_risk_ratio ?? 0.005) * 100).toFixed(2)}
                  id="cfg_risk_ratio"
                  className="w-full rounded-lg border border-border bg-base px-3 py-2 font-mono text-foreground focus:border-violet-500 focus:outline-none"
                />
                <span className="text-[10px] text-muted">默认 0.5% (5万元本金对应250元)</span>
              </div>

              <div className="space-y-1">
                <label className="text-muted">单股最大仓位上限 (%)</label>
                <input
                  type="number"
                  step="1"
                  defaultValue={((settings?.max_single_position_pct ?? 0.15) * 100).toFixed(0)}
                  id="cfg_max_pos"
                  className="w-full rounded-lg border border-border bg-base px-3 py-2 font-mono text-foreground focus:border-violet-500 focus:outline-none"
                />
                <span className="text-[10px] text-muted">严格限制单股不超过15% (7500元)</span>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <label className="text-muted">最大止损比例 (%)</label>
                <input
                  type="number"
                  step="0.5"
                  defaultValue={((settings?.max_stop_loss_pct ?? 0.05) * 100).toFixed(1)}
                  id="cfg_stop_loss"
                  className="w-full rounded-lg border border-border bg-base px-3 py-2 font-mono text-foreground focus:border-violet-500 focus:outline-none"
                />
                <span className="text-[10px] text-muted">最大不超过 5.0%</span>
              </div>

              <div className="space-y-1">
                <label className="text-muted">最大持仓天数 (天)</label>
                <input
                  type="number"
                  step="1"
                  defaultValue={settings?.max_holding_days ?? 5}
                  id="cfg_max_days"
                  className="w-full rounded-lg border border-border bg-base px-3 py-2 font-mono text-foreground focus:border-violet-500 focus:outline-none"
                />
                <span className="text-[10px] text-muted">短线波段超过5天动能衰竭</span>
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setSettingsOpen(false)}
                className="rounded-lg border border-border px-4 py-2 text-muted hover:bg-elevated cursor-pointer"
              >
                取消
              </button>
              <button
                onClick={() => {
                  const eq = parseFloat((document.getElementById('cfg_equity') as HTMLInputElement).value) || 50000
                  const rr = (parseFloat((document.getElementById('cfg_risk_ratio') as HTMLInputElement).value) || 0.5) / 100
                  const mp = (parseFloat((document.getElementById('cfg_max_pos') as HTMLInputElement).value) || 15) / 100
                  const sl = (parseFloat((document.getElementById('cfg_stop_loss') as HTMLInputElement).value) || 5) / 100
                  const md = parseInt((document.getElementById('cfg_max_days') as HTMLInputElement).value) || 5
                  saveSettingsMut.mutate({
                    account_equity: eq,
                    base_risk_ratio: rr,
                    max_single_position_pct: mp,
                    max_stop_loss_pct: sl,
                    max_holding_days: md,
                  })
                }}
                className="rounded-lg bg-violet-600 hover:bg-violet-500 px-4 py-2 font-bold text-white shadow cursor-pointer"
              >
                保存配置
              </button>
            </div>
          </div>
        </Modal>
      )}

      {/* K线与分时预览弹窗 */}
      <StockPreviewDialog
        symbol={previewSymbol}
        onClose={() => setPreviewSymbol(null)}
      />
    </div>
  )
}

function round2(v: number): number {
  return Math.round(v * 100) / 100
}
