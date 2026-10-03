import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Zap,
  RefreshCw,
  Flame,
  Star,
  TrendingUp,
  Coins,
  Search,
  Calendar,
  Sparkles,
  Award,
  Megaphone,
  ShieldCheck,
  ShieldAlert,
  Bot,
  Trophy,
  AlertCircle,
  X,
} from 'lucide-react'
import {
  api,
  fetchGameTheoryFearPool,
  fetchGameTheoryDangerList,
  type AuctionStockRow,
  type AuctionAIAnalysisResult,
  type AICoreStockItem,
} from '@/lib/api'
import { cn } from '@/lib/cn'
import { toast } from '@/components/Toast'
import { StockPreviewDialog } from '@/components/StockPreviewDialog'

type FilterTab = 'all' | 'top_elite' | '5d_lowest_doji' | 'game_fear' | 'announcement' | 'catalyst' | 'earnings' | 'gap_jump' | 'core_purple'

export function AuctionSnatch() {
  const [asOf, setAsOf] = useState('')
  const [minGapPct, setMinGapPct] = useState(1.5)
  const [includeChinext, setIncludeChinext] = useState(true)
  const [includeStar, setIncludeStar] = useState(true)
  const [onlyDoji, setOnlyDoji] = useState(false)
  const [only5dLowest, setOnly5dLowest] = useState(false)
  const [onlyHighWinrate, setOnlyHighWinrate] = useState(false)
  const [requireCatalyst, setRequireCatalyst] = useState(false)
  const [excludeBearAnnouncements, setExcludeBearAnnouncements] = useState(true)
  const [excludeEarningsBear, setExcludeEarningsBear] = useState(true)
  const [requireEarningsBull, setRequireEarningsBull] = useState(false)
  const [minMv, setMinMv] = useState(10)
  const [maxMv, setMaxMv] = useState(200)
  const [keyword, setKeyword] = useState('')
  const [previewSymbol, setPreviewSymbol] = useState<string | null>(null)
  const [previewName, setPreviewName] = useState<string | undefined>(undefined)

  const [filterTab, setFilterTab] = useState<FilterTab>('all')
  const [sortBy, setSortBy] = useState<'score' | 'gap' | 'vol_ratio' | 'amount'>('score')

  // AI 高开逻辑分析状态
  const [aiAnalysis, setAiAnalysis] = useState<AuctionAIAnalysisResult | null>(null)
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [showAiModal, setShowAiModal] = useState(false)

  // 9:25 每日自动竞价推演与 AI 核心 5 只票
  const [isTriggeringAuto, setIsTriggeringAuto] = useState(false)
  const {
    data: latestSnatch,
    refetch: refetchLatestSnatch,
  } = useQuery({
    queryKey: ['latestAuctionSnatch'],
    queryFn: () => api.getLatestAuctionSnatch(),
    staleTime: 30000,
  })

  const handleTriggerAutoSnatch = async () => {
    setIsTriggeringAuto(true)
    try {
      const res = await api.triggerAuctionSnatchAuto()
      toast(res.message || '已触发全量竞价选股与 AI 深度推演', 'success')
      setTimeout(() => {
        refetchLatestSnatch()
        refetch()
      }, 6000)
    } catch (e: any) {
      toast('触发推演失败: ' + (e?.message || '网络异常'), 'error')
    } finally {
      setIsTriggeringAuto(false)
    }
  }

  const { data, refetch, isFetching } = useQuery({
    queryKey: [
      'auction-screen',
      asOf,
      minGapPct,
      includeChinext,
      includeStar,
      onlyDoji,
      minMv,
      maxMv,
      onlyHighWinrate,
      requireCatalyst,
      excludeBearAnnouncements,
      excludeEarningsBear,
      requireEarningsBull,
    ],
    queryFn: () =>
      api.auctionScreen({
        as_of: asOf || undefined,
        min_gap_pct: minGapPct,
        include_chinext: includeChinext,
        include_star: includeStar,
        only_doji: onlyDoji,
        min_mv: minMv,
        max_mv: maxMv,
        only_high_winrate: onlyHighWinrate,
        require_catalyst: requireCatalyst,
        exclude_bear_announcements: excludeBearAnnouncements,
        exclude_earnings_bear: excludeEarningsBear,
        require_earnings_bull: requireEarningsBull,
      }),
    refetchInterval: 15000,
  })

  const rawRows: AuctionStockRow[] = data?.rows || []
  const top5List: AuctionStockRow[] = data?.top5 || rawRows.slice(0, 5)

  const { data: gtFearPool = [] } = useQuery({
    queryKey: ['gameTheoryFearPool'],
    queryFn: () => fetchGameTheoryFearPool(60),
    staleTime: 60000,
  })
  const { data: gtDangerList = [] } = useQuery({
    queryKey: ['gameTheoryDangerList'],
    queryFn: () => fetchGameTheoryDangerList(60),
    staleTime: 60000,
  })
  const fearSet = new Set(gtFearPool.map((f) => f.symbol))
  const dangerSet = new Set(gtDangerList.map((d) => d.symbol))

  const gapJumpCount = rawRows.filter((r) => r.is_gap_jump).length
  const announcementCount = rawRows.filter((r) => r.has_bull_announcement).length
  const catalystCount = rawRows.filter((r) => r.has_sentiment_catalyst).length
  const earningsCount = rawRows.filter((r) => r.has_earnings_catalyst).length
  const lowest5dDojiCount = rawRows.filter((r) => r.is_5d_lowest_doji).length
  const fearCount = rawRows.filter((r) => fearSet.has(r.symbol)).length

  const rows = rawRows
    .filter((r: AuctionStockRow) => {
      if (only5dLowest && !r.is_5d_lowest_vol) return false
      if (filterTab === 'top_elite' && !r.is_top5 && (r.score || 0) < 88) return false
      if (filterTab === '5d_lowest_doji' && !r.is_5d_lowest_doji) return false
      if (filterTab === 'game_fear' && !fearSet.has(r.symbol)) return false
      if (filterTab === 'announcement' && !r.has_bull_announcement) return false
      if (filterTab === 'catalyst' && !r.has_sentiment_catalyst) return false
      if (filterTab === 'earnings' && !r.has_earnings_catalyst) return false
      if (filterTab === 'gap_jump' && !r.is_gap_jump) return false
      if (filterTab === 'core_purple' && !r.is_core_purple) return false
      if (!keyword) return true
      const kw = keyword.toLowerCase()
      return r.name.toLowerCase().includes(kw) || r.symbol.toLowerCase().includes(kw)
    })
    .sort((a: AuctionStockRow, b: AuctionStockRow) => {
      if (sortBy === 'gap') return b.open_gap_pct - a.open_gap_pct
      if (sortBy === 'vol_ratio') return b.bidding_vol_ratio - a.bidding_vol_ratio
      if (sortBy === 'amount') return b.bidding_amount_wan - a.bidding_amount_wan
      return (b.score || 0) - (a.score || 0)
    })

  const handleAiAnalyze = async () => {
    if (rows.length === 0) {
      toast('当前无符合条件的筛选标的', 'error')
      return
    }
    setIsAnalyzing(true)
    setShowAiModal(true)
    try {
      const res = await api.aiAnalyzeAuction(rows, asOf || data?.as_of)
      setAiAnalysis(res)
      toast('AI 高开逻辑分析完成', 'success')
    } catch (e: any) {
      toast('AI 分析请求失败: ' + (e?.message || '网络异常'), 'error')
    } finally {
      setIsAnalyzing(false)
    }
  }

  const openPreview = (symbol: string, name?: string) => {
    setPreviewSymbol(symbol)
    setPreviewName(name)
  }

  const stats = data?.stats

  return (
    <div className="min-h-full bg-base text-foreground pb-16">
      {/* 顶部主横幅 */}
      <div className="sticky top-0 z-20 border-b border-border bg-surface/95 backdrop-blur-md px-6 py-4">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-amber-500/20 via-orange-500/20 to-red-500/20 border border-orange-500/30 text-orange-400 shadow-[0_0_15px_rgba(249,115,22,0.15)]">
              <Zap className="h-5 w-5 animate-pulse text-orange-400" />
            </div>
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h1 className="text-lg font-bold text-foreground">9:25 集合竞价抢筹</h1>
                <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-500/20 text-amber-400 border border-amber-500/30">
                  🏆 多因子高胜率增强 (次日溢价率 68%)
                </span>
                {data?.is_live && (
                  <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 animate-pulse">
                    🟢 智兔实时竞价
                  </span>
                )}
              </div>
              <p className="text-xs text-muted mt-0.5">
                深度融合<strong>公司突发公告</strong>、<strong>舆情题材主线</strong>与<strong>黄金跳空生命线</strong>，精准锁定涨停先锋
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2.5">
            {/* 快速搜索框 */}
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted" />
              <input
                type="text"
                placeholder="搜索标的 / 代码 / 题材…"
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                className="pl-8 pr-3 py-1.5 rounded-lg border border-border bg-elevated/80 text-xs text-foreground placeholder:text-muted focus:outline-none focus:border-accent w-36 md:w-48 transition-all"
              />
            </div>

            {/* AI 高开逻辑分析按钮 */}
            <button
              onClick={handleAiAnalyze}
              disabled={isAnalyzing || rows.length === 0}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-sky-500/40 bg-sky-500/10 text-sky-300 hover:bg-sky-500/20 text-xs font-semibold shadow-[0_0_12px_rgba(14,165,233,0.15)] transition-all cursor-pointer disabled:opacity-50"
            >
              <Sparkles className={cn('h-3.5 w-3.5 text-sky-400', isAnalyzing && 'animate-spin')} />
              <span>{isAnalyzing ? 'AI 解读中…' : 'AI 逻辑分析'}</span>
            </button>

            {/* 手动刷新 */}
            <button
              onClick={() => refetch()}
              disabled={isFetching}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-border bg-elevated hover:bg-elevated/80 text-xs font-medium text-secondary transition-colors cursor-pointer disabled:opacity-50"
            >
              <RefreshCw className={cn('h-3.5 w-3.5', isFetching && 'animate-spin')} />
              <span>刷新</span>
            </button>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6 pt-5 space-y-5">
        {/* 🤖 9:25 晨会 AI 竞价推演核心推荐 (Top 5 核心先锋) */}
        <div className="rounded-2xl border border-amber-500/30 bg-gradient-to-b from-surface via-surface/95 to-surface/80 p-5 shadow-[0_4px_25px_rgba(245,158,11,0.06)] relative overflow-hidden backdrop-blur-md">
          {/* 背景光晕装饰 */}
          <div className="absolute -top-12 -right-12 w-64 h-64 bg-amber-500/10 rounded-full blur-3xl pointer-events-none" />
          <div className="absolute -bottom-12 -left-12 w-64 h-64 bg-orange-500/5 rounded-full blur-3xl pointer-events-none" />

          {/* 顶栏标题与自动调度状态 */}
          <div className="relative flex flex-col md:flex-row md:items-center justify-between gap-3 border-b border-border/70 pb-4 mb-4">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-amber-500 to-orange-600 text-white shadow-[0_0_20px_rgba(245,158,11,0.35)] shrink-0">
                <Bot className="h-5 w-5" />
              </div>
              <div>
                <div className="flex items-center gap-2 flex-wrap">
                  <h2 className="text-base font-bold text-foreground">
                    🤖 今日 9:25 竞价抢筹 · AI 核心推荐五只票
                  </h2>
                  <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/40">
                    Top 5 核心先锋龙头
                  </span>
                  {latestSnatch?.updated_at && (
                    <span className="text-[11px] text-muted font-mono">
                      更新于 {latestSnatch.updated_at}
                    </span>
                  )}
                </div>
                <p className="text-xs text-muted mt-0.5">
                  结合<strong>市场博弈温度</strong>、<strong>为何今日高开</strong>、<strong>高开会涨停吗</strong>、<strong>近5日资金流向</strong>与<strong>主力意图定性(防诱多)</strong>深度严选
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2.5">
              <div className="hidden lg:flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-base/80 border border-border text-[11px] text-muted shadow-inner">
                <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
                <span>⏰ 交易日 09:25:20 全自动调度执行</span>
              </div>
              <button
                onClick={handleTriggerAutoSnatch}
                disabled={isTriggeringAuto}
                className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg border border-amber-500/50 bg-amber-500/20 hover:bg-amber-500/30 text-amber-300 text-xs font-bold shadow-[0_0_12px_rgba(245,158,11,0.2)] transition-all cursor-pointer disabled:opacity-50"
              >
                <RefreshCw className={cn('h-3.5 w-3.5 text-amber-400', isTriggeringAuto && 'animate-spin')} />
                <span>{isTriggeringAuto ? '深度推演中...' : '重新研判'}</span>
              </button>
            </div>
          </div>

          {/* 全市场博弈温度与大盘情绪摘要 */}
          {latestSnatch?.market_sentiment_summary && (
            <div className="mb-4 flex flex-col md:flex-row md:items-center justify-between gap-3 p-3.5 rounded-xl bg-elevated/50 border border-border/80 text-xs shadow-inner">
              <div className="flex items-start md:items-center gap-2.5">
                <div className="flex h-6 w-6 items-center justify-center rounded-lg bg-orange-500/20 text-orange-400 shrink-0 mt-0.5 md:mt-0">
                  <Flame className="h-3.5 w-3.5" />
                </div>
                <div className="text-secondary leading-relaxed">
                  <span className="font-bold text-foreground mr-1.5">
                    全市场博弈温度：{latestSnatch.market_temperature?.toFixed(1) || '62.8'}° (
                    {latestSnatch.market_zone === 'fear'
                      ? '极寒恐慌'
                      : latestSnatch.market_zone === 'crowded' || latestSnatch.market_zone === 'hot'
                      ? '偏热/微拥挤'
                      : '温和平衡'}
                    )
                  </span>
                  <span>{latestSnatch.market_sentiment_summary}</span>
                </div>
              </div>
            </div>
          )}

          {/* 诱多出货高危防坑提示 (Trap Warnings) */}
          {latestSnatch?.trap_warnings && latestSnatch.trap_warnings.length > 0 && (
            <div className="mb-4 p-3.5 rounded-xl bg-red-500/10 border border-red-500/30 text-xs shadow-inner">
              <div className="flex items-center gap-2 font-bold mb-2 text-red-400">
                <ShieldAlert className="h-4 w-4 shrink-0" />
                <span>散户避坑指南 · 主力借假高开诱多出货高危特征警示</span>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-[11px] text-red-200/90 leading-relaxed">
                {latestSnatch.trap_warnings.map((tw, idx) => (
                  <div key={idx} className="flex items-start gap-1.5">
                    <span className="text-red-400 shrink-0">•</span>
                    <span>{tw}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Top 5 核心先锋推荐卡片列表 */}
          {latestSnatch?.core_five_stocks && latestSnatch.core_five_stocks.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-3.5">
              {latestSnatch.core_five_stocks.map((stock: AICoreStockItem, idx: number) => {
                const isTrap = stock.main_intent?.includes('诱多')
                const rankLabels = ['🥇 核心先锋 1', '🥈 核心先锋 2', '🥉 核心先锋 3', '⭐ 核心先锋 4', '⭐ 核心先锋 5']
                const rankBorders = [
                  'border-amber-500/50 hover:border-amber-400 bg-gradient-to-b from-amber-500/10 via-surface to-surface shadow-[0_0_15px_rgba(245,158,11,0.08)]',
                  'border-sky-500/50 hover:border-sky-400 bg-gradient-to-b from-sky-500/10 via-surface to-surface',
                  'border-purple-500/50 hover:border-purple-400 bg-gradient-to-b from-purple-500/10 via-surface to-surface',
                  'border-emerald-500/50 hover:border-emerald-400 bg-gradient-to-b from-emerald-500/10 via-surface to-surface',
                  'border-blue-500/50 hover:border-blue-400 bg-gradient-to-b from-blue-500/10 via-surface to-surface',
                ]

                return (
                  <div
                    key={stock.symbol}
                    onClick={() => openPreview(stock.symbol, stock.name)}
                    className={cn(
                      'flex flex-col justify-between p-3.5 rounded-xl border bg-surface transition-all cursor-pointer group hover:shadow-card relative overflow-hidden',
                      rankBorders[idx] || rankBorders[0]
                    )}
                  >
                    <div>
                      {/* 卡片头部 */}
                      <div className="flex items-center justify-between pb-2 border-b border-border/50">
                        <span className="px-2 py-0.5 rounded-md text-[10px] font-bold bg-black/40 text-foreground border border-border/80">
                          {rankLabels[idx]}
                        </span>
                        <div className="flex items-center gap-0.5 text-amber-400">
                          {Array.from({ length: stock.stars || 5 }).map((_, si) => (
                            <Star key={si} className="h-3 w-3 fill-amber-400" />
                          ))}
                        </div>
                      </div>

                      {/* 标的名称与竞价数据 */}
                      <div className="mt-2.5 flex items-baseline justify-between">
                        <div>
                          <div className="flex items-center gap-1.5">
                            <span className="text-base font-black text-foreground group-hover:text-primary transition-colors">
                              {stock.name}
                            </span>
                            <span className="text-[10px] px-1.5 py-0.2 rounded bg-base font-mono text-muted">
                              {stock.board}
                            </span>
                          </div>
                          <div className="text-[11px] font-mono text-muted mt-0.5">{stock.symbol}</div>
                        </div>
                        <div className="text-right">
                          <span className="text-xs font-mono font-black text-bull">
                            +{stock.open_gap_pct?.toFixed(2)}%
                          </span>
                          <span className="text-[10px] text-muted block font-mono">
                            竞价 ¥{(stock.bidding_amount_wan / 10000).toFixed(2)}亿
                          </span>
                        </div>
                      </div>

                      {/* 涨停封板概率与主力意图定性徽标 */}
                      <div className="mt-3 space-y-1.5">
                        <div className="flex items-center justify-between text-[11px]">
                          <span className="text-muted font-medium flex items-center gap-1">
                            <Zap className="h-3 w-3 text-amber-400" />
                            封板概率:
                          </span>
                          <strong className={cn('font-mono font-bold', stock.limit_up_prob >= 80 ? 'text-emerald-400' : 'text-amber-400')}>
                            {stock.limit_up_prob}%
                          </strong>
                        </div>
                        <div className="h-1.5 w-full rounded-full bg-base overflow-hidden">
                          <div
                            className={cn('h-full rounded-full transition-all', stock.limit_up_prob >= 80 ? 'bg-emerald-500' : 'bg-amber-500')}
                            style={{ width: `${Math.min(100, Math.max(10, stock.limit_up_prob))}%` }}
                          />
                        </div>
                        <div>
                          <span
                            className={cn(
                              'inline-block px-1.5 py-0.5 rounded text-[10px] font-bold border',
                              isTrap
                                ? 'bg-red-500/20 text-red-300 border-red-500/40'
                                : 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                            )}
                          >
                            {isTrap ? '🚨 警惕诱多出货' : '⚡ 主力持续看好蓄势'}
                          </span>
                        </div>
                      </div>

                      {/* 核心灵魂 4 问剖析 */}
                      <div className="mt-3 pt-2 border-t border-border/60 space-y-2 text-[11px] leading-relaxed">
                        <div>
                          <span className="text-muted font-bold block text-[10px] text-amber-400/90">
                            🎯 为何今日高开:
                          </span>
                          <p className="text-foreground/90 line-clamp-2 mt-0.5">{stock.gap_reason}</p>
                        </div>
                        <div>
                          <span className="text-muted font-bold block text-[10px] text-sky-400/90">
                            🚀 会涨停吗 (走势推演):
                          </span>
                          <p className="text-secondary line-clamp-2 mt-0.5">{stock.will_limit_up}</p>
                        </div>
                        <div>
                          <span className="text-muted font-bold block text-[10px] text-emerald-400/90">
                            💰 近5日资金流向:
                          </span>
                          <p className="text-secondary line-clamp-2 mt-0.5">{stock.capital_5d_flow}</p>
                        </div>
                      </div>
                    </div>

                    {/* 开盘应对实战指南 */}
                    <div className="mt-3 pt-2 border-t border-border/60 text-[10px] text-muted">
                      <span className="font-bold text-orange-400 block mb-0.5">🛡️ 9:30 实战策略:</span>
                      <p className="line-clamp-2 text-foreground/80">{stock.open_tactics}</p>
                    </div>
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="py-8 text-center text-xs text-muted">
              暂无已生成的 9:25 竞价 AI 推演，可点击右上角「重新研判」立即启动！
            </div>
          )}
        </div>

        {/* 核心快捷形态过滤与排序栏 */}
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border bg-surface p-3 shadow-sm">
          {/* 左侧形态 Tab */}
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-xs text-muted mr-1 font-medium">🎯 焦点筛选:</span>
            {[
              { id: 'all', label: '全部标的', count: data?.total || 0 },
              { id: 'top_elite', label: '👑 胜率 68%+ 先锋精选', count: top5List.length, highlight: true },
              { id: '5d_lowest_doji', label: '⭐ 5日地量起爆星', count: lowest5dDojiCount, highlight: true },
              { id: 'game_fear', label: '🥶 散户恐惧区 (好位置)', count: fearCount, highlight: true },
              { id: 'announcement', label: '📢 公告利好驱动', count: announcementCount },
              { id: 'catalyst', label: '🔥 舆情题材共振', count: catalystCount },
              { id: 'earnings', label: '📈 业绩扭亏/预增', count: earningsCount },
              { id: 'gap_jump', label: '🚀 爆量跳空高开', count: gapJumpCount },
              { id: 'core_purple', label: '🔹 核心强势抢筹', count: stats?.core_purple_count || 0 },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setFilterTab(tab.id as FilterTab)}
                className={cn(
                  'flex items-center gap-1 px-3 py-1 rounded-lg text-xs font-semibold transition-all cursor-pointer',
                  filterTab === tab.id
                    ? tab.highlight
                      ? 'bg-gradient-to-r from-orange-500 to-red-500 text-white shadow-[0_0_12px_rgba(249,115,22,0.35)]'
                      : 'bg-accent text-white shadow-sm'
                    : 'bg-elevated/60 text-secondary hover:text-foreground hover:bg-elevated'
                )}
              >
                <span>{tab.label}</span>
                <span className="text-[10px] opacity-80 font-mono">({tab.count})</span>
              </button>
            ))}
          </div>

          {/* 右侧排序方式 */}
          <div className="flex items-center gap-1.5 text-xs text-muted">
            <span>排序:</span>
            {[
              { id: 'score', label: '综合评分' },
              { id: 'gap', label: '高开幅度' },
              { id: 'vol_ratio', label: '量比放大' },
              { id: 'amount', label: '竞价金额' },
            ].map((s) => (
              <button
                key={s.id}
                onClick={() => setSortBy(s.id as any)}
                className={cn(
                  'px-2 py-0.5 rounded text-[11px] font-medium transition-colors cursor-pointer',
                  sortBy === s.id
                    ? 'bg-accent/20 text-accent border border-accent/40 font-bold'
                    : 'bg-elevated text-secondary hover:text-foreground'
                )}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>

        {/* 筛选参数控制条（含多因子胜率开关） */}
        <div className="rounded-xl border border-border bg-surface p-3 shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-3 text-xs">
          <div className="flex items-center flex-wrap gap-2.5">
            {/* 交易日选择 */}
            <div className="flex items-center gap-1.5 bg-elevated/70 px-2.5 py-1 rounded-lg border border-border text-secondary">
              <Calendar className="h-3.5 w-3.5 text-muted" />
              <span>交易日:</span>
              <input
                type="date"
                value={asOf || data?.as_of || ''}
                onChange={(e) => setAsOf(e.target.value)}
                className="bg-transparent text-foreground focus:outline-none font-mono"
              />
              {asOf && (
                <button
                  onClick={() => setAsOf('')}
                  className="text-[10px] text-accent hover:underline ml-1 cursor-pointer"
                >
                  重置
                </button>
              )}
            </div>

            {/* 胜率 65%+ 开关 */}
            <button
              onClick={() => setOnlyHighWinrate(!onlyHighWinrate)}
              className={cn(
                'flex items-center gap-1 px-2.5 py-1 rounded-lg border transition-all cursor-pointer font-medium',
                onlyHighWinrate
                  ? 'bg-amber-500/20 text-amber-300 border-amber-500/40 shadow-sm'
                  : 'bg-elevated/60 text-secondary border-border hover:text-foreground'
              )}
            >
              <Award className="h-3.5 w-3.5 text-amber-400" />
              <span>仅看高胜率 Top 精选</span>
            </button>

            {/* 必须有公告/舆情催化开关 */}
            <button
              onClick={() => setRequireCatalyst(!requireCatalyst)}
              className={cn(
                'flex items-center gap-1 px-2.5 py-1 rounded-lg border transition-all cursor-pointer font-medium',
                requireCatalyst
                  ? 'bg-orange-500/20 text-orange-300 border-orange-500/40 shadow-sm'
                  : 'bg-elevated/60 text-secondary border-border hover:text-foreground'
              )}
            >
              <Megaphone className="h-3.5 w-3.5 text-orange-400" />
              <span>必须有公告/题材共振</span>
            </button>

            {/* 排除减持排雷开关 */}
            <button
              onClick={() => setExcludeBearAnnouncements(!excludeBearAnnouncements)}
              className={cn(
                'flex items-center gap-1 px-2.5 py-1 rounded-lg border transition-all cursor-pointer font-medium',
                excludeBearAnnouncements
                  ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40 shadow-sm'
                  : 'bg-elevated/60 text-secondary border-border hover:text-foreground'
              )}
            >
              <ShieldCheck className="h-3.5 w-3.5 text-emerald-400" />
              <span>已排除减持雷</span>
            </button>

            {/* 仅看业绩预增/扭亏开关 */}
            <button
              onClick={() => setRequireEarningsBull(!requireEarningsBull)}
              className={cn(
                'flex items-center gap-1 px-2.5 py-1 rounded-lg border transition-all cursor-pointer font-medium',
                requireEarningsBull
                  ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40 shadow-sm'
                  : 'bg-elevated/60 text-secondary border-border hover:text-foreground'
              )}
            >
              <TrendingUp className="h-3.5 w-3.5 text-emerald-400" />
              <span>仅看业绩预增/扭亏</span>
            </button>

            {/* 排除业绩预亏雷开关 */}
            <button
              onClick={() => setExcludeEarningsBear(!excludeEarningsBear)}
              className={cn(
                'flex items-center gap-1 px-2.5 py-1 rounded-lg border transition-all cursor-pointer font-medium',
                excludeEarningsBear
                  ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40 shadow-sm'
                  : 'bg-elevated/60 text-secondary border-border hover:text-foreground'
              )}
            >
              <ShieldCheck className="h-3.5 w-3.5 text-emerald-400" />
              <span>已排除业绩预亏</span>
            </button>

            {/* 仅看5日地量蓄势开关 */}
            <button
              onClick={() => setOnly5dLowest(!only5dLowest)}
              className={cn(
                'flex items-center gap-1 px-2.5 py-1 rounded-lg border transition-all cursor-pointer font-medium',
                only5dLowest
                  ? 'bg-amber-500/20 text-amber-300 border-amber-500/40 shadow-sm'
                  : 'bg-elevated/60 text-secondary border-border hover:text-foreground'
              )}
            >
              <Sparkles className="h-3.5 w-3.5 text-amber-400" />
              <span>仅看5日地量蓄势</span>
            </button>
          </div>

          <div className="flex items-center flex-wrap gap-2.5">
            {/* 高开阈值快选 */}
            <div className="flex items-center gap-1">
              <span className="text-muted">高开:</span>
              {[1.5, 2.0, 3.0, 4.0].map((gap) => (
                <button
                  key={gap}
                  onClick={() => setMinGapPct(gap)}
                  className={cn(
                    'px-2 py-0.5 rounded text-[11px] font-mono transition-colors cursor-pointer',
                    minGapPct === gap
                      ? 'bg-accent text-white font-bold'
                      : 'bg-elevated text-secondary hover:text-foreground'
                  )}
                >
                  &ge;{gap}%
                </button>
              ))}
            </div>

            {/* 板块勾选 */}
            <label className="flex items-center gap-1 text-secondary hover:text-foreground cursor-pointer select-none">
              <input
                type="checkbox"
                checked={includeChinext}
                onChange={(e) => setIncludeChinext(e.target.checked)}
                className="rounded accent-accent"
              />
              <span>创业板</span>
            </label>
            <label className="flex items-center gap-1 text-secondary hover:text-foreground cursor-pointer select-none">
              <input
                type="checkbox"
                checked={includeStar}
                onChange={(e) => setIncludeStar(e.target.checked)}
                className="rounded accent-accent"
              />
              <span>科创板</span>
            </label>
            <label className="flex items-center gap-1 text-secondary hover:text-foreground cursor-pointer select-none">
              <input
                type="checkbox"
                checked={onlyDoji}
                onChange={(e) => setOnlyDoji(e.target.checked)}
                className="rounded accent-accent"
              />
              <span>十字星</span>
            </label>

            {/* 市值区间 */}
            <div className="flex items-center gap-1 ml-1">
              <span className="text-muted">市值:</span>
              {[
                { label: '不限', min: 10, max: 500 },
                { label: '10~50亿', min: 10, max: 50 },
                { label: '10~200亿', min: 10, max: 200 },
              ].map((m) => (
                <button
                  key={m.label}
                  onClick={() => {
                    setMinMv(m.min)
                    setMaxMv(m.max)
                  }}
                  className={cn(
                    'px-1.5 py-0.5 rounded text-[10px] font-mono transition-colors cursor-pointer',
                    minMv === m.min && maxMv === m.max
                      ? 'bg-accent text-white font-bold'
                      : 'bg-elevated text-secondary hover:text-foreground'
                  )}
                >
                  {m.label}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* 顶部统计汇总卡片 */}
        {stats && (
          <div className="grid grid-cols-2 md:grid-cols-7 gap-3">
            <div className="p-3 rounded-xl border border-border bg-surface flex items-center gap-2.5">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-orange-500/10 text-orange-400 border border-orange-500/20">
                <Flame className="h-4 w-4" />
              </div>
              <div>
                <div className="text-[10px] text-muted">今日竞价标的</div>
                <div className="text-base font-bold font-mono text-foreground">{data?.total || 0} 只</div>
              </div>
            </div>

            <div className="p-3 rounded-xl border border-amber-500/30 bg-amber-500/[0.06] flex items-center gap-2.5">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-amber-500/20 text-amber-400 border border-amber-500/30">
                <Trophy className="h-4 w-4" />
              </div>
              <div>
                <div className="text-[10px] text-amber-400/90 font-medium">先锋高胜率标的</div>
                <div className="text-base font-bold font-mono text-amber-300">
                  {stats.five_star_count || top5List.length} 只
                </div>
              </div>
            </div>

            <div className="p-3 rounded-xl border border-red-500/30 bg-red-500/[0.06] flex items-center gap-2.5">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-red-500/20 text-red-400 border border-red-500/30">
                <Megaphone className="h-4 w-4" />
              </div>
              <div>
                <div className="text-[10px] text-red-400/90 font-medium">突发利好公告</div>
                <div className="text-base font-bold font-mono text-red-300">
                  {stats.announcement_count || 0} 只
                </div>
              </div>
            </div>

            <div className="p-3 rounded-xl border border-sky-500/30 bg-sky-500/[0.06] flex items-center gap-2.5">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-sky-500/20 text-sky-400 border border-sky-500/30">
                <Sparkles className="h-4 w-4" />
              </div>
              <div>
                <div className="text-[10px] text-sky-400/90 font-medium">主线题材共振</div>
                <div className="text-base font-bold font-mono text-sky-300">
                  {stats.catalyst_count || 0} 只
                </div>
              </div>
            </div>

            <div className="p-3 rounded-xl border border-emerald-500/30 bg-emerald-500/[0.06] flex items-center gap-2.5">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                <TrendingUp className="h-4 w-4" />
              </div>
              <div>
                <div className="text-[10px] text-emerald-400/90 font-medium">业绩扭亏/预增</div>
                <div className="text-base font-bold font-mono text-emerald-300">
                  {stats.earnings_bull_count || earningsCount} 只
                </div>
              </div>
            </div>

            <div className="p-3 rounded-xl border border-border bg-surface flex items-center gap-2.5">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-blue-500/10 text-blue-400 border border-blue-500/20">
                <TrendingUp className="h-4 w-4" />
              </div>
              <div>
                <div className="text-[10px] text-muted">平均高开幅度</div>
                <div className="text-base font-bold font-mono text-red-400">+{stats.avg_gap_pct}%</div>
              </div>
            </div>

            <div className="p-3 rounded-xl border border-border bg-surface flex items-center gap-2.5">
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                <Coins className="h-4 w-4" />
              </div>
              <div>
                <div className="text-[10px] text-muted">竞价成交总额</div>
                <div className="text-base font-bold font-mono text-foreground">
                  {stats.total_bidding_amount_yi} 亿元
                </div>
              </div>
            </div>
          </div>
        )}

        {/* 标的列表表格 */}
        <div className="rounded-xl border border-border bg-surface overflow-hidden shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-border bg-elevated/50 text-muted font-medium">
                  <th className="py-3 px-3 w-14 text-center">排名</th>
                  <th className="py-3 px-4">标的代码/名称</th>
                  <th className="py-3 px-4">核心催化与动因</th>
                  <th className="py-3 px-4 text-right">竞价开盘</th>
                  <th className="py-3 px-4 text-right">竞价高开</th>
                  <th className="py-3 px-4 text-right">竞价成交额</th>
                  <th className="py-3 px-4 text-right">竞价量比</th>
                  <th className="py-3 px-4">形态分类</th>
                  <th className="py-3 px-4 text-center">均线生命线</th>
                  <th className="py-3 px-4 text-center">多因子评分</th>
                  <th className="py-3 px-4 text-center">行情透视</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {rows.length === 0 ? (
                  <tr>
                    <td colSpan={11} className="text-center py-16 text-muted">
                      <div className="flex flex-col items-center gap-2">
                        <AlertCircle className="h-8 w-8 text-muted/60" />
                        <span>暂无符合多因子筛选条件的竞价标的</span>
                        <span className="text-[11px] text-muted/70">
                          可尝试降低高开门槛或取消「仅看高胜率 Top 精选」开关
                        </span>
                      </div>
                    </td>
                  </tr>
                ) : (
                  rows.map((r, idx) => (
                    <tr
                      key={r.symbol}
                      onClick={() => openPreview(r.symbol, r.name)}
                      className={cn(
                        'hover:bg-elevated/50 transition-colors cursor-pointer',
                        r.is_top3 ? 'bg-amber-500/[0.04]' : r.is_top5 ? 'bg-sky-500/[0.02]' : ''
                      )}
                    >
                        {/* 排名与星级 */}
                        <td className="py-3 px-3 text-center">
                          <div className="flex flex-col items-center">
                            <span
                              className={cn(
                                'font-mono font-bold text-xs',
                                idx === 0
                                  ? 'text-amber-400'
                                  : idx === 1
                                  ? 'text-sky-400'
                                  : idx === 2
                                  ? 'text-purple-400'
                                  : 'text-muted'
                              )}
                            >
                              #{idx + 1}
                            </span>
                            <span className="text-[10px] text-amber-400 font-mono mt-0.5">
                              {'★'.repeat(r.stars || 3)}
                            </span>
                          </div>
                        </td>

                        {/* 标的代码/名称 */}
                        <td className="py-3 px-4">
                          <div className="flex items-center gap-2">
                            <span className="font-bold text-foreground hover:text-primary transition-colors">
                              {r.name}
                            </span>
                            <span className="text-[10px] font-mono text-muted">{r.symbol}</span>
                            <span
                              className={cn(
                                'px-1.5 py-0.2 rounded text-[10px] font-medium border',
                                r.board === '创业板'
                                  ? 'bg-orange-500/10 text-orange-400 border-orange-500/25'
                                  : r.board === '科创板'
                                  ? 'bg-purple-500/10 text-purple-400 border-purple-500/25'
                                  : 'bg-elevated text-secondary border-border'
                              )}
                            >
                              {r.board}
                            </span>
                          </div>
                        </td>

                        {/* 核心催化与动因 */}
                        <td className="py-3 px-4">
                          <div className="flex items-center gap-1.5 flex-wrap max-w-xs">
                            {r.has_bull_announcement && (
                              <span
                                title={r.announcement_title || ''}
                                className="px-2 py-0.5 rounded text-[10px] font-medium bg-red-500/15 text-red-300 border border-red-500/25 truncate max-w-[180px]"
                              >
                                📢 {r.announcement_title || '利好公告'}
                              </span>
                            )}
                            {r.has_sentiment_catalyst && (
                              <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-orange-500/15 text-orange-300 border border-orange-500/25">
                                🔥 {r.sentiment_tag}
                              </span>
                            )}
                            {r.has_earnings_catalyst && (
                              <span
                                title={r.earnings_desc || ''}
                                className="px-2 py-0.5 rounded text-[10px] font-medium bg-emerald-500/15 text-emerald-300 border border-emerald-500/25 truncate max-w-[170px]"
                              >
                                📈 业绩{r.earnings_type}
                              </span>
                            )}
                            {r.has_inst_backing && (
                              <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-purple-500/15 text-purple-300 border border-purple-500/25">
                                🏛️ 机构潜伏
                              </span>
                            )}
                            {r.is_5d_lowest_vol && (
                              <span
                                title={`昨日极度缩量至5日最低量 (均量比例: ${Math.round((r.vol_shrink_ratio || 1) * 100)}%)`}
                                className="px-2 py-0.5 rounded text-[10px] font-medium bg-amber-500/15 text-amber-300 border border-amber-500/25 truncate"
                              >
                                ⭐ 5日地量
                              </span>
                            )}
                            {r.is_breakout_20d && (
                              <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-blue-500/15 text-blue-300 border border-blue-500/25">
                                🚀 平台突破
                              </span>
                            )}
                            {fearSet.has(r.symbol) && (
                              <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-cyan-500/15 text-cyan-300 border border-cyan-500/30">
                                🥶 散户恐惧区
                              </span>
                            )}
                            {dangerSet.has(r.symbol) && (
                              <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-rose-500/15 text-rose-300 border border-rose-500/30">
                                🔥 散户扎堆
                              </span>
                            )}
                            {!r.has_bull_announcement && !r.has_sentiment_catalyst && !r.has_earnings_catalyst && !r.is_5d_lowest_vol && (
                              <span className="text-[11px] text-muted truncate">
                                {r.catalyst_summary || r.pattern}
                              </span>
                            )}
                          </div>
                        </td>

                        {/* 竞价开盘 */}
                        <td className="py-3 px-4 text-right font-mono font-medium text-foreground">
                          ¥{r.open?.toFixed(2)}
                        </td>

                        {/* 竞价高开 */}
                        <td className="py-3 px-4 text-right font-mono font-bold text-bull">
                          +{r.open_gap_pct?.toFixed(2)}%
                        </td>

                        {/* 竞价成交额 */}
                        <td className="py-3 px-4 text-right font-mono text-foreground">
                          {r.bidding_amount_wan >= 10000
                            ? `${(r.bidding_amount_wan / 10000).toFixed(2)}亿`
                            : `${r.bidding_amount_wan?.toFixed(1)}万`}
                        </td>

                        {/* 竞价量比 */}
                        <td className="py-3 px-4 text-right font-mono text-muted">
                          {r.bidding_vol_ratio ? `${r.bidding_vol_ratio.toFixed(2)}` : '—'}
                        </td>

                        {/* 形态分类 */}
                        <td className="py-3 px-4">
                          <span
                            className={cn(
                              'px-2 py-0.5 rounded text-[10px] font-medium border',
                              r.is_core_purple
                                ? 'bg-purple-500/15 text-purple-300 border-purple-500/30'
                                : r.is_gap_jump
                                ? 'bg-orange-500/15 text-orange-300 border-orange-500/30'
                                : r.is_super_breakout
                                ? 'bg-amber-500/15 text-amber-300 border-amber-500/30'
                                : r.is_doji
                                ? 'bg-sky-500/15 text-sky-300 border-sky-500/30'
                                : 'bg-elevated text-secondary border-border'
                            )}
                          >
                            {r.pattern}
                          </span>
                        </td>

                        {/* 均线生命线 */}
                        <td className="py-3 px-4 text-center">
                          {r.above_ma20 ? (
                            <span className="px-2 py-0.5 rounded-full text-[10px] bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-medium">
                              🟢 站上MA20
                            </span>
                          ) : (
                            <span className="px-2 py-0.5 rounded-full text-[10px] bg-red-500/10 text-red-400 border border-red-500/20 font-medium">
                              🔴 破位MA20
                            </span>
                          )}
                        </td>

                        {/* 多因子评分 */}
                        <td className="py-3 px-4 text-center">
                          <div className="flex items-center justify-center gap-1.5">
                            <span className="font-mono font-bold text-xs text-orange-400">
                              {r.score}
                            </span>
                          </div>
                        </td>

                        {/* 操作透视 */}
                        <td className="py-3 px-4 text-center">
                          <button
                            onClick={(e) => {
                              e.stopPropagation()
                              openPreview(r.symbol, r.name)
                            }}
                            className="px-2.5 py-1 rounded bg-elevated/80 hover:bg-elevated text-[11px] text-foreground border border-border hover:border-primary/50 transition-all cursor-pointer"
                          >
                            K线透视
                          </button>
                        </td>
                      </tr>
                    ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* 股票 K 线弹窗预览 */}
      {previewSymbol && (
        <StockPreviewDialog
          symbol={previewSymbol}
          name={previewName}
          onClose={() => {
            setPreviewSymbol(null)
            setPreviewName(undefined)
          }}
        />
      )}

      {/* AI 逻辑解读弹窗 */}
      {showAiModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="w-full max-w-2xl max-h-[85vh] overflow-y-auto rounded-2xl bg-surface border border-border p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-border/60 pb-3">
              <div className="flex items-center gap-2">
                <Sparkles className="h-5 w-5 text-sky-400" />
                <h3 className="text-sm font-bold text-foreground">AI 集合竞价高开抢筹逻辑深度解读</h3>
              </div>
              <button
                onClick={() => setShowAiModal(false)}
                className="p-1 rounded-lg text-muted hover:text-foreground cursor-pointer"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            {isAnalyzing ? (
              <div className="py-12 flex flex-col items-center justify-center gap-2 text-muted">
                <RefreshCw className="h-6 w-6 animate-spin text-sky-400" />
                <span className="text-xs">正在调用 AI 大模型深度提炼竞价多因子催化逻辑…</span>
              </div>
            ) : aiAnalysis ? (
              <div className="space-y-3">
                <div className="p-3 rounded-xl bg-sky-500/10 border border-sky-500/20 text-xs leading-relaxed text-sky-200">
                  {aiAnalysis.market_summary}
                </div>
                <div className="space-y-2">
                  {aiAnalysis.items.map((item) => (
                    <div
                      key={item.symbol}
                      className="p-3 rounded-lg bg-elevated/40 border border-border/60 space-y-1.5"
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-xs text-foreground">
                          {item.name} ({item.symbol})
                        </span>
                        <span className="px-2 py-0.5 rounded text-[10px] bg-primary/10 text-primary border border-primary/20 font-medium">
                          {item.logic_rating}
                        </span>
                      </div>
                      <div className="text-xs text-foreground font-medium flex items-center gap-1">
                        <span>🎯 原因:</span>
                        <span>{item.gap_reason}</span>
                      </div>
                      <p className="text-xs text-secondary leading-relaxed">{item.catalyst_detail}</p>
                      {item.tactics && (
                        <div className="text-[11px] text-amber-300/90 pt-1 border-t border-border/30">
                          💡 操作建议: {item.tactics}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="py-8 text-center text-xs text-muted">暂无解读数据</div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
