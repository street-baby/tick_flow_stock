import { useState, useEffect, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import {
  Zap,
  ShieldAlert,
  Sliders,
  Layers,
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
} from '@/lib/api'
import { fmtPct, priceColorClass } from '@/lib/format'
import { cn } from '@/lib/cn'

export function TradePlan() {
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<'plans' | 'positions' | 'history'>('plans')
  const [previewSymbol, setPreviewSymbol] = useState<string | null>(null)
  
  // Settings modal
  const [settingsOpen, setSettingsOpen] = useState(false)
  // Manual buy / execute modal
  const [buyModalItem, setBuyModalItem] = useState<TradePlanItem | null>(null)
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
        setMarketStatus({ status: '集合竞价中', desc: '9:15-9:25 观察竞价与高开幅度', color: 'text-purple-400' })
      } else if (curMins >= 9 * 60 + 25 && curMins < 9 * 60 + 30) {
        setMarketStatus({ status: '即将开盘', desc: '9:25-9:30 核对开盘价与止损线', color: 'text-cyan-400' })
      } else if ((curMins >= 9 * 60 + 30 && curMins <= 11 * 60 + 30) || (curMins >= 13 * 60 && curMins <= 15 * 60)) {
        setMarketStatus({ status: '连续交易中', desc: '分批执行开仓与分级止盈', color: 'text-emerald-400' })
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

  // Queries
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
      toast('成功录入/执行持仓订单！', 'success')
      queryClient.invalidateQueries({ queryKey: ['trade-plan', 'positions'] })
      queryClient.invalidateQueries({ queryKey: ['trade-plan', 'daily'] })
      setBuyModalItem(null)
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
  const plans = dailyData?.plans ?? []

  // Copy order text for broker app
  const copyOrderText = (item: TradePlanItem) => {
    const text = `买入 ${item.name} (${item.symbol.split('.')[0]})\n计划买入价: ${item.buy_price.toFixed(2)}\n计划买入股数: ${item.suggested_shares}股 (首笔50%: ${item.first_tranche_shares}股)\n严格止损价: ${item.stop_loss_price.toFixed(2)} (-${(item.stop_loss_pct * 100).toFixed(1)}%)\n止盈目标: +1R(${item.tp_1r.toFixed(2)}) / +1.5R(${item.tp_15r.toFixed(2)})`
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

  const alertPositionsCount = useMemo(() => {
    return positions.filter(p => p.action_alerts && p.action_alerts.length > 0).length
  }, [positions])

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
                短线趋势资金共振交易面板
              </h1>
              <span className="rounded-full bg-violet-500/10 px-2.5 py-0.5 text-[11px] font-semibold text-violet-400 border border-violet-500/20">
                短线平衡偏激进 · 半自动人工确认
              </span>
            </div>
            <p className="mt-0.5 text-xs text-muted">
              理想持仓 1~3 天 · 右侧趋势突破 + 缩量回踩 · 0.5%单笔风控 · 每日开盘纪律执行
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
            onClick={() => refetchDaily()}
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
            <span className="text-muted">需处理动作:</span>
            {alertPositionsCount > 0 ? (
              <span className="font-bold text-amber-400 animate-pulse">{alertPositionsCount} 只持仓触发止盈/止损/超时提醒</span>
            ) : (
              <span className="text-muted/70">暂无触发动作，持仓健康</span>
            )}
          </div>
        </div>
      </div>

      {/* 选项卡导航 */}
      <div className="flex items-center gap-2 border-b border-border pb-1">
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
          <span>今日开盘执行计划 ({plans.length})</span>
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
          <Layers className="h-4 w-4" />
          <span>实时持仓与分级止盈 ({positions.length})</span>
          {alertPositionsCount > 0 && (
            <span className="flex h-4 w-4 items-center justify-center rounded-full bg-danger text-[9px] font-bold text-white">
              {alertPositionsCount}
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

      {/* ===== TAB 1: 今日开盘执行计划表 ===== */}
      {activeTab === 'plans' && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-surface/60 px-4 py-2 text-xs text-muted border border-border/60">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-violet-400" />
              <span>
                基准选股日: <span className="font-mono font-medium text-foreground">{dailyData?.date || '最新'}</span> · 严格满足 5 大买入条件与 3 大策略共振
              </span>
            </div>
            <div className="text-[11px] text-amber-400">
              💡 开盘规则: 高开超过 3% 放弃追高 · 开盘买 50% 底仓 · 确认走势后再补 50%
            </div>
          </div>

          {dailyLoading ? (
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <Skeleton className="h-64 rounded-xl" />
              <Skeleton className="h-64 rounded-xl" />
            </div>
          ) : plans.length === 0 ? (
            <div className="rounded-xl border border-border bg-surface p-12 text-center">
              <EmptyState title="今日暂无符合严格买入条件的标的" hint="市场环境或个股未达 72 分及 5 项核心标准，保持空仓也是一种交易纪律。" />
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              {plans.map((item, idx) => (
                <motion.div
                  key={item.symbol}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: idx * 0.05 }}
                  className="flex flex-col justify-between rounded-xl border border-border bg-surface p-4.5 shadow-sm transition-all hover:border-violet-500/40 hover:shadow-md"
                >
                  {/* 头部信息 */}
                  <div>
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
                        </div>
                        <div className="mt-1.5 flex flex-wrap gap-1">
                          {item.strategies.map((st) => (
                            <span key={st} className="rounded bg-violet-500/10 border border-violet-500/20 px-1.5 py-0.5 text-[10px] font-medium text-violet-300">
                              {st}
                            </span>
                          ))}
                          {item.last_limit_date !== '—' && (
                            <span className="rounded bg-amber-500/10 border border-amber-500/20 px-1.5 py-0.5 text-[10px] font-medium text-amber-400">
                              近月涨停: {item.last_limit_date}
                            </span>
                          )}
                        </div>
                      </div>

                      {/* 综合评分徽章 */}
                      <div className="flex flex-col items-end">
                        <div className="flex items-baseline gap-1">
                          <span className="text-xl font-extrabold font-mono text-violet-400">{item.composite_score}</span>
                          <span className="text-[10px] text-muted">分</span>
                        </div>
                        <span className="text-[10px] text-muted">综合强度评分</span>
                      </div>
                    </div>

                    {/* 买入理由列表 */}
                    <div className="mt-3 rounded-lg bg-base/50 p-2.5 text-[11px] text-secondary space-y-1">
                      {item.reasons.map((r, i) => (
                        <div key={i} className="flex items-center gap-1.5">
                          <CheckCircle2 className="h-3 w-3 text-emerald-400 shrink-0" />
                          <span>{r}</span>
                        </div>
                      ))}
                    </div>

                    {/* 算仓与风控矩阵 */}
                    <div className="mt-3.5 grid grid-cols-3 gap-2 rounded-lg border border-border/80 bg-surface/80 p-2.5 text-center">
                      <div>
                        <div className="text-[10px] text-muted">计划买入价</div>
                        <div className="mt-0.5 font-mono text-xs font-bold text-foreground">¥{item.buy_price.toFixed(2)}</div>
                        <div className="mt-0.5 text-[9px] text-muted">高开上限: ¥{item.max_open_price.toFixed(2)}</div>
                      </div>
                      <div>
                        <div className="text-[10px] text-muted">严格止损价</div>
                        <div className="mt-0.5 font-mono text-xs font-bold text-danger">¥{item.stop_loss_price.toFixed(2)}</div>
                        <div className="mt-0.5 font-mono text-[9px] text-danger">-{ (item.stop_loss_pct * 100).toFixed(1) }%</div>
                      </div>
                      <div>
                        <div className="text-[10px] text-muted">建议开仓总额</div>
                        <div className="mt-0.5 font-mono text-xs font-bold text-foreground">¥{item.order_amount.toLocaleString()}</div>
                        <div className="mt-0.5 font-mono text-[9px] text-muted">{item.suggested_shares}股 ({(item.position_pct * 100).toFixed(1)}%)</div>
                      </div>
                    </div>

                    {/* 分批执行与分级止盈阶梯 */}
                    <div className="mt-3 space-y-1.5 text-[11px]">
                      <div className="flex items-center justify-between rounded bg-base/40 px-2 py-1">
                        <span className="text-muted">⚡ 分批建仓指引:</span>
                        <span className="font-medium text-foreground">
                          开盘先买 50% 底仓 (<span className="text-accent font-mono">{item.first_tranche_shares}股</span>) → 走势确认补 50% (<span className="text-accent font-mono">{item.second_tranche_shares}股</span>)
                        </span>
                      </div>
                      <div className="flex items-center justify-between rounded bg-base/40 px-2 py-1">
                        <span className="text-muted">🎯 分级止盈阶梯:</span>
                        <span className="font-mono text-foreground">
                          <span className="text-blue-400">1R(保本): ¥{item.tp_1r.toFixed(2)}</span>
                          <span className="mx-1 text-muted/40">|</span>
                          <span className="text-emerald-400">1.5R(卖1/3): ¥{item.tp_15r.toFixed(2)}</span>
                          <span className="mx-1 text-muted/40">|</span>
                          <span className="text-emerald-400">2R: ¥{item.tp_2r.toFixed(2)}</span>
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
                      <span>确认买入 / 录入持仓</span>
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

      {/* ===== TAB 2: 实时持仓与分级止盈止损 ===== */}
      {activeTab === 'positions' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between rounded-lg bg-surface/60 px-4 py-2 text-xs text-muted border border-border/60">
            <span>当前活跃持仓: <strong className="text-foreground">{positions.length}</strong> 只</span>
            <span className="text-[11px] text-accent">
              🛡️ 纪律保障: 达成 1R 自动保本 · 1.5R 卖出 1/3 · 跌破止损坚决清仓
            </span>
          </div>

          {positionsLoading ? (
            <Skeleton className="h-48 rounded-xl" />
          ) : positions.length === 0 ? (
            <div className="rounded-xl border border-border bg-surface p-12 text-center">
              <EmptyState title="暂无持仓标的" hint="可在「今日开盘执行计划」中点击【确认买入】，或点击下方按钮手动录入实盘持仓。" />
              <button
                onClick={() => {
                  setBuyModalItem({
                    symbol: '603366.SH',
                    name: '日出东方',
                    close: 7.33,
                    change_pct: 0,
                    composite_score: 80,
                    trend_score: 20,
                    strategies: ['短线共振'],
                    reasons: [],
                    buy_price: 7.33,
                    stop_loss_price: 7.05,
                    stop_loss_pct: 0.04,
                    max_open_price: 7.55,
                    suggested_shares: 500,
                    order_amount: 3665,
                    position_pct: 0.07,
                    first_tranche_shares: 200,
                    second_tranche_shares: 300,
                    tp_1r: 7.61,
                    tp_15r: 7.75,
                    tp_2r: 7.89,
                    trailing_stop_desc: '',
                    max_holding_days: 5,
                    last_limit_date: '',
                  })
                  setBuyPriceInput(7.33)
                  setBuySharesInput(500)
                }}
                className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-violet-600 px-4 py-2 text-xs font-bold text-white shadow-sm hover:bg-violet-500 cursor-pointer"
              >
                <Plus className="h-3.5 w-3.5" />
                <span>手动录入持仓</span>
              </button>
            </div>
          ) : (
            <div className="space-y-3">
              {positions.map((pos) => (
                <div
                  key={pos.id || pos.symbol}
                  className={cn(
                    'rounded-xl border bg-surface p-4 shadow-sm transition-all',
                    pos.action_alerts && pos.action_alerts.some(a => a.level === 'danger') ? 'border-danger/60 bg-danger/[0.03]' :
                    pos.action_alerts && pos.action_alerts.some(a => a.level === 'success') ? 'border-emerald-500/40 bg-emerald-500/[0.02]' :
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
                          <span className="text-muted">持仓: <span className="font-mono text-foreground">{pos.shares}股</span></span>
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

                      {/* 平仓操作按钮 */}
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
                            setSellSharesInput(pos.shares)
                            setCloseReasonInput('全额清仓')
                          }}
                          className="rounded-lg bg-danger/10 border border-danger/30 px-3 py-1.5 text-xs font-bold text-danger hover:bg-danger/20 cursor-pointer"
                        >
                          清仓
                        </button>
                      </div>
                    </div>
                  </div>

                  {/* 动作提示指令条 */}
                  {pos.action_alerts && pos.action_alerts.length > 0 && (
                    <div className="mt-3 space-y-1.5 border-t border-border/60 pt-2.5">
                      {pos.action_alerts.map((al, idx) => (
                        <div
                          key={idx}
                          className={cn(
                            'flex items-center justify-between rounded-lg px-3 py-1.5 text-xs font-medium',
                            al.level === 'danger' ? 'bg-danger/15 text-danger border border-danger/30' :
                            al.level === 'success' ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30' :
                            al.level === 'warning' ? 'bg-amber-500/15 text-amber-300 border border-amber-500/30' :
                            'bg-blue-500/15 text-blue-300 border border-blue-500/30'
                          )}
                        >
                          <div className="flex items-center gap-2">
                            {al.level === 'danger' ? <ShieldAlert className="h-4 w-4 shrink-0" /> : <AlertTriangle className="h-4 w-4 shrink-0" />}
                            <span>{al.desc}</span>
                          </div>
                          <span className="font-bold underline cursor-pointer" onClick={() => {
                            setCloseModalItem(pos)
                            setSellPriceInput(pos.current_price)
                            setSellSharesInput(al.suggested_action.includes('1/3') ? Math.max(100, Math.floor(pos.shares / 3 / 100) * 100) : pos.shares)
                            setCloseReasonInput(al.title)
                          }}>
                            {al.suggested_action} →
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ===== TAB 3: 交易复盘与纪律统计 ===== */}
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

      {/* ===== 弹窗 1: 买入确认 / 录入持仓 ===== */}
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
                <span className="text-muted">建议开盘总额:</span>
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

      {/* ===== 弹窗 2: 平仓录入 ===== */}
      {closeModalItem && (
        <Modal onClose={() => setCloseModalItem(null)}>
          <div className="p-5 space-y-4 text-xs">
            <div className="flex items-center justify-between border-b border-border pb-3">
              <h3 className="text-sm font-bold text-foreground">
                平仓操作: {closeModalItem.name} ({closeModalItem.symbol})
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
              <label className="text-muted">平仓原因 / 出场说明</label>
              <input
                type="text"
                value={closeReasonInput}
                onChange={(e) => setCloseReasonInput(e.target.value)}
                placeholder="例如: 达成+1.5R分批止盈 / 跌破MA5止盈 / 严格止损"
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
                确认平仓
              </button>
            </div>
          </div>
        </Modal>
      )}

      {/* ===== 弹窗 3: 交易风控参数设置 ===== */}
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
