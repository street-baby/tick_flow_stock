import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Sparkles,
  Search,
  RefreshCw,
  Plus,
  Flame,
  Zap,
  TrendingUp,
  TrendingDown,
  Calendar,
  ExternalLink,
  Trash2,
  Clock,
  SunMedium,
  CheckCircle2,
  Compass,
  ArrowRight,
} from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { api, type TomorrowCatalystItem, type TomorrowCatalystStock } from '@/lib/api'
import { cn } from '@/lib/cn'
import { toast } from '@/components/Toast'

// 模拟小折线 SVG
function Sparkline({ isUp }: { isUp: boolean }) {
  const points = isUp
    ? '0,24 15,20 30,22 45,14 60,18 75,8 90,4'
    : '0,6 15,10 30,8 45,18 60,14 75,22 90,26'
  const strokeColor = isUp ? '#ef4444' : '#22c55e'

  return (
    <svg className="w-24 h-8 shrink-0 overflow-visible" viewBox="0 0 90 30">
      <polyline
        fill="none"
        stroke={strokeColor}
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        points={points}
      />
    </svg>
  )
}

function StockBadge({ stock }: { stock: TomorrowCatalystStock }) {
  const pct = stock.change_pct ?? 0
  const isUp = pct > 0
  const isZero = pct === 0
  const pctStr = `${pct > 0 ? '+' : ''}${pct.toFixed(2)}%`

  return (
    <div
      className={cn(
        'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium border transition-all hover:scale-105 cursor-pointer',
        isUp
          ? 'bg-red-500/10 text-red-400 border-red-500/20 hover:bg-red-500/20 hover:border-red-500/40'
          : isZero
          ? 'bg-surface text-secondary border-border hover:bg-elevated'
          : 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20 hover:bg-emerald-500/20 hover:border-emerald-500/40'
      )}
      title={`${stock.symbol} ${stock.name} ${stock.last_price ? `现价: ¥${stock.last_price}` : ''}`}
    >
      <span className="font-semibold">{stock.name}</span>
      <span className="font-mono text-[11px] font-bold">{pctStr}</span>
    </div>
  )
}

