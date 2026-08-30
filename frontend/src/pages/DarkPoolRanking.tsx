import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Search,
  RefreshCw,
  Star,
  EyeOff,
  Sparkles,
} from 'lucide-react'
import { motion } from 'framer-motion'
import { api, type DarkpoolRankingRow } from '@/lib/api'
import { cn } from '@/lib/cn'
import { StockPreviewDialog } from '@/components/StockPreviewDialog'

export function DarkPoolRanking() {
  const [asOf] = useState('')
  const [minInflow, setMinInflow] = useState(500)
  const [sortBy, setSortBy] = useState<'inflow' | 'dai_score' | 'inst_position' | 'amount'>('inflow')
  const [limit] = useState(50)
  const [keyword, setKeyword] = useState('')
  const [previewSymbol, setPreviewSymbol] = useState<string | null>(null)

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ['darkpool-ranking', asOf, minInflow, sortBy, limit],
    queryFn: () =>
      api.darkpoolRanking({
        as_of: asOf || undefined,
        min_inflow: minInflow,
        sort_by: sortBy,
        limit: limit,
      }),
    refetchInterval: 30000,
  })

  const rows = (data?.rows || []).filter((r: DarkpoolRankingRow) => {
    // 严格过滤北交所标的
    if (
      r.symbol.endsWith('.BJ') ||
      r.symbol.startsWith('920') ||
      r.symbol.startsWith('430') ||
      r.symbol.startsWith('830') ||
      r.symbol.startsWith('870')
    ) {
      return false
    }
    if (!keyword) return true
    const kw = keyword.toLowerCase()
    return r.name.toLowerCase().includes(kw) || r.symbol.toLowerCase().includes(kw)
  })

  const stats = data?.stats
  const maxInflow = Math.max(...(data?.rows || []).map((r) => r.dark_inflow_wan), 1000)

  return (
    <div className="min-h-full bg-base text-foreground pb-16">
      {/* 顶部主横幅 */}
      <div className="sticky top-0 z-20 border-b border-border bg-surface/95 backdrop-blur-md px-6 py-4">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br from-sky-500/20 via-pink-500/20 to-red-500/20 border border-sky-500/30 text-sky-400 shadow-[0_0_15px_rgba(14, 165, 233, 0.2)]">
              <EyeOff className="h-6 w-6 text-sky-400" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-xl font-bold tracking-tight text-foreground bg-gradient-to-r from-foreground via-sky-300 to-sky-400 bg-clip-text text-transparent">
                  全市场暗盘资金流入排行榜
                </h1>
                <span className="inline-flex items-center gap-1 rounded-full bg-sky-500/15 border border-sky-500/30 px-2 py-0.5 text-xs font-semibold text-sky-300">
                  <Sparkles className="h-3 w-3" />
                  冰山拆单·假跌真买探测
                </span>
              </div>
              <p className="text-xs text-muted mt-0.5">
                实时解构全市场 Level-2 隐形吸筹、冰山大单吞筹与地量锁仓信号 · 捕捉主升起爆先兆
              </p>
            </div>
          </div>

          {/* 顶部统计卡片 */}
          <div className="flex items-center gap-3">
            <div className="rounded-xl border border-border/80 bg-elevated/60 px-3.5 py-1.5 shadow-sm">
              <div className="text-[11px] text-muted">全市场暗盘净流入</div>
              <div className="font-mono text-base font-bold text-red-400">
                +{stats?.total_dark_inflow_yi ? stats.total_dark_inflow_yi.toFixed(2) : '--'} 亿元
              </div>
            </div>
            <div className="rounded-xl border border-border/80 bg-elevated/60 px-3.5 py-1.5 shadow-sm">
              <div className="text-[11px] text-muted">主力高控盘标的</div>
              <div className="font-mono text-base font-bold text-sky-400">
                {stats?.heavy_control_count ?? '--'} 支
              </div>
            </div>
            <div className="rounded-xl border border-border/80 bg-elevated/60 px-3.5 py-1.5 shadow-sm">
              <div className="text-[11px] text-muted">平均吸筹强度</div>
              <div className="font-mono text-base font-bold text-amber-400">
                {stats?.avg_dai_score ? stats.avg_dai_score.toFixed(1) : '--'} 分
              </div>
            </div>
            <button
              onClick={() => refetch()}
              disabled={isFetching}
              className="flex items-center gap-1.5 rounded-xl border border-border bg-surface px-3 py-2 text-xs font-medium text-foreground hover:bg-elevated transition-colors"
            >
              <RefreshCw className={cn('h-3.5 w-3.5', isFetching && 'animate-spin text-sky-400')} />
              刷新
            </button>
          </div>
        </div>
      </div>

      {/* 主体内容 */}
      <div className="max-w-7xl mx-auto px-6 py-6 space-y-6">
        {/* 筛选与排序控制条 */}
        <div className="rounded-2xl border border-border bg-surface/60 p-4 shadow-sm backdrop-blur-sm space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex flex-wrap items-center gap-3">
              <div className="flex items-center gap-2 text-xs text-muted">
                <span>排序维度：</span>
                <div className="inline-flex rounded-lg border border-border bg-elevated/60 p-0.5">
                  <button
                    onClick={() => setSortBy('inflow')}
                    className={cn(
                      'px-2.5 py-1 rounded-md text-xs font-medium transition-all',
                      sortBy === 'inflow' ? 'bg-sky-600 text-white shadow-sm' : 'text-muted hover:text-foreground'
                    )}
                  >
                    💰 暗盘净流入
                  </button>
                  <button
                    onClick={() => setSortBy('dai_score')}
                    className={cn(
                      'px-2.5 py-1 rounded-md text-xs font-medium transition-all',
                      sortBy === 'dai_score' ? 'bg-sky-600 text-white shadow-sm' : 'text-muted hover:text-foreground'
                    )}
                  >
                    🎯 吸筹强度 (DAI)
                  </button>
                  <button
                    onClick={() => setSortBy('inst_position')}
                    className={cn(
                      'px-2.5 py-1 rounded-md text-xs font-medium transition-all',
                      sortBy === 'inst_position' ? 'bg-sky-600 text-white shadow-sm' : 'text-muted hover:text-foreground'
                    )}
                  >
                    🛡️ 主力资金仓位
                  </button>
                  <button
                    onClick={() => setSortBy('amount')}
                    className={cn(
                      'px-2.5 py-1 rounded-md text-xs font-medium transition-all',
                      sortBy === 'amount' ? 'bg-sky-600 text-white shadow-sm' : 'text-muted hover:text-foreground'
                    )}
                  >
                    📊 成交额
                  </button>
                </div>
              </div>

              <div className="flex items-center gap-2 text-xs text-muted">
                <span>最低暗盘流入：</span>
                <div className="inline-flex rounded-lg border border-border bg-elevated/60 p-0.5">
                  {[300, 500, 1000, 3000].map((v) => (
                    <button
                      key={v}
                      onClick={() => setMinInflow(v)}
                      className={cn(
                        'px-2 py-1 rounded-md text-xs transition-all',
                        minInflow === v ? 'bg-sky-500/20 text-sky-300 font-semibold' : 'text-muted hover:text-foreground'
                      )}
                    >
                      {v >= 10000 ? `${v / 10000}亿` : `${v}万`}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* 搜索框 */}
            <div className="relative w-full sm:w-64">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted" />
              <input
                type="text"
                placeholder="搜索代码 / 名称..."
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                className="w-full rounded-xl border border-border bg-elevated/60 pl-8 pr-3 py-1.5 text-xs text-foreground placeholder:text-muted focus:outline-none focus:ring-1 focus:ring-sky-500"
              />
            </div>
          </div>
        </div>

        {/* 排行榜表格 */}
        <div className="rounded-2xl border border-border bg-surface overflow-hidden shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-border bg-elevated/50 text-muted font-medium">
                  <th className="py-3 px-4 w-12 text-center">#</th>
                  <th className="py-3 px-4">标的</th>
                  <th className="py-3 px-4 text-right">现价 / 涨幅</th>
                  <th className="py-3 px-4">暗盘资金净流入</th>
                  <th className="py-3 px-4 text-center">吸筹强度</th>
                  <th className="py-3 px-4 text-center">资金仓位</th>
                  <th className="py-3 px-4 text-center">机构活跃度</th>
                  <th className="py-3 px-4">暗盘特征标签</th>
                  <th className="py-3 px-4 text-center">次日潜力</th>
                  <th className="py-3 px-4 text-center">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/50 font-mono">
                {isLoading ? (
                  <tr>
                    <td colSpan={10} className="py-12 text-center text-muted">
                      <RefreshCw className="h-6 w-6 animate-spin mx-auto text-sky-400 mb-2" />
                      正在全市场实时解构暗盘资金...
                    </td>
                  </tr>
                ) : rows.length === 0 ? (
                  <tr>
                    <td colSpan={10} className="py-12 text-center text-muted">
                      未发现符合当前门槛的暗盘吸筹标的
                    </td>
                  </tr>
                ) : (
                  rows.map((r, idx) => {
                    const isWin = r.change_pct >= 0
                    const barWidthPct = Math.min(100, Math.max(5, (r.dark_inflow_wan / maxInflow) * 100))

                    return (
                      <tr
                        key={r.symbol}
                        onClick={() => setPreviewSymbol(r.symbol)}
                        className="hover:bg-elevated/50 transition-colors cursor-pointer group"
                      >
                        {/* 排名 */}
                        <td className="py-3 px-4 text-center">
                          {idx === 0 ? (
                            <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-amber-500 text-black font-bold text-[10px] shadow-sm">
                              1
                            </span>
                          ) : idx === 1 ? (
                            <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-slate-300 text-black font-bold text-[10px] shadow-sm">
                              2
                            </span>
                          ) : idx === 2 ? (
                            <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-amber-700 text-white font-bold text-[10px] shadow-sm">
                              3
                            </span>
                          ) : (
                            <span className="text-muted text-[11px]">{idx + 1}</span>
                          )}
                        </td>

                        {/* 标的 */}
                        <td className="py-3 px-4">
                          <div className="flex flex-col font-sans">
                            <span className="font-bold text-foreground group-hover:text-sky-400 transition-colors">
                              {r.name}
                            </span>
                            <span className="text-[11px] text-muted font-mono">{r.symbol}</span>
                          </div>
                        </td>

                        {/* 现价 / 涨幅 */}
                        <td className="py-3 px-4 text-right">
                          <div className="font-bold text-foreground">¥{r.close.toFixed(2)}</div>
                          <div className={cn('text-[11px] font-bold', isWin ? 'text-red-400' : 'text-green-400')}>
                            {isWin ? '+' : ''}
                            {r.change_pct.toFixed(2)}%
                          </div>
                        </td>

                        {/* 暗盘净流入 (带可视化进度条) */}
                        <td className="py-3 px-4">
                          <div className="w-48 space-y-1">
                            <div className="flex items-center justify-between text-[11px]">
                              <span className="font-bold text-red-400">+{r.dark_inflow_yi.toFixed(2)} 亿元</span>
                              <span className="text-muted text-[10px]">({r.dark_inflow_wan.toLocaleString()}万)</span>
                            </div>
                            <div className="h-1.5 w-full bg-elevated rounded-full overflow-hidden">
                              <motion.div
                                initial={{ width: 0 }}
                                animate={{ width: `${barWidthPct}%` }}
                                transition={{ duration: 0.5 }}
                                className="h-full bg-gradient-to-r from-sky-500 via-pink-500 to-red-500 rounded-full"
                              />
                            </div>
                          </div>
                        </td>

                        {/* 吸筹强度 (DAI) */}
                        <td className="py-3 px-4 text-center">
                          <span
                            className={cn(
                              'inline-flex items-center px-2 py-0.5 rounded-full text-xs font-bold font-mono',
                              r.dai_score >= 80
                                ? 'bg-sky-500/20 text-sky-300 border border-sky-500/30'
                                : r.dai_score >= 60
                                ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                                : 'bg-slate-500/20 text-slate-300'
                            )}
                          >
                            {r.dai_score} 分
                          </span>
                        </td>

                        {/* 资金仓位 */}
                        <td className="py-3 px-4 text-center">
                          <span
                            className={cn(
                              'inline-flex items-center px-2 py-0.5 rounded-md text-xs font-bold font-mono',
                              r.inst_position >= 70
                                ? 'bg-red-500/20 text-red-400 border border-red-500/30'
                                : r.inst_position >= 50
                                ? 'bg-orange-500/20 text-orange-300'
                                : 'text-muted'
                            )}
                          >
                            {r.inst_position}%
                          </span>
                        </td>

                        {/* 机构活跃度 */}
                        <td className="py-3 px-4 text-center">
                          <span className="text-sky-400 font-bold">{r.inst_activity}</span>
                        </td>

                        {/* 暗盘特征标签 */}
                        <td className="py-3 px-4 font-sans">
                          <div className="flex flex-wrap gap-1">
                            {r.pattern_tags.map((tag) => (
                              <span
                                key={tag}
                                className={cn(
                                  'px-1.5 py-0.5 rounded text-[10px] font-medium border',
                                  tag.includes('假跌')
                                    ? 'bg-red-500/10 border-red-500/30 text-red-400'
                                    : tag.includes('冰山')
                                    ? 'bg-sky-500/10 border-sky-500/30 text-sky-300'
                                    : tag.includes('锁仓')
                                    ? 'bg-amber-500/10 border-amber-500/30 text-amber-300'
                                    : 'bg-elevated border-border text-muted'
                                )}
                              >
                                {tag}
                              </span>
                            ))}
                          </div>
                        </td>

                        {/* 次日潜力星级 */}
                        <td className="py-3 px-4 text-center">
                          <div className="flex items-center justify-center gap-0.5 text-amber-400 text-xs">
                            {Array.from({ length: r.potential_stars }).map((_, i) => (
                              <Star key={i} className="h-3 w-3 fill-amber-400 text-amber-400" />
                            ))}
                          </div>
                        </td>

                        {/* 操作 */}
                        <td className="py-3 px-4 text-center font-sans">
                          <button
                            onClick={(e) => {
                              e.stopPropagation()
                              setPreviewSymbol(r.symbol)
                            }}
                            className="text-xs text-sky-400 hover:text-sky-300 hover:underline"
                          >
                            查看K线
                          </button>
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

      {/* 个股详情弹窗 (包含资金仓位、四路资金条形图、AI机构活跃度) */}
      {previewSymbol && (
        <StockPreviewDialog symbol={previewSymbol} onClose={() => setPreviewSymbol(null)} />
      )}
    </div>
  )
}
