import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Flame,
  Building2,
  Users2,
  TrendingUp,
  Search,
  RefreshCw,
  Award,
  Calendar,
  Sparkles,
} from 'lucide-react'
import { PageHeader } from '@/components/PageHeader'
import { EmptyState } from '@/components/EmptyState'
import { StockPreviewDialog } from '@/components/StockPreviewDialog'
import { api, type LhbDailyStockItem } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { fmtBigNum, fmtPctValue, priceColorClass } from '@/lib/format'
import { cn } from '@/lib/cn'

type TabKey = 'daily' | 'institution' | 'branch' | 'stocks'
type DaysOption = 5 | 10 | 30 | 60

function fmtWan(v: number | null | undefined, withSign: boolean = true): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const abs = Math.abs(v)
  const sign = withSign ? (v > 0 ? '+' : v < 0 ? '-' : '') : ''
  if (abs >= 10000) {
    return `${sign}${(abs / 10000).toFixed(2)}亿`
  }
  return `${sign}${abs.toFixed(2)}万`
}

export function LongHuBang() {
  const [activeTab, setActiveTab] = useState<TabKey>('daily')
  const [days, setDays] = useState<DaysOption>(5)
  const [categoryFilter, setCategoryFilter] = useState<string>('all')
  const [search, setSearch] = useState('')
  const [previewStock, setPreviewStock] = useState<{ symbol: string; name: string } | null>(null)

  // 1. 每日龙虎榜详情
  const dailyQuery = useQuery({
    queryKey: QK.lhbDaily,
    queryFn: api.lhbDaily,
    staleTime: 60_000,
  })

  // 2. 个股上榜统计
  const stockStatsQuery = useQuery({
    queryKey: QK.lhbStockStats(days),
    queryFn: () => api.lhbStockStats(days),
    staleTime: 60_000,
  })

  // 3. 营业部统计
  const branchStatsQuery = useQuery({
    queryKey: QK.lhbBranchStats(days),
    queryFn: () => api.lhbBranchStats(days),
    staleTime: 60_000,
  })

  // 4. 机构席位追踪
  const institutionStatsQuery = useQuery({
    queryKey: QK.lhbInstitutionStats(days),
    queryFn: () => api.lhbInstitutionStats(days),
    staleTime: 60_000,
  })

  // 5. 机构明细流水
  const institutionDetailsQuery = useQuery({
    queryKey: QK.lhbInstitutionDetails,
    queryFn: api.lhbInstitutionDetails,
    staleTime: 60_000,
  })

  const isRefreshing =
    dailyQuery.isFetching ||
    stockStatsQuery.isFetching ||
    branchStatsQuery.isFetching ||
    institutionStatsQuery.isFetching ||
    institutionDetailsQuery.isFetching

  const handleRefresh = () => {
    dailyQuery.refetch()
    stockStatsQuery.refetch()
    branchStatsQuery.refetch()
    institutionStatsQuery.refetch()
    institutionDetailsQuery.refetch()
  }

  // 计算每日榜单过滤
  const dailyData = dailyQuery.data
  const filteredDailyStocks = useMemo(() => {
    if (!dailyData) return []
    let list: LhbDailyStockItem[] = []
    if (categoryFilter === 'all') {
      list = dailyData.all_stocks || []
    } else {
      list = dailyData.categories[categoryFilter] || []
    }
    const q = search.trim().toLowerCase()
    if (!q) return list
    return list.filter(
      s =>
        s.name.toLowerCase().includes(q) ||
        s.code.includes(q) ||
        s.symbol.toLowerCase().includes(q) ||
        (s.reasons && s.reasons.some(r => r.includes(q)))
    )
  }, [dailyData, categoryFilter, search])

  // 计算机构榜过滤与排序
  const instStats = institutionStatsQuery.data || []
  const filteredInstStats = useMemo(() => {
    const q = search.trim().toLowerCase()
    const base = q
      ? instStats.filter(s => s.name.toLowerCase().includes(q) || s.code.includes(q) || s.symbol.toLowerCase().includes(q))
      : instStats
    return [...base].sort((a, b) => b.net_amount - a.net_amount)
  }, [instStats, search])

  // 计算营业部榜过滤与排序
  const branchStats = branchStatsQuery.data || []
  const filteredBranchStats = useMemo(() => {
    const q = search.trim().toLowerCase()
    const base = q
      ? branchStats.filter(
          b =>
            b.branch_name.toLowerCase().includes(q) ||
            b.top3_stocks.some(t => t.toLowerCase().includes(q))
        )
      : branchStats
    return [...base].sort((a, b) => b.buy_amount - a.buy_amount)
  }, [branchStats, search])

  // 计算个股统计榜过滤与排序
  const stockStats = stockStatsQuery.data || []
  const filteredStockStats = useMemo(() => {
    const q = search.trim().toLowerCase()
    const base = q
      ? stockStats.filter(s => s.name.toLowerCase().includes(q) || s.code.includes(q) || s.symbol.toLowerCase().includes(q))
      : stockStats
    return [...base].sort((a, b) => (b.count !== a.count ? b.count - a.count : b.net_amount - a.net_amount))
  }, [stockStats, search])

  // 顶栏汇总核心指标
  const topInstBuyStock = useMemo(() => {
    if (!instStats.length) return null
    return [...instStats].sort((a, b) => b.net_amount - a.net_amount)[0]
  }, [instStats])

  const topActiveBranch = useMemo(() => {
    if (!branchStats.length) return null
    return [...branchStats].sort((a, b) => b.count - a.count)[0]
  }, [branchStats])

  const totalInstNetWan = useMemo(() => {
    return instStats.reduce((sum, item) => sum + (item.net_amount || 0), 0)
  }, [instStats])

  return (
    <div className="space-y-6 pb-12">
      {/* 顶栏标题区 */}
      <PageHeader
        title="龙虎榜数据"
        subtitle="实时全景追踪主力机构席位抢筹、一线顶级游资营业部动向与每日龙虎榜异动股票"
        right={
          <div className="flex items-center gap-3">
            {dailyData?.date && (
              <div className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-elevated border border-border text-xs text-muted">
                <Calendar className="h-3.5 w-3.5 text-primary" />
                <span>数据日期: <strong className="text-foreground font-mono">{dailyData.date}</strong></span>
              </div>
            )}
            <button
              onClick={handleRefresh}
              disabled={isRefreshing}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-btn bg-elevated hover:bg-elevated/80 border border-border text-xs font-medium text-foreground transition-all cursor-pointer disabled:opacity-50"
            >
              <RefreshCw className={cn('h-3.5 w-3.5', isRefreshing && 'animate-spin text-primary')} />
              <span>刷新</span>
            </button>
          </div>
        }
      />

      {/* 4 大核心指标卡 */}
      <div className="px-5 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* 今日上榜股票数 */}
        <div className="relative overflow-hidden rounded-panel border border-border/80 bg-surface/60 p-4 shadow-subtle backdrop-blur-md">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-muted">今日上榜股票数</span>
            <div className="p-2 rounded-lg bg-orange-500/10 text-orange-400">
              <Flame className="h-4 w-4" />
            </div>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-bold font-mono text-foreground">
              {dailyData?.total_stocks_count ?? '—'}
            </span>
            <span className="text-xs text-muted">只异动标的</span>
          </div>
          <div className="mt-1 text-[11px] text-muted truncate">
            涵盖涨跌偏离、换手振幅等 12 维规则
          </div>
        </div>

        {/* 机构净买入总额 */}
        <div className="relative overflow-hidden rounded-panel border border-border/80 bg-surface/60 p-4 shadow-subtle backdrop-blur-md">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-muted">机构净买入合计 ({days}日)</span>
            <div className="p-2 rounded-lg bg-emerald-500/10 text-emerald-400">
              <Building2 className="h-4 w-4" />
            </div>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className={cn('text-2xl font-bold font-mono', totalInstNetWan >= 0 ? 'text-bull' : 'text-bear')}>
              {fmtWan(totalInstNetWan)}
            </span>
          </div>
          <div className="mt-1 text-[11px] text-muted truncate">
            机构跟踪标的共 {instStats.length} 只
          </div>
        </div>

        {/* 机构抢筹龙头 */}
        <div
          onClick={() => topInstBuyStock && setPreviewStock({ symbol: topInstBuyStock.symbol, name: topInstBuyStock.name })}
          className="relative overflow-hidden rounded-panel border border-border/80 bg-surface/60 p-4 shadow-subtle backdrop-blur-md cursor-pointer hover:border-primary/50 transition-colors group"
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-muted">机构净买第一</span>
            <div className="p-2 rounded-lg bg-purple-500/10 text-purple-400 group-hover:scale-110 transition-transform">
              <Award className="h-4 w-4" />
            </div>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-lg font-bold text-foreground truncate">
              {topInstBuyStock ? topInstBuyStock.name : '—'}
            </span>
            {topInstBuyStock && (
              <span className="text-xs font-mono text-muted">{topInstBuyStock.code}</span>
            )}
          </div>
          <div className="mt-1 text-[11px] font-mono text-bull truncate">
            {topInstBuyStock ? `净买入 ${fmtWan(topInstBuyStock.net_amount)}` : '等待数据'}
          </div>
        </div>

        {/* 顶级活跃游资席位 */}
        <div className="relative overflow-hidden rounded-panel border border-border/80 bg-surface/60 p-4 shadow-subtle backdrop-blur-md">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-muted">最活跃游资席位 ({days}日)</span>
            <div className="p-2 rounded-lg bg-cyan-500/10 text-cyan-400">
              <Users2 className="h-4 w-4" />
            </div>
          </div>
          <div className="mt-2 truncate">
            <span className="text-sm font-semibold text-foreground" title={topActiveBranch?.branch_name}>
              {topActiveBranch ? topActiveBranch.branch_name : '—'}
            </span>
          </div>
          <div className="mt-1 text-[11px] text-muted truncate">
            {topActiveBranch ? `上榜 ${topActiveBranch.count} 次 · 买入 ${fmtWan(topActiveBranch.buy_amount)}` : '等待数据'}
          </div>
        </div>
      </div>

      {/* 选项卡导航与搜索过滤 */}
      <div className="px-5 flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-4 border-b border-border/60 pb-3">
        {/* 4 大 Tab */}
        <div className="flex items-center gap-1.5 p-1 rounded-btn bg-elevated/70 border border-border">
          <button
            onClick={() => setActiveTab('daily')}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all cursor-pointer',
              activeTab === 'daily'
                ? 'bg-primary text-primary-foreground shadow-sm'
                : 'text-muted hover:text-foreground'
            )}
          >
            <Flame className="h-3.5 w-3.5" />
            <span>每日龙虎榜</span>
            {dailyData && (
              <span className="ml-1 px-1.5 py-0.2 rounded-full text-[10px] bg-black/20">
                {dailyData.total_stocks_count}
              </span>
            )}
          </button>

          <button
            onClick={() => setActiveTab('institution')}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all cursor-pointer',
              activeTab === 'institution'
                ? 'bg-primary text-primary-foreground shadow-sm'
                : 'text-muted hover:text-foreground'
            )}
          >
            <Building2 className="h-3.5 w-3.5" />
            <span>机构席位追踪</span>
          </button>

          <button
            onClick={() => setActiveTab('branch')}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all cursor-pointer',
              activeTab === 'branch'
                ? 'bg-primary text-primary-foreground shadow-sm'
                : 'text-muted hover:text-foreground'
            )}
          >
            <Users2 className="h-3.5 w-3.5" />
            <span>游资营业部</span>
          </button>

          <button
            onClick={() => setActiveTab('stocks')}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all cursor-pointer',
              activeTab === 'stocks'
                ? 'bg-primary text-primary-foreground shadow-sm'
                : 'text-muted hover:text-foreground'
            )}
          >
            <TrendingUp className="h-3.5 w-3.5" />
            <span>个股上榜统计</span>
          </button>
        </div>

        {/* 右侧搜索与周期选择 */}
        <div className="flex items-center gap-3">
          {activeTab !== 'daily' && (
            <div className="flex items-center gap-1 p-1 rounded-btn bg-elevated/70 border border-border text-xs">
              {([5, 10, 30, 60] as DaysOption[]).map(d => (
                <button
                  key={d}
                  onClick={() => setDays(d)}
                  className={cn(
                    'px-2.5 py-1 rounded text-xs font-medium transition-all cursor-pointer',
                    days === d
                      ? 'bg-surface text-foreground shadow-sm font-semibold'
                      : 'text-muted hover:text-foreground'
                  )}
                >
                  近{d}日
                </button>
              ))}
            </div>
          )}

          {/* 搜索框 */}
          <div className="relative w-full sm:w-56">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted" />
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="搜索股票/代码/营业部..."
              className="w-full pl-8 pr-3 py-1.5 rounded-btn bg-elevated/70 border border-border text-xs text-foreground placeholder:text-muted focus:outline-none focus:border-primary transition-all"
            />
          </div>
        </div>
      </div>

      {/* Tab 1: 每日龙虎榜 */}
      {activeTab === 'daily' && (
        <div className="px-5 space-y-4">
          {/* 上榜原因分类胶囊筛选 */}
          <div className="flex flex-wrap items-center gap-1.5">
            <button
              onClick={() => setCategoryFilter('all')}
              className={cn(
                'px-3 py-1 rounded-full text-xs font-medium transition-all cursor-pointer border',
                categoryFilter === 'all'
                  ? 'bg-primary/15 text-primary border-primary/40 font-semibold'
                  : 'bg-elevated/50 text-muted border-border hover:text-foreground'
              )}
            >
              全部 ({dailyData?.total_stocks_count ?? 0})
            </button>
            {dailyData?.category_meta &&
              Object.entries(dailyData.category_meta).map(([key, label]) => {
                const count = dailyData.categories[key]?.length || 0
                if (count === 0) return null
                return (
                  <button
                    key={key}
                    onClick={() => setCategoryFilter(key)}
                    className={cn(
                      'px-3 py-1 rounded-full text-xs font-medium transition-all cursor-pointer border flex items-center gap-1',
                      categoryFilter === key
                        ? 'bg-primary/15 text-primary border-primary/40 font-semibold'
                        : 'bg-elevated/50 text-muted border-border hover:text-foreground'
                    )}
                  >
                    <span>{label}</span>
                    <span className="text-[10px] opacity-75 font-mono">({count})</span>
                  </button>
                )
              })}
          </div>

          {/* 每日龙虎榜表格 */}
          <div className="rounded-panel border border-border/80 bg-surface/70 shadow-card overflow-hidden backdrop-blur-md">
            <div className="overflow-x-auto">
              <table className="w-full text-xs text-left border-collapse">
                <thead>
                  <tr className="border-b border-border/80 bg-elevated/40 text-muted text-[11px] font-medium">
                    <th className="px-4 py-3">序号</th>
                    <th className="px-4 py-3">标的简称</th>
                    <th className="px-4 py-3 text-right">最新收盘</th>
                    <th className="px-4 py-3 text-right">涨跌幅</th>
                    <th className="px-4 py-3 text-right">成交额</th>
                    <th className="px-4 py-3 text-right">成交量(手)</th>
                    <th className="px-4 py-3">上榜原因 / 异动类型</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/50">
                  {filteredDailyStocks.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="py-12 text-center text-muted">
                        <EmptyState icon={Flame} title="暂无龙虎榜上榜数据" hint="每日龙虎榜数据通常在交易日 17:00~20:00 由交易所发布并同步" />
                      </td>
                    </tr>
                  ) : (
                    filteredDailyStocks.map((stock, idx) => (
                      <tr
                        key={`${stock.symbol}-${idx}`}
                        onClick={() => setPreviewStock({ symbol: stock.symbol, name: stock.name })}
                        className="hover:bg-elevated/40 cursor-pointer transition-colors"
                      >
                        <td className="px-4 py-2.5 font-mono text-muted">{idx + 1}</td>
                        <td className="px-4 py-2.5">
                          <div className="font-semibold text-foreground flex items-center gap-1.5">
                            <span>{stock.name}</span>
                            <span className="font-mono text-[10px] text-muted font-normal">{stock.symbol}</span>
                          </div>
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono font-medium text-foreground">
                          {stock.close ? stock.close.toFixed(2) : '—'}
                        </td>
                        <td className={cn('px-4 py-2.5 text-right font-mono font-semibold', priceColorClass(stock.change_pct))}>
                          {fmtPctValue(stock.change_pct)}
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono text-foreground">
                          {fmtBigNum(stock.amount)}
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono text-muted">
                          {stock.volume ? (stock.volume >= 10000 ? `${(stock.volume / 10000).toFixed(1)}万` : stock.volume.toLocaleString()) : '—'}
                        </td>
                        <td className="px-4 py-2.5">
                          <div className="flex flex-wrap gap-1">
                            {(stock.reasons || [stock.reason_label]).map((r, ri) => (
                              <span
                                key={ri}
                                className="px-2 py-0.5 rounded text-[10px] font-medium bg-primary/10 text-primary border border-primary/20"
                              >
                                {r}
                              </span>
                            ))}
                          </div>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Tab 2: 机构席位追踪 */}
      {activeTab === 'institution' && (
        <div className="px-5 grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* 左侧 2 栏: 机构席位统计榜 */}
          <div className="lg:col-span-2 space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-semibold text-foreground flex items-center gap-1.5">
                <Building2 className="h-4 w-4 text-emerald-400" />
                <span>近 {days} 日机构席位抢筹与出逃榜</span>
              </h3>
              <span className="text-[11px] text-muted">按机构净买入额排序</span>
            </div>

            <div className="rounded-panel border border-border/80 bg-surface/70 shadow-card overflow-hidden backdrop-blur-md">
              <div className="overflow-x-auto">
                <table className="w-full text-xs text-left border-collapse">
                  <thead>
                    <tr className="border-b border-border/80 bg-elevated/40 text-muted text-[11px] font-medium">
                      <th className="px-4 py-3">标的</th>
                      <th className="px-4 py-3 text-right">机构买入额</th>
                      <th className="px-4 py-3 text-right">买入次数</th>
                      <th className="px-4 py-3 text-right">机构卖出额</th>
                      <th className="px-4 py-3 text-right">卖出次数</th>
                      <th className="px-4 py-3 text-right">机构净买入</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/50">
                    {filteredInstStats.length === 0 ? (
                      <tr>
                        <td colSpan={6} className="py-12 text-center text-muted">
                          <EmptyState icon={Building2} title="暂无机构席位数据" hint="暂无近期机构大笔交易数据" />
                        </td>
                      </tr>
                    ) : (
                      filteredInstStats.map((item, idx) => (
                        <tr
                          key={`${item.symbol}-${idx}`}
                          onClick={() => setPreviewStock({ symbol: item.symbol, name: item.name })}
                          className="hover:bg-elevated/40 cursor-pointer transition-colors"
                        >
                          <td className="px-4 py-2.5">
                            <div className="font-semibold text-foreground flex items-center gap-1.5">
                              <span>{item.name}</span>
                              <span className="font-mono text-[10px] text-muted font-normal">{item.code}</span>
                            </div>
                          </td>
                          <td className="px-4 py-2.5 text-right font-mono font-medium text-bull">
                            {fmtWan(item.buy_amount, false)}
                          </td>
                          <td className="px-4 py-2.5 text-right font-mono text-muted">
                            {item.buy_count} 次
                          </td>
                          <td className="px-4 py-2.5 text-right font-mono font-medium text-bear">
                            {fmtWan(item.sell_amount, false)}
                          </td>
                          <td className="px-4 py-2.5 text-right font-mono text-muted">
                            {item.sell_count} 次
                          </td>
                          <td className={cn('px-4 py-2.5 text-right font-mono font-bold', item.net_amount >= 0 ? 'text-bull' : 'text-bear')}>
                            {fmtWan(item.net_amount, true)}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {/* 右侧 1 栏: 近5日机构成交明细流水 */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-semibold text-foreground flex items-center gap-1.5">
                <Sparkles className="h-4 w-4 text-purple-400" />
                <span>机构成交明细流水 (近5日)</span>
              </h3>
              <span className="text-[11px] text-muted">{institutionDetailsQuery.data?.length ?? 0} 笔流水</span>
            </div>

            <div className="rounded-panel border border-border/80 bg-surface/70 shadow-card p-3 max-h-[640px] overflow-y-auto space-y-2.5 backdrop-blur-md">
              {(institutionDetailsQuery.data || []).map((detail, idx) => (
                <div
                  key={`${detail.symbol}-${detail.date}-${idx}`}
                  onClick={() => setPreviewStock({ symbol: detail.symbol, name: detail.name })}
                  className="p-2.5 rounded-lg bg-elevated/40 border border-border/50 hover:border-primary/40 hover:bg-elevated/70 cursor-pointer transition-all"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5">
                      <span className="font-semibold text-xs text-foreground">{detail.name}</span>
                      <span className="text-[10px] font-mono text-muted">{detail.code}</span>
                    </div>
                    <span className="text-[10px] font-mono text-muted">{detail.date}</span>
                  </div>

                  <div className="mt-2 grid grid-cols-3 gap-1 text-[11px] font-mono">
                    <div>
                      <span className="text-muted text-[10px] block">机构买入</span>
                      <span className="text-bull font-medium">{fmtWan(detail.buy_amount, false)}</span>
                    </div>
                    <div>
                      <span className="text-muted text-[10px] block">机构卖出</span>
                      <span className="text-bear font-medium">{fmtWan(detail.sell_amount, false)}</span>
                    </div>
                    <div className="text-right">
                      <span className="text-muted text-[10px] block">净买入</span>
                      <span className={cn('font-bold', detail.net_amount >= 0 ? 'text-bull' : 'text-bear')}>
                        {fmtWan(detail.net_amount, true)}
                      </span>
                    </div>
                  </div>

                  {detail.reason && (
                    <div className="mt-1.5 text-[10px] text-muted truncate border-t border-border/30 pt-1">
                      原因: {detail.reason}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Tab 3: 顶级游资与营业部 */}
      {activeTab === 'branch' && (
        <div className="px-5 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-semibold text-foreground flex items-center gap-1.5">
              <Users2 className="h-4 w-4 text-cyan-400" />
              <span>近 {days} 日一线知名游资营业部成交排行</span>
            </h3>
            <span className="text-[11px] text-muted">共收录 {filteredBranchStats.length} 个活跃席位</span>
          </div>

          <div className="rounded-panel border border-border/80 bg-surface/70 shadow-card overflow-hidden backdrop-blur-md">
            <div className="overflow-x-auto">
              <table className="w-full text-xs text-left border-collapse">
                <thead>
                  <tr className="border-b border-border/80 bg-elevated/40 text-muted text-[11px] font-medium">
                    <th className="px-4 py-3">序号</th>
                    <th className="px-4 py-3">营业部名称</th>
                    <th className="px-4 py-3 text-right">上榜次数</th>
                    <th className="px-4 py-3 text-right">累计买入额</th>
                    <th className="px-4 py-3 text-right">累计卖出额</th>
                    <th className="px-4 py-3 text-right">净买入额</th>
                    <th className="px-4 py-3">主要买入标的 (Top 3)</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/50">
                  {filteredBranchStats.length === 0 ? (
                    <tr>
                      <td colSpan={7} className="py-12 text-center text-muted">
                        <EmptyState icon={Users2} title="暂无营业部统计数据" hint="暂无符合条件的营业部席位数据" />
                      </td>
                    </tr>
                  ) : (
                    filteredBranchStats.map((branch, idx) => (
                      <tr key={`${branch.branch_name}-${idx}`} className="hover:bg-elevated/40 transition-colors">
                        <td className="px-4 py-2.5 font-mono text-muted">{idx + 1}</td>
                        <td className="px-4 py-2.5 font-medium text-foreground">
                          {branch.branch_name}
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono text-foreground font-semibold">
                          <span className="px-2 py-0.5 rounded bg-elevated text-xs">
                            {branch.count} 次
                          </span>
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono text-bull font-medium">
                          {fmtWan(branch.buy_amount, false)}
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono text-bear font-medium">
                          {fmtWan(branch.sell_amount, false)}
                        </td>
                        <td className={cn('px-4 py-2.5 text-right font-mono font-bold', branch.net_amount >= 0 ? 'text-bull' : 'text-bear')}>
                          {fmtWan(branch.net_amount, true)}
                        </td>
                        <td className="px-4 py-2.5">
                          <div className="flex flex-wrap gap-1">
                            {branch.top3_stocks.map((stockName, si) => (
                              <span
                                key={si}
                                onClick={() => setPreviewStock({ symbol: stockName, name: stockName })}
                                className="px-2 py-0.5 rounded text-[10px] bg-elevated/80 border border-border text-foreground hover:border-primary/50 cursor-pointer transition-all"
                              >
                                {stockName}
                              </span>
                            ))}
                          </div>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* Tab 4: 个股上榜统计 */}
      {activeTab === 'stocks' && (
        <div className="px-5 space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-semibold text-foreground flex items-center gap-1.5">
              <TrendingUp className="h-4 w-4 text-amber-400" />
              <span>近 {days} 日个股龙虎榜上榜频次与龙虎资金汇总</span>
            </h3>
            <span className="text-[11px] text-muted">共 {filteredStockStats.length} 只标的</span>
          </div>

          <div className="rounded-panel border border-border/80 bg-surface/70 shadow-card overflow-hidden backdrop-blur-md">
            <div className="overflow-x-auto">
              <table className="w-full text-xs text-left border-collapse">
                <thead>
                  <tr className="border-b border-border/80 bg-elevated/40 text-muted text-[11px] font-medium">
                    <th className="px-4 py-3">序号</th>
                    <th className="px-4 py-3">标的简称</th>
                    <th className="px-4 py-3 text-right">上榜次数</th>
                    <th className="px-4 py-3 text-right">龙虎榜买入总额</th>
                    <th className="px-4 py-3 text-right">龙虎榜卖出总额</th>
                    <th className="px-4 py-3 text-right">龙虎榜净额</th>
                    <th className="px-4 py-3 text-right">买入席位数</th>
                    <th className="px-4 py-3 text-right">卖出席位数</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/50">
                  {filteredStockStats.length === 0 ? (
                    <tr>
                      <td colSpan={8} className="py-12 text-center text-muted">
                        <EmptyState icon={TrendingUp} title="暂无个股上榜统计" hint="暂无符合筛选条件的个股数据" />
                      </td>
                    </tr>
                  ) : (
                    filteredStockStats.map((item, idx) => (
                      <tr
                        key={`${item.symbol}-${idx}`}
                        onClick={() => setPreviewStock({ symbol: item.symbol, name: item.name })}
                        className="hover:bg-elevated/40 cursor-pointer transition-colors"
                      >
                        <td className="px-4 py-2.5 font-mono text-muted">{idx + 1}</td>
                        <td className="px-4 py-2.5">
                          <div className="font-semibold text-foreground flex items-center gap-1.5">
                            <span>{item.name}</span>
                            <span className="font-mono text-[10px] text-muted font-normal">{item.code}</span>
                          </div>
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono font-bold text-foreground">
                          <span className="px-2 py-0.5 rounded bg-primary/10 text-primary text-xs border border-primary/20">
                            {item.count} 次
                          </span>
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono text-bull font-medium">
                          {fmtWan(item.buy_amount, false)}
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono text-bear font-medium">
                          {fmtWan(item.sell_amount, false)}
                        </td>
                        <td className={cn('px-4 py-2.5 text-right font-mono font-bold', item.net_amount >= 0 ? 'text-bull' : 'text-bear')}>
                          {fmtWan(item.net_amount, true)}
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono text-muted">
                          {item.buy_seats}
                        </td>
                        <td className="px-4 py-2.5 text-right font-mono text-muted">
                          {item.sell_seats}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* 股票 K 线弹窗预览 */}
      {previewStock && (
        <StockPreviewDialog
          symbol={previewStock.symbol}
          name={previewStock.name}
          onClose={() => setPreviewStock(null)}
        />
      )}
    </div>
  )
}