export function TomorrowCatalyst() {
  const qc = useQueryClient()
  const [activeTab, setActiveTab] = useState<'catalysts' | 'flash'>('catalysts')
  const [keyword, setKeyword] = useState('')
  const [selectedDate, setSelectedDate] = useState('2026-08-20')
  const [isAiModalOpen, setIsAiModalOpen] = useState(false)
  const [aiMode, setAiMode] = useState<'catalysts' | 'morning'>('catalysts')
  const [aiPrompt, setAiPrompt] = useState(
    '结合当日全天重大产业政策、全球科技突破、央视与财联社/新浪快讯及主力资金热点，深度提炼出下一个交易日最具爆发潜力的3~5个前瞻主线题材，给出核心逻辑与对应A股龙头受益股。'
  )
  const [isAddModalOpen, setIsAddModalOpen] = useState(false)
  const [newTag, setNewTag] = useState('')
  const [newTitle, setNewTitle] = useState('')
  const [newSummary, setNewSummary] = useState('')
  const [newStocksStr, setNewStocksStr] = useState('')
  const [newSectorPct, setNewSectorPct] = useState('2.0')

  // 获取前瞻题材
  const { data: catalystsData, isLoading: isCatLoading, refetch: refetchCat } = useQuery({
    queryKey: ['tomorrow-catalysts', keyword],
    queryFn: () => api.tomorrowCatalysts(keyword),
  })

  // 获取今日早盘前瞻
  const { data: morningData, isLoading: isMorningLoading, refetch: refetchMorning } = useQuery({
    queryKey: ['morning-brief'],
    queryFn: () => api.morningBrief(),
  })

  // 获取 7x24 快讯
  const { data: flashData, isLoading: isFlashLoading, refetch: refetchFlash } = useQuery({
    queryKey: ['news-flash'],
    queryFn: () => api.newsFlash(60),
    refetchInterval: 30000,
  })

  // AI 生成前瞻题材 Mutation (AKShare + LLM)
  const aiCatalystsMutation = useMutation({
    mutationFn: ({ targetDate, prompt }: { targetDate: string; prompt: string }) =>
      api.aiGenerateTomorrow(targetDate, prompt),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ['tomorrow-catalysts'] })
      setIsAiModalOpen(false)
      toast(`AI 结合 AKShare 新闻分析完成，已新增 ${res.items?.length || 0} 条题材`, 'success')
    },
    onError: (err: any) => {
      toast(err.message || 'AI 分析失败，请检查设置中的 AI 模型配置', 'error')
    },
  })

  // AI 生成早盘前瞻 Mutation
  const aiMorningMutation = useMutation({
    mutationFn: ({ targetDate, prompt }: { targetDate: string; prompt: string }) =>
      api.aiGenerateMorningBrief(targetDate, prompt),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['morning-brief'] })
      setIsAiModalOpen(false)
      toast('今日早盘前瞻已生成', 'success')
    },
    onError: (err: any) => {
      toast(err.message || 'AI 早盘分析失败', 'error')
    },
  })

  // 手工添加 Mutation
  const addMutation = useMutation({
    mutationFn: (item: Partial<TomorrowCatalystItem>) => api.saveCatalyst(item),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tomorrow-catalysts'] })
      setIsAddModalOpen(false)
      setNewTag('')
      setNewTitle('')
      setNewSummary('')
      setNewStocksStr('')
      toast('题材催化添加成功', 'success')
    },
  })

  // 删除 Mutation
  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteCatalyst(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['tomorrow-catalysts'] })
      toast('已删除', 'success')
    },
  })

  // 按日期分组
  const groupedCatalysts = useMemo(() => {
    const items = catalystsData?.items || []
    const groups: { dateLabel: string; date: string; items: TomorrowCatalystItem[] }[] = []
    const map = new Map<string, TomorrowCatalystItem[]>()

    for (const it of items) {
      const label = it.date_label || it.date || '其他'
      if (!map.has(label)) {
        map.set(label, [])
      }
      map.get(label)!.push(it)
    }

    map.forEach((list, dateLabel) => {
      groups.push({
        dateLabel,
        date: list[0]?.date || '',
        items: list,
      })
    })

    return groups
  }, [catalystsData])

  const handleAddSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!newTitle.trim() || !newTag.trim()) {
      toast('请填写题材标签和标题', 'error')
      return
    }

    const stocks: TomorrowCatalystStock[] = []
    if (newStocksStr.trim()) {
      const parts = newStocksStr.split(/[,，\n]/)
      for (const p of parts) {
        const trimmed = p.trim()
        if (!trimmed) continue
        const tokens = trimmed.split(/\s+/)
        if (tokens.length >= 2) {
          stocks.push({ name: tokens[0], symbol: tokens[1] })
        } else {
          stocks.push({ name: tokens[0], symbol: tokens[0] })
        }
      }
    }

    addMutation.mutate({
      tag: newTag.trim(),
      title: newTitle.trim(),
      summary: newSummary.trim(),
      sector_change_pct: parseFloat(newSectorPct) || 0.0,
      stocks,
    })
  }

  const brief = morningData?.brief

  return (
    <div className="min-h-full bg-base text-foreground pb-16">
      {/* 顶部主横幅与导航 */}
      <div className="sticky top-0 z-20 border-b border-border bg-surface/95 backdrop-blur-md px-6 py-4">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-amber-500/20 via-orange-500/20 to-red-500/20 border border-amber-500/30 text-amber-400 shadow-[0_0_15px_rgba(245,158,11,0.15)]">
              <Flame className="h-5 w-5 animate-pulse text-amber-400" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-lg font-bold text-foreground tracking-wide">
                  明天炒什么 · 题材催化前瞻
                </h1>
                <span className="inline-flex items-center gap-1 rounded-full border border-blue-500/30 bg-blue-500/10 px-2 py-0.5 text-[10px] font-semibold text-blue-400">
                  <Sparkles className="h-3 w-3" />
                  AKShare + 智兔联动
                </span>
              </div>
              <p className="text-xs text-muted mt-0.5">
                整合全网财经热点与央视/东财数据，AI深度提炼明日主线与开盘前瞻
              </p>
            </div>
          </div>

          {/* 选项卡 & 操作栏 */}
          <div className="flex items-center flex-wrap gap-2.5">
            {/* 子 Tab */}
            <div className="flex items-center bg-elevated/70 p-0.5 rounded-lg border border-border">
              <button
                onClick={() => setActiveTab('catalysts')}
                className={cn(
                  'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer',
                  activeTab === 'catalysts'
                    ? 'bg-surface text-foreground shadow-sm font-semibold'
                    : 'text-muted hover:text-foreground'
                )}
              >
                <Flame className="h-3.5 w-3.5 text-amber-400" />
                明天炒什么
              </button>
              <button
                onClick={() => setActiveTab('flash')}
                className={cn(
                  'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors cursor-pointer',
                  activeTab === 'flash'
                    ? 'bg-surface text-foreground shadow-sm font-semibold'
                    : 'text-muted hover:text-foreground'
                )}
              >
                <Zap className="h-3.5 w-3.5 text-blue-400" />
                7x24 实时快讯
                {flashData?.total ? (
                  <span className="text-[10px] bg-blue-500/20 text-blue-300 px-1 rounded-full">
                    {flashData.total}
                  </span>
                ) : null}
              </button>
            </div>

            {/* 搜索框 */}
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted" />
              <input
                type="text"
                placeholder="搜索题材 / 关键词 / 个股..."
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                className="h-8 w-40 md:w-52 pl-8 pr-3 text-xs rounded-lg border border-border bg-elevated/50 text-foreground placeholder:text-muted focus:outline-none focus:border-accent transition-colors"
              />
            </div>

            {/* AI 智能生成按钮 */}
            <button
              onClick={() => {
                setAiMode('catalysts')
                setIsAiModalOpen(true)
              }}
              className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg border border-sky-500/30 bg-sky-500/10 text-xs font-medium text-sky-300 hover:bg-sky-500/20 hover:border-sky-500/50 transition-colors cursor-pointer"
            >
              <Sparkles className="h-3.5 w-3.5 text-sky-400" />
              AI 智能提炼
            </button>

            {/* 添加题材按钮 */}
            <button
              onClick={() => setIsAddModalOpen(true)}
              className="inline-flex items-center gap-1 h-8 px-2.5 rounded-lg border border-border bg-surface text-xs font-medium text-secondary hover:text-foreground hover:bg-elevated transition-colors cursor-pointer"
              title="手动添加题材催化"
            >
              <Plus className="h-3.5 w-3.5" />
              添加
            </button>

            {/* 刷新 */}
            <button
              onClick={() => {
                refetchCat()
                refetchFlash()
                refetchMorning()
                toast('数据已刷新', 'success')
              }}
              className="inline-flex items-center justify-center h-8 w-8 rounded-lg border border-border bg-surface text-muted hover:text-foreground hover:bg-elevated transition-colors cursor-pointer"
              title="刷新数据"
            >
              <RefreshCw className={cn('h-3.5 w-3.5', (isCatLoading || isFlashLoading || isMorningLoading) && 'animate-spin')} />
            </button>
          </div>
        </div>
      </div>

      {/* 主体内容 */}
      <div className="max-w-7xl mx-auto px-6 pt-6 space-y-6">
        {/* 🌅 今日早盘开盘前瞻 · 盘前必读卡片 */}
        {brief && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            className="relative overflow-hidden rounded-2xl border border-amber-500/30 bg-gradient-to-br from-amber-500/[0.08] via-surface to-surface p-5 shadow-lg"
          >
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 border-b border-border/60 pb-3">
              <div className="flex items-center gap-2.5">
                <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-amber-500/20 text-amber-400">
                  <SunMedium className="h-4 w-4" />
                </span>
                <span className="text-sm font-bold text-foreground">🌅 今日早盘前瞻 · 盘前必读</span>
                <span className="text-[11px] font-mono text-muted">({brief.updated_at || brief.date})</span>
                <span className="inline-flex items-center gap-1 rounded-full border border-amber-500/40 bg-amber-500/15 px-2 py-0.5 text-[11px] font-bold text-amber-300">
                  <Compass className="h-3 w-3" />
                  {brief.sentiment}
                </span>
              </div>

              <button
                onClick={() => {
                  setAiMode('morning')
                  setIsAiModalOpen(true)
                }}
                className="text-xs text-sky-400 hover:text-sky-300 flex items-center gap-1 cursor-pointer font-medium"
              >
                <Sparkles className="h-3 w-3" />
                AI 重算早盘
              </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-3 text-xs">
              <div className="space-y-1.5 md:border-r border-border/60 md:pr-4">
                <div className="font-semibold text-secondary flex items-center gap-1">
                  <CheckCircle2 className="h-3.5 w-3.5 text-bull" />
                  今晨要闻主线
                </div>
                <p className="text-foreground/90 font-medium leading-relaxed">
                  {brief.headline}
                </p>
                <p className="text-muted text-[11px] leading-relaxed pt-1">
                  {brief.overnight_summary}
                </p>
              </div>

              <div className="space-y-2 md:border-r border-border/60 md:pr-4">
                <div className="font-semibold text-secondary flex items-center gap-1">
                  <Flame className="h-3.5 w-3.5 text-amber-400" />
                  开盘核心关注方向
                </div>
                <div className="space-y-1.5">
                  {brief.core_focus?.map((f, i) => (
                    <div key={i} className="flex items-start gap-1.5 bg-elevated/60 p-1.5 rounded-lg border border-border/40">
                      <span className="px-1.5 py-0.2 rounded text-[10px] font-bold bg-amber-500/15 text-amber-300 shrink-0">
                        {f.tag}
                      </span>
                      <span className="text-foreground/80 text-[11px] leading-snug truncate">
                        {f.desc}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="space-y-1.5">
                <div className="font-semibold text-secondary flex items-center gap-1">
                  <ArrowRight className="h-3.5 w-3.5 text-accent" />
                  今日竞价与开盘策略
                </div>
                <div className="bg-elevated/80 p-2.5 rounded-xl border border-border/60 text-foreground/90 leading-relaxed text-[11px]">
                  {brief.opening_tactics}
                </div>
              </div>
            </div>
          </motion.div>
        )}

        {/* 选项卡内容 */}
        {activeTab === 'catalysts' ? (
          <div className="space-y-8">
            {groupedCatalysts.length === 0 && !isCatLoading && (
              <div className="text-center py-16 border border-dashed border-border rounded-2xl bg-surface/30">
                <Flame className="h-10 w-10 text-muted mx-auto mb-3 opacity-40" />
                <div className="text-sm font-medium text-foreground">暂无匹配的前瞻题材数据</div>
                <p className="text-xs text-muted mt-1">您可以点击右上角「AI 智能提炼」结合 AKShare 全网新闻一键归纳</p>
              </div>
            )}

            {groupedCatalysts.map((group) => (
              <div key={group.dateLabel} className="space-y-3">
                {/* 日期分组 Header */}
                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-elevated text-xs font-mono font-bold text-foreground border border-border">
                    <Calendar className="h-3.5 w-3.5 text-accent" />
                    {group.dateLabel}
                  </div>
                  <div className="h-px flex-1 bg-border/60" />
                  <span className="text-[11px] text-muted">{group.items.length} 个前瞻驱动</span>
                </div>

                {/* 催化卡片列表 */}
                <div className="space-y-3">
                  {group.items.map((item) => {
                    const sectorPct = item.sector_change_pct ?? 0
                    const isSectorUp = sectorPct >= 0
                    const pctFormatted = `${sectorPct >= 0 ? '+' : ''}${sectorPct.toFixed(2)}%`

                    return (
                      <motion.div
                        key={item.id}
                        initial={{ opacity: 0, y: 6 }}
                        animate={{ opacity: 1, y: 0 }}
                        className="group relative rounded-xl border border-border/80 bg-surface hover:border-accent/40 hover:bg-elevated/40 transition-all p-5 shadow-sm overflow-hidden"
                      >
                        {/* 左侧装饰小色条 */}
                        <div
                          className={cn(
                            'absolute left-0 top-0 bottom-0 w-1',
                            isSectorUp ? 'bg-red-500/60' : 'bg-emerald-500/60'
                          )}
                        />

                        <div className="flex flex-col md:flex-row md:items-start justify-between gap-4">
                          {/* 左侧主体内容 */}
                          <div className="space-y-2.5 flex-1 min-w-0">
                            {/* 题材标签 & 标题 */}
                            <div className="flex items-center flex-wrap gap-2.5">
                              <span className="inline-flex items-center px-2.5 py-0.5 rounded-md text-xs font-bold bg-sky-500/15 text-sky-300 border border-sky-500/25">
                                {item.tag}
                              </span>
                              <h3 className="text-sm md:text-base font-bold text-foreground tracking-tight group-hover:text-accent transition-colors">
                                {item.title}
                              </h3>
                            </div>

                            {/* 核心驱动深度摘要 */}
                            <p className="text-xs md:text-sm text-foreground/80 leading-relaxed text-justify">
                              {item.summary}
                            </p>

                            {/* 关联受益个股（带实时行情涨跌幅） */}
                            {item.stocks && item.stocks.length > 0 && (
                              <div className="flex items-center flex-wrap gap-2 pt-1">
                                <span className="text-[11px] font-medium text-muted mr-1">
                                  关联龙头/标的:
                                </span>
                                {item.stocks.map((stk, idx) => (
                                  <StockBadge key={`${stk.symbol}-${idx}`} stock={stk} />
                                ))}
                              </div>
                            )}
                          </div>

                          {/* 右侧板块涨跌幅与趋势折线 */}
                          <div className="flex md:flex-col items-end justify-between md:justify-center shrink-0 pt-1 md:pt-0 gap-2 border-t md:border-t-0 border-border/50">
                            <div className="flex items-center gap-2">
                              <span
                                className={cn(
                                  'text-sm md:text-base font-bold font-mono',
                                  isSectorUp ? 'text-red-400' : 'text-emerald-400'
                                )}
                              >
                                {pctFormatted}
                              </span>
                              {isSectorUp ? (
                                <TrendingUp className="h-4 w-4 text-red-400" />
                              ) : (
                                <TrendingDown className="h-4 w-4 text-emerald-400" />
                              )}
                            </div>

                            <Sparkline isUp={isSectorUp} />

                            {/* 删除按钮 */}
                            <button
                              onClick={() => deleteMutation.mutate(item.id)}
                              className="opacity-0 group-hover:opacity-100 p-1 text-muted hover:text-red-400 transition-all cursor-pointer"
                              title="删除此项"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        </div>
                      </motion.div>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        ) : (
          /* 7x24 实时快讯 Tab */
          <div className="space-y-4 max-w-4xl">
            <div className="flex items-center justify-between">
              <div className="text-xs text-muted flex items-center gap-1.5">
                <Clock className="h-3.5 w-3.5 text-blue-400" />
                全网实时抓取 · 30秒自动轮询
              </div>
              <span className="text-xs font-mono text-secondary">
                共 {flashData?.total || 0} 条快讯
              </span>
            </div>

            <div className="relative border-l-2 border-border/80 ml-3 pl-6 space-y-6">
              {flashData?.items?.map((item) => (
                <div key={item.id} className="relative group">
                  {/* 时间轴小圆点 */}
                  <div className="absolute -left-[31px] top-1 h-3.5 w-3.5 rounded-full border-2 border-blue-500 bg-base" />

                  <div className="p-4 rounded-xl border border-border bg-surface hover:border-accent/40 transition-colors space-y-2">
                    <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="text-[11px] font-mono font-medium text-blue-400">
                          {item.time}
                        </span>
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-blue-500/10 text-blue-300 border border-blue-500/20">
                          {item.tag}
                        </span>
                      </div>
                      {item.url && (
                        <a
                          href={item.url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-muted hover:text-foreground text-xs inline-flex items-center gap-0.5"
                        >
                          来源 <ExternalLink className="h-3 w-3" />
                        </a>
                      )}
                    </div>

                    {item.title && item.title !== item.content && (
                      <h4 className="text-sm font-bold text-foreground leading-snug">
                        {item.title}
                      </h4>
                    )}

                    <p className="text-xs text-foreground/80 leading-relaxed">
                      {item.content}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* AI 智能前瞻与早盘分析弹窗 */}
      <AnimatePresence>
        {isAiModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="w-full max-w-lg rounded-2xl border border-sky-500/30 bg-surface p-6 shadow-2xl space-y-4"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-sky-400 font-bold">
                  <Sparkles className="h-5 w-5" />
                  <span>{aiMode === 'catalysts' ? 'AI 全天热点提炼 (AKShare + 大模型)' : 'AI 生成今日早盘开盘前瞻'}</span>
                </div>
                <button
                  onClick={() => setIsAiModalOpen(false)}
                  className="text-muted hover:text-foreground text-sm cursor-pointer"
                >
                  ✕
                </button>
              </div>

              {/* 模式选择 */}
              <div className="flex items-center bg-elevated p-1 rounded-xl border border-border">
                <button
                  type="button"
                  onClick={() => setAiMode('catalysts')}
                  className={cn(
                    'flex-1 py-1.5 text-xs font-semibold rounded-lg transition-colors cursor-pointer',
                    aiMode === 'catalysts' ? 'bg-surface text-foreground shadow-sm' : 'text-muted hover:text-foreground'
                  )}
                >
                  🔥 盘后前瞻（明天炒什么）
                </button>
                <button
                  type="button"
                  onClick={() => setAiMode('morning')}
                  className={cn(
                    'flex-1 py-1.5 text-xs font-semibold rounded-lg transition-colors cursor-pointer',
                    aiMode === 'morning' ? 'bg-surface text-foreground shadow-sm' : 'text-muted hover:text-foreground'
                  )}
                >
                  🌅 盘前必读（早盘热点前瞻）
                </button>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-secondary mb-1">
                    指定新闻日期
                  </label>
                  <input
                    type="date"
                    value={selectedDate}
                    onChange={(e) => setSelectedDate(e.target.value)}
                    className="w-full text-xs rounded-lg border border-border bg-elevated px-3 py-2 text-foreground focus:outline-none focus:border-sky-500"
                  />
                </div>
                <div className="flex flex-col justify-end">
                  <div className="text-[11px] text-muted leading-tight pb-1">
                    系统将自动调用 AKShare 抓取该日期央视要闻、东财与财联社新闻进行综合研判。
                  </div>
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-secondary mb-1.5">
                  分析侧重点 / 提示词
                </label>
                <textarea
                  rows={3}
                  value={aiPrompt}
                  onChange={(e) => setAiPrompt(e.target.value)}
                  className="w-full text-xs rounded-xl border border-border bg-elevated p-3 text-foreground focus:outline-none focus:border-sky-500 transition-colors"
                />
              </div>

              <div className="flex items-center justify-end gap-2 pt-2">
                <button
                  onClick={() => setIsAiModalOpen(false)}
                  className="px-4 py-2 rounded-lg border border-border text-xs font-medium text-secondary hover:bg-elevated cursor-pointer"
                >
                  取消
                </button>
                <button
                  onClick={() => {
                    if (aiMode === 'catalysts') {
                      aiCatalystsMutation.mutate({ targetDate: selectedDate, prompt: aiPrompt })
                    } else {
                      aiMorningMutation.mutate({ targetDate: selectedDate, prompt: aiPrompt })
                    }
                  }}
                  disabled={aiCatalystsMutation.isPending || aiMorningMutation.isPending}
                  className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg bg-gradient-to-r from-sky-600 to-indigo-600 text-xs font-semibold text-white shadow-lg shadow-sky-500/25 hover:from-sky-500 hover:to-indigo-500 transition-all cursor-pointer disabled:opacity-50"
                >
                  {aiCatalystsMutation.isPending || aiMorningMutation.isPending ? (
                    <>
                      <RefreshCw className="h-3.5 w-3.5 animate-spin" />
                      AKShare 抓取与 AI 深度研判中…
                    </>
                  ) : (
                    <>
                      <Sparkles className="h-3.5 w-3.5" />
                      开始 AI 整合
                    </>
                  )}
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>

      {/* 手动添加题材弹窗 */}
      <AnimatePresence>
        {isAddModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
            <motion.div
              initial={{ scale: 0.95, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.95, opacity: 0 }}
              className="w-full max-w-md rounded-2xl border border-border bg-surface p-6 shadow-2xl space-y-4"
            >
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-bold text-foreground flex items-center gap-1.5">
                  <Plus className="h-4 w-4 text-accent" />
                  添加题材催化
                </h3>
                <button
                  onClick={() => setIsAddModalOpen(false)}
                  className="text-muted hover:text-foreground text-sm cursor-pointer"
                >
                  ✕
                </button>
              </div>

              <form onSubmit={handleAddSubmit} className="space-y-3">
                <div>
                  <label className="block text-xs font-medium text-secondary mb-1">
                    题材标签 (如：存储芯片/固态电池)
                  </label>
                  <input
                    type="text"
                    required
                    value={newTag}
                    onChange={(e) => setNewTag(e.target.value)}
                    placeholder="例如：铝箔"
                    className="w-full text-xs rounded-lg border border-border bg-elevated px-3 py-2 text-foreground focus:outline-none focus:border-accent"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-secondary mb-1">
                    催化主标题
                  </label>
                  <input
                    type="text"
                    required
                    value={newTitle}
                    onChange={(e) => setNewTitle(e.target.value)}
                    placeholder="例如：行业供需拐点已至！高附加值电池铝箔迎量价齐升窗口"
                    className="w-full text-xs rounded-lg border border-border bg-elevated px-3 py-2 text-foreground focus:outline-none focus:border-accent"
                  />
                </div>

                <div>
                  <label className="block text-xs font-medium text-secondary mb-1">
                    核心驱动解读 / 逻辑说明
                  </label>
                  <textarea
                    rows={3}
                    value={newSummary}
                    onChange={(e) => setNewSummary(e.target.value)}
                    placeholder="详细描述政策导向、产业供需矛盾、技术突破或大厂定点情况..."
                    className="w-full text-xs rounded-lg border border-border bg-elevated px-3 py-2 text-foreground focus:outline-none focus:border-accent"
                  />
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-medium text-secondary mb-1">
                      板块预期涨幅(%)
                    </label>
                    <input
                      type="number"
                      step="0.01"
                      value={newSectorPct}
                      onChange={(e) => setNewSectorPct(e.target.value)}
                      placeholder="2.17"
                      className="w-full text-xs rounded-lg border border-border bg-elevated px-3 py-2 text-foreground focus:outline-none focus:border-accent"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-xs font-medium text-secondary mb-1">
                    关联龙头股票 (名称 代码，逗号分隔)
                  </label>
                  <input
                    type="text"
                    value={newStocksStr}
                    onChange={(e) => setNewStocksStr(e.target.value)}
                    placeholder="例如: 金田股份 601609.SH, 陕国投A 000563.SZ"
                    className="w-full text-xs rounded-lg border border-border bg-elevated px-3 py-2 text-foreground focus:outline-none focus:border-accent"
                  />
                </div>

                <div className="flex items-center justify-end gap-2 pt-2">
                  <button
                    type="button"
                    onClick={() => setIsAddModalOpen(false)}
                    className="px-4 py-2 rounded-lg border border-border text-xs font-medium text-secondary hover:bg-elevated cursor-pointer"
                  >
                    取消
                  </button>
                  <button
                    type="submit"
                    className="px-4 py-2 rounded-lg bg-accent text-xs font-semibold text-white hover:bg-accent/90 cursor-pointer"
                  >
                    保存并展示
                  </button>
                </div>
              </form>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  )
}
