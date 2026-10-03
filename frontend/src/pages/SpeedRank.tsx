import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Search,
  RefreshCw,
  Star,
  Flame,
  Activity,
  Zap,
  TrendingUp,
  Clock,
  Filter,
} from 'lucide-react'
import { motion } from 'framer-motion'
import { api } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { cn } from '@/lib/cn'
import { StockPreviewDialog } from '@/components/StockPreviewDialog'

type SortField = 'speed_5m' | 'speed' | 'change_pct'
type BoardFilter = 'all' | 'main' | 'chinext' | 'star'

export function SpeedRank() {
  const [sortBy, setSortBy] = useState<SortField>('speed_5m')
  const [boardFilter, setBoardFilter] = useState<BoardFilter>('all')
  const [excludeST, setExcludeST] = useState(true)
  const [keyword, setKeyword] = useState('')
  const [previewSymbol, setPreviewSymbol] = useState<string | null>(null)
  const [previewName, setPreviewName] = useState<string | undefined>(undefined)

  const qc = useQueryClient()

  // 自选股列表查询
  const watchlistQuery = useQuery({
    queryKey: QK.watchlist,
    queryFn: api.watchlistList,
  })
  const watchlistSet = useMemo(() => {
    const set = new Set<string>()
    for (const item of watchlistQuery.data?.symbols ?? []) {
      set.add(item.symbol)
    }
    return set
  }, [watchlistQuery.data])

  // 自选股添加/删除
  const toggleWatchlistMutation = useMutation({
    mutationFn: async (symbol: string) => {
      if (watchlistSet.has(symbol)) {
        await api.watchlistRemove(symbol)
      } else {
        await api.watchlistAdd(symbol, '', '默认')
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: QK.watchlist })
    },
  })

  // 涨速数据查询（每 15 秒轮询）
  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: QK.speedRank(sortBy),
    queryFn: () => api.speedRankTop50({ limit: 50, sort_by: sortBy }),
    refetchInterval: 15000,
    refetchIntervalInBackground: false,
  })

  const rows = useMemo(() => {
    const raw = data?.rows || []
    return raw.filter((r) => {
      // 过滤北交所
      if (
        r.symbol.endsWith('.BJ') ||
        r.symbol.startsWith('920') ||
        r.symbol.startsWith('430') ||
        r.symbol.startsWith('830') ||
        r.symbol.startsWith('870')
      ) {
        return false
      }

      // 排除 ST
      if (excludeST && (r.name.includes('ST') || r.name.includes('*ST'))) {
        return false
      }

      // 板块过滤
      if (boardFilter === 'main') {
        const code = r.symbol.slice(0, 6)
        if (code.startsWith('300') || code.startsWith('301') || code.startsWith('688')) {
          return false
        }
      } else if (boardFilter === 'chinext') {
        const code = r.symbol.slice(0, 6)
        if (!code.startsWith('300') && !code.startsWith('301')) {
          return false
        }
      } else if (boardFilter === 'star') {
        const code = r.symbol.slice(0, 6)
        if (!code.startsWith('688')) {
          return false
        }
      }

      // 关键词搜索
      if (keyword.trim()) {
        const kw = keyword.trim().toLowerCase()
        const matchName = r.name.toLowerCase().includes(kw)
        const matchSymbol = r.symbol.toLowerCase().includes(kw)
        const matchInd = (r.industry || '').toLowerCase().includes(kw)
        if (!matchName && !matchSymbol && !matchInd) return false
      }

      return true
    })
  }, [data?.rows, excludeST, boardFilter, keyword])

  // 统计概览
  const stats = useMemo(() => {
    const rawRows = data?.rows || []
    if (rawRows.length === 0) return null

    const top1 = rawRows[0]
    const avg5m = rawRows.reduce((acc, cur) => acc + (cur.speed_5m || 0), 0) / rawRows.length
    const max5m = Math.max(...rawRows.map((r) => r.speed_5m || 0))

    // 统计行业分布
    const indCount: Record<string, number> = {}
    for (const r of rawRows) {
      if (r.industry) {
        indCount[r.industry] = (indCount[r.industry] || 0) + 1
      }
    }
    const sortedInds = Object.entries(indCount).sort((a, b) => b[1] - a[1])
    const topIndustry = sortedInds.length > 0 ? `${sortedInds[0][0]} (${sortedInds[0][1]}只)` : '--'

    const highSpeedCount = rawRows.filter((r) => (r.speed_5m || 0) >= 2.0).length

    return {
      top1,
      avg5m,
      max5m,
      topIndustry,
      highSpeedCount,
    }
  }, [data?.rows])

  // 5m 涨速柱状图基准比例
  const maxSpeed5m = Math.max(stats?.max5m || 5, 2)

  // 格式化金额
  const formatAmount = (amt: number) => {
    if (!amt) return '--'
    if (amt >= 100000000) {
      return `${(amt / 100000000).toFixed(2)}亿`
    }
    if (amt >= 10000) {
      return `${(amt / 10000).toFixed(0)}万`
    }
    return amt.toFixed(0)
  }

  // 格式化市值
  const formatMv = (val: number) => {
    if (!val) return '--'
    if (val >= 100000000) {
      return `${(val / 100000000).toFixed(1)}亿`
    }
    return `${(val / 10000).toFixed(0)}万`
  }

  return (
    <div className="min-h-full bg-base text-foreground pb-16">
      {/* 顶部主横幅 */}
      <div className="sticky top-0 z-20 border-b border-border bg-surface/95 backdrop-blur-md px-6 py-4">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-red-500/20 via-orange-500/20 to-amber-500/20 border border-red-500/30 text-red-400 shadow-[0_0_15px_rgba(239,68,68,0.2)]">
              <Zap className="h-6 w-6 text-red-400" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-xl font-bold tracking-tight text-foreground bg-gradient-to-r from-foreground via-red-300 to-amber-300 bg-clip-text text-transparent">
                  五分钟涨速排行榜
                </h1>
                <span className="inline-flex items-center gap-1 rounded-full bg-red-500/15 border border-red-500/30 px-2.5 py-0.5 text-xs font-semibold text-red-300">
                  <Flame className="h-3.5 w-3.5 text-red-400 animate-pulse" />
                  智兔数服·实时Top 50
                </span>
              </div>
              <p className="text-xs text-muted mt-0.5 flex items-center gap-2">
                <span>实时扫描全市场 5000+ 标的微秒级异动 · 捕捉点火拉升与资金抢筹第一浪</span>
                {data?.as_of && (
                  <span className="inline-flex items-center gap-1 text-muted/80 font-mono">
                    <Clock className="h-3 w-3" />
                    {data.as_of}
                  </span>
                )}
              </p>
            </div>
          </div>

          {/* 顶部统计卡片 & 操作 */}
          <div className="flex flex-wrap items-center gap-3">
            {stats && (
              <>
                <div className="rounded-xl border border-border/80 bg-elevated/60 px-3.5 py-1.5 shadow-sm">
                  <div className="text-[11px] text-muted">涨速榜首</div>
                  <div className="font-mono text-sm font-bold text-red-400 flex items-center gap-1.5">
                    <span>{stats.top1.name}</span>
                    <span className="text-xs text-red-300">+{stats.top1.speed_5m.toFixed(2)}%</span>
                  </div>
                </div>
                <div className="rounded-xl border border-border/80 bg-elevated/60 px-3.5 py-1.5 shadow-sm">
                  <div className="text-[11px] text-muted">平均5m涨速</div>
                  <div className="font-mono text-base font-bold text-amber-400">
                    +{stats.avg5m.toFixed(2)}%
                  </div>
                </div>
                <div className="rounded-xl border border-border/80 bg-elevated/60 px-3.5 py-1.5 shadow-sm">
                  <div className="text-[11px] text-muted">急拉标的(≥2%)</div>
                  <div className="font-mono text-base font-bold text-orange-400">
                    {stats.highSpeedCount} 只
                  </div>
                </div>
                <div className="rounded-xl border border-border/80 bg-elevated/60 px-3.5 py-1.5 shadow-sm hidden lg:block">
                  <div className="text-[11px] text-muted">活跃行业集聚</div>
                  <div className="text-sm font-semibold text-sky-400 truncate max-w-[120px]">
                    {stats.topIndustry}
                  </div>
                </div>
              </>
            )}

            <button
              onClick={() => refetch()}
              disabled={isFetching}
              className="flex items-center gap-1.5 rounded-xl border border-border bg-surface px-3 py-2 text-xs font-medium text-foreground hover:bg-elevated transition-colors shadow-sm"
              title="立即刷新"
            >
              <RefreshCw className={cn('h-3.5 w-3.5', isFetching && 'animate-spin text-red-400')} />
              <span>刷新</span>
            </button>
          </div>
        </div>
      </div>

      {/* 主体内容 */}
      <div className="max-w-7xl mx-auto px-6 py-6 space-y-6">
        {/* 筛选与排序控制条 */}
        <div className="rounded-2xl border border-border bg-surface/60 p-4 shadow-sm backdrop-blur-sm space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex flex-wrap items-center gap-4">
              {/* 排序维度 */}
              <div className="flex items-center gap-2 text-xs text-muted">
                <span className="font-medium">排序维度：</span>
                <div className="inline-flex rounded-lg border border-border bg-elevated/60 p-0.5">
                  <button
                    onClick={() => setSortBy('speed_5m')}
                    className={cn(
                      'px-3 py-1 rounded-md text-xs font-medium transition-all flex items-center gap-1',
                      sortBy === 'speed_5m'
                        ? 'bg-red-500 text-white shadow-[0_0_12px_rgba(239,68,68,0.4)]'
                        : 'text-muted hover:text-foreground'
                    )}
                  >
                    <Flame className="h-3 w-3" />
                    5分钟涨速
                  </button>
                  <button
                    onClick={() => setSortBy('speed')}
                    className={cn(
                      'px-3 py-1 rounded-md text-xs font-medium transition-all flex items-center gap-1',
                      sortBy === 'speed'
                        ? 'bg-red-500 text-white shadow-[0_0_12px_rgba(239,68,68,0.4)]'
                        : 'text-muted hover:text-foreground'
                    )}
                  >
                    <Activity className="h-3 w-3" />
                    即时涨速
                  </button>
                  <button
                    onClick={() => setSortBy('change_pct')}
                    className={cn(
                      'px-3 py-1 rounded-md text-xs font-medium transition-all flex items-center gap-1',
                      sortBy === 'change_pct'
                        ? 'bg-red-500 text-white shadow-[0_0_12px_rgba(239,68,68,0.4)]'
                        : 'text-muted hover:text-foreground'
                    )}
                  >
                    <TrendingUp className="h-3 w-3" />
                    当日涨幅
                  </button>
                </div>
              </div>

              {/* 板块筛选 */}
              <div className="flex items-center gap-2 text-xs text-muted">
                <span className="font-medium">板块：</span>
                <div className="inline-flex rounded-lg border border-border bg-elevated/60 p-0.5">
                  {[
                    { id: 'all', label: '全部' },
                    { id: 'main', label: '主板' },
                    { id: 'chinext', label: '创业板' },
                    { id: 'star', label: '科创板' },
                  ].map((item) => (
                    <button
                      key={item.id}
                      onClick={() => setBoardFilter(item.id as BoardFilter)}
                      className={cn(
                        'px-2.5 py-1 rounded-md text-xs transition-all',
                        boardFilter === item.id
                          ? 'bg-surface font-semibold text-foreground shadow-sm'
                          : 'text-muted hover:text-foreground'
                      )}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* 过滤 ST */}
              <label className="flex items-center gap-1.5 text-xs text-muted cursor-pointer hover:text-foreground select-none">
                <input
                  type="checkbox"
                  checked={excludeST}
                  onChange={(e) => setExcludeST(e.target.checked)}
                  className="rounded border-border text-red-500 focus:ring-red-500/20"
                />
                <span>排除 ST / *ST</span>
              </label>
            </div>

            {/* 搜索框 */}
            <div className="relative w-full sm:w-64">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted" />
              <input
                type="text"
                placeholder="搜索名称 / 代码 / 行业..."
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                className="w-full rounded-xl border border-border bg-elevated/80 pl-9 pr-3 py-1.5 text-xs text-foreground placeholder:text-muted/60 focus:border-red-500/50 focus:outline-none focus:ring-2 focus:ring-red-500/20 transition-all"
              />
            </div>
          </div>
        </div>

        {/* 核心榜单表格 */}
        <div className="rounded-2xl border border-border bg-surface/70 shadow-sm overflow-hidden backdrop-blur-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="border-b border-border/80 bg-elevated/50 text-[11px] text-muted uppercase tracking-wider font-mono">
                  <th className="py-3 px-4 w-14 text-center">排名</th>
                  <th className="py-3 px-4">标的名称 / 代码</th>
                  <th className="py-3 px-4">所属行业</th>
                  <th className="py-3 px-4 min-w-[180px]">
                    <div className="flex items-center gap-1 text-red-400 font-bold">
                      <Flame className="h-3.5 w-3.5" />
                      <span>5分钟涨速</span>
                    </div>
                  </th>
                  <th className="py-3 px-4 text-right">即时涨速</th>
                  <th className="py-3 px-4 text-right">现价</th>
                  <th className="py-3 px-4 text-right">当日涨跌幅</th>
                  <th className="py-3 px-4 text-right">量比</th>
                  <th className="py-3 px-4 text-right">换手率</th>
                  <th className="py-3 px-4 text-right">成交额</th>
                  <th className="py-3 px-4 text-right">流通市值</th>
                  <th className="py-3 px-4 text-center w-24">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/40 font-mono">
                {isLoading && rows.length === 0 ? (
                  <tr>
                    <td colSpan={12} className="py-20 text-center text-muted">
                      <div className="flex flex-col items-center justify-center gap-3">
                        <RefreshCw className="h-6 w-6 animate-spin text-red-400" />
                        <span className="text-xs">正在从智兔数服拉取全市场实时涨速数据...</span>
                      </div>
                    </td>
                  </tr>
                ) : rows.length === 0 ? (
                  <tr>
                    <td colSpan={12} className="py-20 text-center text-muted">
                      <div className="flex flex-col items-center justify-center gap-2">
                        <Filter className="h-8 w-8 text-muted/40" />
                        <span className="text-sm font-medium">无匹配的股票数据</span>
                        <span className="text-xs text-muted/70">尝试调整筛选条件或搜索关键词</span>
                      </div>
                    </td>
                  </tr>
                ) : (
                  rows.map((r, idx) => {
                    const rank = idx + 1
                    const isTop3 = rank <= 3
                    const inWatchlist = watchlistSet.has(r.symbol)
                    const speed5m = r.speed_5m || 0
                    const barWidthPct = Math.min(100, Math.max(5, (speed5m / maxSpeed5m) * 100))
                    const isWin = r.change_pct > 0

                    return (
                      <tr
                        key={r.symbol}
                        onClick={() => {
                          setPreviewSymbol(r.symbol)
                          setPreviewName(r.name)
                        }}
                        className="hover:bg-elevated/60 transition-colors cursor-pointer group"
                      >
                        {/* 排名 */}
                        <td className="py-3.5 px-4 text-center">
                          {isTop3 ? (
                            <div
                              className={cn(
                                'inline-flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold shadow-sm',
                                rank === 1 &&
                                  'bg-gradient-to-br from-amber-300 to-yellow-500 text-yellow-950 shadow-[0_0_10px_rgba(234,179,8,0.4)]',
                                rank === 2 &&
                                  'bg-gradient-to-br from-slate-200 to-slate-400 text-slate-900 shadow-[0_0_8px_rgba(148,163,184,0.3)]',
                                rank === 3 &&
                                  'bg-gradient-to-br from-amber-600 to-amber-800 text-amber-100 shadow-[0_0_8px_rgba(217,119,6,0.3)]'
                              )}
                            >
                              {rank}
                            </div>
                          ) : (
                            <span className="text-muted text-xs font-medium">{rank}</span>
                          )}
                        </td>

                        {/* 标的 */}
                        <td className="py-3.5 px-4">
                          <div className="flex flex-col font-sans">
                            <span className="font-bold text-foreground text-sm group-hover:text-red-400 transition-colors flex items-center gap-1.5">
                              {r.name}
                              {r.name.includes('ST') && (
                                <span className="text-[10px] px-1 py-0.2 rounded bg-amber-500/20 text-amber-300 font-normal">
                                  ST
                                </span>
                              )}
                            </span>
                            <span className="text-[11px] text-muted font-mono">{r.symbol}</span>
                          </div>
                        </td>

                        {/* 所属行业 */}
                        <td className="py-3.5 px-4 font-sans">
                          {r.industry ? (
                            <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium bg-elevated border border-border/80 text-foreground/85">
                              {r.industry}
                            </span>
                          ) : (
                            <span className="text-muted text-[11px]">--</span>
                          )}
                        </td>

                        {/* 5分钟涨速 (带柱状微图) */}
                        <td className="py-3.5 px-4">
                          <div className="space-y-1.5">
                            <div className="flex items-center justify-between">
                              <span className="font-mono text-sm font-extrabold text-red-400">
                                +{speed5m.toFixed(2)}%
                              </span>
                              {speed5m >= 3.0 && (
                                <span className="inline-flex items-center gap-0.5 text-[10px] font-semibold text-red-400 bg-red-500/10 px-1.5 py-0.5 rounded border border-red-500/20 font-sans">
                                  <Zap className="h-2.5 w-2.5" />
                                  点火
                                </span>
                              )}
                            </div>
                            <div className="h-1.5 w-full bg-elevated/80 rounded-full overflow-hidden">
                              <motion.div
                                initial={{ width: 0 }}
                                animate={{ width: `${barWidthPct}%` }}
                                transition={{ duration: 0.4 }}
                                className={cn(
                                  'h-full rounded-full',
                                  speed5m >= 3.0
                                    ? 'bg-gradient-to-r from-orange-500 via-red-500 to-rose-500 shadow-[0_0_8px_rgba(239,68,68,0.5)]'
                                    : 'bg-gradient-to-r from-amber-500 to-red-500'
                                )}
                              />
                            </div>
                          </div>
                        </td>

                        {/* 即时涨速 */}
                        <td className="py-3.5 px-4 text-right">
                          <span
                            className={cn(
                              'font-bold',
                              r.speed > 0
                                ? 'text-red-400'
                                : r.speed < 0
                                ? 'text-green-400'
                                : 'text-muted'
                            )}
                          >
                            {r.speed > 0 ? '+' : ''}
                            {r.speed.toFixed(2)}%
                          </span>
                        </td>

                        {/* 现价 */}
                        <td className="py-3.5 px-4 text-right">
                          <span className="font-bold text-foreground text-sm">
                            ¥{r.price.toFixed(2)}
                          </span>
                        </td>

                        {/* 当日涨跌幅 */}
                        <td className="py-3.5 px-4 text-right">
                          <span
                            className={cn(
                              'inline-block px-2 py-0.5 rounded text-xs font-bold',
                              isWin
                                ? 'bg-red-500/10 text-red-400 border border-red-500/20'
                                : r.change_pct < 0
                                ? 'bg-green-500/10 text-green-400 border border-green-500/20'
                                : 'bg-elevated text-muted'
                            )}
                          >
                            {isWin ? '+' : ''}
                            {r.change_pct.toFixed(2)}%
                          </span>
                        </td>

                        {/* 量比 */}
                        <td className="py-3.5 px-4 text-right">
                          {r.volume_ratio ? (
                            <span
                              className={cn(
                                'font-bold',
                                r.volume_ratio >= 2.5
                                  ? 'text-orange-400'
                                  : r.volume_ratio >= 1.5
                                  ? 'text-amber-300'
                                  : 'text-foreground'
                              )}
                            >
                              {r.volume_ratio >= 2.5 && '🔥 '}
                              {r.volume_ratio.toFixed(2)}
                            </span>
                          ) : (
                            <span className="text-muted">--</span>
                          )}
                        </td>

                        {/* 换手率 */}
                        <td className="py-3.5 px-4 text-right">
                          <span className="text-foreground">
                            {r.turnover_rate ? `${r.turnover_rate.toFixed(2)}%` : '--'}
                          </span>
                        </td>

                        {/* 成交额 */}
                        <td className="py-3.5 px-4 text-right">
                          <span className="text-muted/90 font-medium">
                            {formatAmount(r.amount)}
                          </span>
                        </td>

                        {/* 流通市值 */}
                        <td className="py-3.5 px-4 text-right">
                          <span className="text-muted/80">{formatMv(r.float_mv)}</span>
                        </td>

                        {/* 操作 */}
                        <td
                          className="py-3.5 px-4 text-center"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <div className="flex items-center justify-center gap-1.5 font-sans">
                            <button
                              onClick={() => toggleWatchlistMutation.mutate(r.symbol)}
                              disabled={toggleWatchlistMutation.isPending}
                              title={inWatchlist ? '移出自选' : '加入自选'}
                              className={cn(
                                'p-1.5 rounded-lg border transition-all',
                                inWatchlist
                                  ? 'bg-amber-500/15 border-amber-500/30 text-amber-400 hover:bg-amber-500/25'
                                  : 'bg-elevated/60 border-border text-muted hover:text-amber-400 hover:border-amber-500/30'
                              )}
                            >
                              <Star
                                className={cn('h-3.5 w-3.5', inWatchlist && 'fill-amber-400')}
                              />
                            </button>
                            <button
                              onClick={() => {
                                setPreviewSymbol(r.symbol)
                                setPreviewName(r.name)
                              }}
                              className="px-2 py-1 rounded-lg text-xs font-medium text-sky-400 hover:text-sky-300 hover:bg-sky-500/10 transition-colors"
                            >
                              分时/K线
                            </button>
                          </div>
                        </td>
                      </tr>
                    )
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* 分时图与K线弹窗 */}
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
    </div>
  )
}
