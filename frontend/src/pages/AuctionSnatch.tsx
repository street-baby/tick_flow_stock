import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Zap,
  RefreshCw,
  SlidersHorizontal,
  Flame,
  Star,
  TrendingUp,
  Coins,
  Search,
  Calendar,
  Sparkles,
} from 'lucide-react'
import { motion } from 'framer-motion'
import { api, type AuctionStockRow, type AuctionAIAnalysisResult, type AuctionAIAnalysisItem } from '@/lib/api'
import { cn } from '@/lib/cn'
import { toast } from '@/components/Toast'
import { StockPreviewDialog } from '@/components/StockPreviewDialog'

export function AuctionSnatch() {
  const [asOf, setAsOf] = useState('')
  const [minGapPct, setMinGapPct] = useState(1.5)
  const [includeChinext, setIncludeChinext] = useState(true)
  const [includeStar, setIncludeStar] = useState(true)
  const [onlyDoji, setOnlyDoji] = useState(false)
  const [onlyCorePurple, setOnlyCorePurple] = useState(false)
  const [minMv, setMinMv] = useState(10)
  const [maxMv, setMaxMv] = useState(200)
  const [keyword, setKeyword] = useState('')
  const [previewSymbol, setPreviewSymbol] = useState<string | null>(null)

  // AI 高开逻辑分析状态
  const [aiAnalysis, setAiAnalysis] = useState<AuctionAIAnalysisResult | null>(null)
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [showAiModal, setShowAiModal] = useState(false)

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: [
      'auction-screen',
      asOf,
      minGapPct,
      includeChinext,
      includeStar,
      onlyDoji,
      minMv,
      maxMv,
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
      }),
    refetchInterval: 15000,
  })

  const rows = (data?.rows || []).filter((r: AuctionStockRow) => {
    if (onlyCorePurple && !r.is_core_purple) return false
    if (!keyword) return true
    const kw = keyword.toLowerCase()
    return r.name.toLowerCase().includes(kw) || r.symbol.toLowerCase().includes(kw)
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

  const stats = data?.stats

  // 创建代码到 AI 逻辑的映射
  const aiMap = new Map<string, AuctionAIAnalysisItem>((aiAnalysis?.items || []).map((it) => [it.symbol, it]))

  return (
    <div className="min-h-full bg-base text-foreground pb-16">
      {/* 顶部主横幅 */}
      <div className="sticky top-0 z-20 border-b border-border bg-surface/95 backdrop-blur-md px-6 py-4">
        <div className="max-w-7xl mx-auto flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-purple-500/20 via-orange-500/20 to-red-500/20 border border-purple-500/30 text-purple-400 shadow-[0_0_15px_rgba(168,85,247,0.15)]">
              <Zap className="h-5 w-5 animate-pulse text-purple-400" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-lg font-bold text-foreground tracking-wide">
                  9:25 集合竞价抢筹选股
                </h1>
                <span className="inline-flex items-center gap-1 rounded-full border border-purple-500/30 bg-purple-500/10 px-2 py-0.5 text-[10px] font-semibold text-purple-300 animate-pulse">
                  💜 核心强势抢筹战法
                </span>
                <span className="inline-flex items-center rounded-full border border-border bg-elevated px-2 py-0.5 text-[10px] text-muted">
                  已剔除北交所/ST/次新股
                </span>
              </div>
              <p className="text-xs text-muted mt-0.5">
                定位「试盘蓄势不破底 + 早盘倍量大额抢筹 + 10~200亿弹性市值」主力游资爆拉牛股
              </p>
            </div>
          </div>

          {/* 顶栏操作区 */}
          <div className="flex items-center flex-wrap gap-2.5">
            {/* 搜索框 */}
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted" />
              <input
                type="text"
                placeholder="搜索名称 / 代码..."
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                className="h-8 w-36 md:w-48 pl-8 pr-3 text-xs rounded-lg border border-border bg-elevated/50 text-foreground placeholder:text-muted focus:outline-none focus:border-accent"
              />
            </div>

            {/* 日期选择 */}
            <div className="flex items-center gap-1.5 bg-elevated/60 px-2.5 py-1 rounded-lg border border-border text-xs text-secondary">
              <Calendar className="h-3.5 w-3.5 text-muted" />
              <span>交易日:</span>
              <input
                type="date"
                value={asOf || data?.as_of || ''}
                onChange={(e) => setAsOf(e.target.value)}
                className="bg-transparent text-xs text-foreground focus:outline-none"
              />
            </div>

            {/* AI 一键分析高开逻辑按钮 */}
            <button
              onClick={handleAiAnalyze}
              disabled={isAnalyzing || rows.length === 0}
              className="inline-flex items-center justify-center h-8 px-3.5 rounded-lg bg-gradient-to-r from-purple-500 via-orange-500 to-red-500 hover:from-purple-400 hover:to-red-400 text-white text-xs font-bold shadow-md shadow-purple-500/20 transition-all cursor-pointer disabled:opacity-50"
            >
              <Sparkles className={cn('h-3.5 w-3.5 mr-1.5', isAnalyzing && 'animate-spin')} />
              {isAnalyzing ? 'AI 分析高开逻辑中…' : '✨ AI 一键分析高开逻辑'}
            </button>

            {/* 刷新按钮 */}
            <button
              onClick={() => {
                refetch()
                toast('竞价数据已刷新', 'success')
              }}
              className="inline-flex items-center justify-center h-8 px-3 rounded-lg border border-border bg-surface text-xs font-medium text-secondary hover:text-foreground hover:bg-elevated transition-colors cursor-pointer"
            >
              <RefreshCw className={cn('h-3.5 w-3.5 mr-1.5', (isLoading || isFetching) && 'animate-spin')} />
              刷新
            </button>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6 pt-5 space-y-5">
        {/* 筛选控制器卡片 */}
        <div className="rounded-xl border border-border bg-surface p-4 space-y-3">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div className="flex items-center flex-wrap gap-4 text-xs font-medium text-foreground">
              <span className="text-muted flex items-center gap-1">
                <SlidersHorizontal className="h-3.5 w-3.5" />
                板块筛选:
              </span>

              {/* 核心紫色抢筹筛选 */}
              <label className="flex items-center gap-1.5 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={onlyCorePurple}
                  onChange={(e) => setOnlyCorePurple(e.target.checked)}
                  className="rounded border-border text-purple-500 focus:ring-purple-500 h-3.5 w-3.5"
                />
                <span className="px-2 py-0.5 rounded text-[11px] bg-purple-500/15 text-purple-300 border border-purple-500/35 font-bold shadow-[0_0_8px_rgba(168,85,247,0.2)]">
                  💜 仅看核心强势抢筹 ({stats?.core_purple_count || 0})
                </span>
              </label>

              {/* 创业板勾选 */}
              <label className="flex items-center gap-1.5 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={includeChinext}
                  onChange={(e) => setIncludeChinext(e.target.checked)}
                  className="rounded border-border text-accent focus:ring-accent h-3.5 w-3.5"
                />
                <span className="px-1.5 py-0.5 rounded text-[11px] bg-blue-500/10 text-blue-300 border border-blue-500/20">
                  创业板 (300)
                </span>
              </label>

              {/* 科创板勾选 */}
              <label className="flex items-center gap-1.5 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={includeStar}
                  onChange={(e) => setIncludeStar(e.target.checked)}
                  className="rounded border-border text-accent focus:ring-accent h-3.5 w-3.5"
                />
                <span className="px-1.5 py-0.5 rounded text-[11px] bg-purple-500/10 text-purple-300 border border-purple-500/20">
                  科创板 (688)
                </span>
              </label>

              {/* 只看十字星 */}
              <label className="flex items-center gap-1.5 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={onlyDoji}
                  onChange={(e) => setOnlyDoji(e.target.checked)}
                  className="rounded border-border text-amber-400 focus:ring-amber-400 h-3.5 w-3.5"
                />
                <span className="px-1.5 py-0.5 rounded text-[11px] bg-amber-500/10 text-amber-300 border border-amber-500/25 font-bold">
                  ⭐ 仅看十字星蓄势
                </span>
              </label>
            </div>

            {/* 参数微调快捷栏 */}
            <div className="flex items-center flex-wrap gap-4 text-xs text-secondary">
              <div className="flex items-center gap-1.5">
                <span className="text-muted">高开幅度:</span>
                {[1.0, 1.5, 2.0, 3.0].map((gap) => (
                  <button
                    key={gap}
                    onClick={() => setMinGapPct(gap)}
                    className={cn(
                      'px-2 py-0.5 rounded-md text-[11px] font-mono transition-colors cursor-pointer',
                      minGapPct === gap
                        ? 'bg-accent text-white font-bold'
                        : 'bg-elevated text-secondary hover:text-foreground'
                    )}
                  >
                    &gt;={gap}%
                  </button>
                ))}
              </div>

              <div className="flex items-center gap-1.5">
                <span className="text-muted">市值范围:</span>
                {[
                  { label: '10~200亿', min: 10, max: 200 },
                  { label: '10~50亿', min: 10, max: 50 },
                  { label: '10~100亿', min: 10, max: 100 },
                  { label: '50~300亿', min: 50, max: 300 },
                ].map((item) => (
                  <button
                    key={item.label}
                    onClick={() => {
                      setMinMv(item.min)
                      setMaxMv(item.max)
                    }}
                    className={cn(
                      'px-2 py-0.5 rounded-md text-[11px] font-mono transition-colors cursor-pointer',
                      minMv === item.min && maxMv === item.max
                        ? 'bg-accent text-white font-bold'
                        : 'bg-elevated text-secondary hover:text-foreground'
                    )}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* 顶部统计数据卡片 */}
        {stats && (
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3.5">
            <div className="p-4 rounded-xl border border-border bg-surface flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-red-500/10 text-red-400 border border-red-500/20">
                <Flame className="h-5 w-5" />
              </div>
              <div>
                <div className="text-[11px] text-muted">竞价抢筹标的总数</div>
                <div className="text-xl font-bold font-mono text-foreground">
                  {data?.total || 0} <span className="text-xs font-normal text-muted">只</span>
                </div>
              </div>
            </div>

            <div className="p-4 rounded-xl border border-purple-500/30 bg-purple-500/[0.06] flex items-center gap-3 shadow-[0_0_15px_rgba(168,85,247,0.1)]">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-purple-500/20 text-purple-300 border border-purple-500/40 shadow-[0_0_10px_rgba(168,85,247,0.2)]">
                <Zap className="h-5 w-5" />
              </div>
              <div>
                <div className="text-[11px] text-purple-300/80 font-medium">💜 核心强势抢筹</div>
                <div className="text-xl font-bold font-mono text-purple-200">
                  {stats.core_purple_count || 0} <span className="text-xs font-normal text-muted">只</span>
                </div>
              </div>
            </div>

            <div className="p-4 rounded-xl border border-border bg-surface flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-500/10 text-blue-400 border border-blue-500/20">
                <TrendingUp className="h-5 w-5" />
              </div>
              <div>
                <div className="text-[11px] text-muted">平均高开幅度</div>
                <div className="text-xl font-bold font-mono text-red-400">
                  +{stats.avg_gap_pct}%
                </div>
              </div>
            </div>

            <div className="p-4 rounded-xl border border-border bg-surface flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-amber-500/10 text-amber-400 border border-amber-500/20">
                <Star className="h-5 w-5" />
              </div>
              <div>
                <div className="text-[11px] text-muted">十字星蓄势形态</div>
                <div className="text-xl font-bold font-mono text-amber-300">
                  {stats.doji_count} <span className="text-xs font-normal text-muted">只</span>
                </div>
              </div>
            </div>

            <div className="p-4 rounded-xl border border-border bg-surface flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                <Coins className="h-5 w-5" />
              </div>
              <div>
                <div className="text-[11px] text-muted">竞价抢筹总额</div>
                <div className="text-xl font-bold font-mono text-foreground">
                  {stats.total_bidding_amount_yi} <span className="text-xs font-normal text-muted">亿元</span>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* 涨停战法复盘特征提示栏 */}
        <div className="rounded-xl border border-purple-500/30 bg-gradient-to-r from-purple-500/15 via-amber-500/10 to-transparent p-4 flex items-start gap-3.5 shadow-sm">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-purple-500/20 text-purple-300 border border-purple-500/40 shadow-[0_0_10px_rgba(168,85,247,0.2)]">
            <Zap className="h-4 w-4" />
          </div>
          <div className="text-xs space-y-1.5">
            <div className="font-bold text-purple-200 flex items-center gap-2">
              <span>💜 顶级核心强势抢筹战法（南京商旅范式）</span>
              <span className="text-[10px] font-bold px-2 py-0.5 rounded bg-purple-500/25 text-purple-200 border border-purple-500/40">
                紫色极光核心标识 · 置顶推荐
              </span>
            </div>
            <p className="text-secondary leading-relaxed">
              <strong className="text-foreground">三大必杀起爆逻辑：</strong>
              ① <span className="text-purple-300 font-semibold">放量试盘线 + 绝对防守底线</span>（前期放量试盘探测压力，随后缩量洗盘且<strong>收盘价坚决不破试盘最低价</strong>，主力控盘铁证）；
              ② <span className="text-purple-300 font-semibold">竞价量比翻倍暴增</span>（早盘量比断层放大 &ge; 1.8~5.0，蓄势完毕合力发动总攻）；
              ③ <span className="text-purple-300 font-semibold">充沛资金抢筹</span>（中小市值早盘/全天成交大额 &ge; 1.5 亿或竞价超千万，主力大单通吃上方挂单直接拉板）。
            </p>
          </div>
        </div>

        {/* 标的表格 */}
        <div className="rounded-xl border border-border bg-surface overflow-hidden shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead>
                <tr className="border-b border-border bg-elevated/50 text-muted font-medium">
                  <th className="py-3 px-4 w-12 text-center">序号</th>
                  <th className="py-3 px-4">标的代码/名称</th>
                  <th className="py-3 px-4">板块</th>
                  <th className="py-3 px-4">竞价开盘价</th>
                  <th className="py-3 px-4">竞价高开</th>
                  <th className="py-3 px-4">昨日K线形态</th>
                  <th className="py-3 px-4">昨日实体/振幅</th>
                  <th className="py-3 px-4">总市值</th>
                  <th className="py-3 px-4">竞价成交额</th>
                  <th className="py-3 px-4">竞价量比</th>
                  <th className="py-3 px-4 text-center">抢筹评分</th>
                  <th className="py-3 px-4 text-center">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/60">
                {isLoading && (
                  <tr>
                    <td colSpan={12} className="py-12 text-center text-muted text-xs">
                      正在全市场扫描 9:25 集合竞价行情…
                    </td>
                  </tr>
                )}

                {!isLoading && rows.length === 0 && (
                  <tr>
                    <td colSpan={12} className="py-12 text-center text-muted text-xs">
                      暂无符合条件的竞价抢筹标的，可尝试调整高开幅度或市值区间
                    </td>
                  </tr>
                )}

                {rows.map((row, idx) => {
                  const isUp = row.open_gap_pct >= 0
                  return (
                    <motion.tr
                      key={row.symbol}
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      className={cn(
                        'hover:bg-elevated/40 transition-colors group cursor-pointer border-l-2',
                        row.is_core_purple
                          ? 'border-l-purple-500 bg-purple-500/[0.07] hover:bg-purple-500/[0.12]'
                          : row.is_super_breakout
                          ? 'border-l-amber-400 bg-amber-500/[0.05]'
                          : 'border-l-transparent'
                      )}
                      onClick={() => setPreviewSymbol(row.symbol)}
                    >
                      <td className="py-3 px-4 text-center font-mono text-muted">
                        {idx + 1}
                      </td>

                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2">
                          <span className={cn(
                            "font-bold transition-colors",
                            row.is_core_purple ? "text-purple-200 group-hover:text-purple-300" : "text-foreground group-hover:text-accent"
                          )}>
                            {row.name}
                          </span>
                          <span className="font-mono text-[11px] text-muted">
                            {row.symbol}
                          </span>
                          {row.is_core_purple && (
                            <span className="px-1.5 py-0.2 rounded text-[9px] font-bold bg-gradient-to-r from-purple-500/30 to-fuchsia-500/30 text-purple-200 border border-purple-500/50 shadow-[0_0_8px_rgba(168,85,247,0.3)]">
                              💜 核心强势抢筹
                            </span>
                          )}
                          {!row.is_core_purple && row.is_super_breakout && (
                            <span className="px-1.5 py-0.2 rounded text-[9px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30">
                              👑 涨停爆发基因
                            </span>
                          )}
                        </div>

                        {/* 试盘线防守底线信息 */}
                        {row.is_core_purple && row.test_date && row.test_low && (
                          <div className="mt-1 flex items-center gap-1 text-[10px] text-purple-300/90 bg-purple-500/10 border border-purple-500/20 px-1.5 py-0.5 rounded w-fit">
                            <Zap className="h-2.5 w-2.5 text-purple-400 shrink-0" />
                            <span>试盘日 {row.test_date.slice(5)} · 坚守 ¥{row.test_low.toFixed(2)} 底线 ({row.defense_days}天未破)</span>
                          </div>
                        )}

                        {aiMap.has(row.symbol) && (
                          <div className="mt-1 flex items-center gap-1 text-[10px] text-amber-300 bg-amber-500/10 border border-amber-500/20 px-1.5 py-0.5 rounded w-fit">
                            <Sparkles className="h-2.5 w-2.5 text-amber-400 shrink-0" />
                            <span className="truncate max-w-[240px] font-medium">{aiMap.get(row.symbol)?.gap_reason}</span>
                          </div>
                        )}
                      </td>

                      <td className="py-3 px-4">
                        <span
                          className={cn(
                            'px-1.5 py-0.5 rounded text-[10px] font-medium border',
                            row.board === '科创板'
                              ? 'bg-purple-500/10 text-purple-300 border-purple-500/20'
                              : row.board === '创业板'
                              ? 'bg-blue-500/10 text-blue-300 border-blue-500/20'
                              : 'bg-surface text-secondary border-border'
                          )}
                        >
                          {row.board}
                        </span>
                      </td>

                      <td className="py-3 px-4 font-mono font-semibold text-foreground">
                        ¥{row.open.toFixed(2)}
                      </td>

                      <td className="py-3 px-4">
                        <span
                          className={cn(
                            'font-mono font-bold text-xs px-2 py-0.5 rounded-md inline-flex items-center gap-0.5',
                            isUp
                              ? 'bg-red-500/15 text-red-400 border border-red-500/25'
                              : 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/25'
                          )}
                        >
                          {isUp ? '+' : ''}
                          {row.open_gap_pct.toFixed(2)}%
                        </span>
                      </td>

                      <td className="py-3 px-4">
                        <span
                          className={cn(
                            'px-2 py-0.5 rounded-md text-[11px] font-bold inline-flex items-center gap-1',
                            row.is_core_purple
                              ? 'bg-gradient-to-r from-purple-500/25 to-fuchsia-500/25 text-purple-200 border border-purple-500/50 shadow-[0_0_12px_rgba(168,85,247,0.3)] font-extrabold'
                              : row.is_super_breakout
                              ? 'bg-gradient-to-r from-amber-500/20 via-orange-500/20 to-red-500/20 text-amber-300 border border-amber-500/40 shadow-[0_0_10px_rgba(245,158,11,0.2)] font-extrabold'
                              : row.is_doji
                              ? 'bg-amber-500/15 text-amber-300 border border-amber-500/30'
                              : row.pattern_type === 'bull_body'
                              ? 'bg-red-500/10 text-red-300 border border-red-500/20'
                              : 'bg-emerald-500/10 text-emerald-300 border border-emerald-500/20'
                          )}
                        >
                          {row.pattern}
                        </span>
                      </td>

                      <td className="py-3 px-4 font-mono text-muted text-[11px]">
                        实体 {row.prev_body_pct.toFixed(2)}% / 振幅 {row.prev_amplitude.toFixed(2)}%
                      </td>

                      <td className="py-3 px-4 font-mono font-medium text-foreground">
                        {row.total_mv.toFixed(1)} 亿
                      </td>

                      <td className="py-3 px-4 font-mono font-medium text-foreground">
                        {row.bidding_amount_wan >= 10000
                          ? `${(row.bidding_amount_wan / 10000).toFixed(2)} 亿`
                          : `${row.bidding_amount_wan.toFixed(0)} 万`}
                      </td>

                      <td className="py-3 px-4 font-mono font-medium text-foreground">
                        {row.bidding_vol_ratio >= 10 ? (row.bidding_vol_ratio / 100).toFixed(2) : row.bidding_vol_ratio.toFixed(2)}
                      </td>

                      <td className="py-3 px-4 text-center">
                        <div className={cn(
                          "inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-mono font-bold text-xs",
                          row.is_core_purple
                            ? "bg-purple-500/20 border border-purple-500/40 text-purple-200 shadow-[0_0_8px_rgba(168,85,247,0.25)]"
                            : "bg-gradient-to-r from-orange-500/15 to-red-500/15 border border-orange-500/30 text-amber-300"
                        )}>
                          <Sparkles className={cn("h-3 w-3", row.is_core_purple ? "text-purple-300" : "text-amber-400")} />
                          {row.score}
                        </div>
                      </td>

                      <td className="py-3 px-4 text-center" onClick={(e) => e.stopPropagation()}>
                        <button
                          onClick={() => setPreviewSymbol(row.symbol)}
                          className={cn(
                            "px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors cursor-pointer border",
                            row.is_core_purple
                              ? "bg-purple-500/20 border-purple-500/30 text-purple-200 hover:bg-purple-500 hover:text-white"
                              : "bg-elevated hover:bg-accent hover:text-white border-border"
                          )}
                        >
                          分析/分时
                        </button>
                      </td>
                    </motion.tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* AI 高开逻辑分析弹窗 */}
      {showAiModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-in fade-in duration-200">
          <div className="relative w-full max-w-4xl max-h-[85vh] flex flex-col rounded-2xl border border-border bg-surface shadow-2xl overflow-hidden">
            {/* Modal 顶栏 */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-border bg-elevated/40">
              <div className="flex items-center gap-2.5">
                <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-amber-500 to-red-500 text-white shadow-md">
                  <Sparkles className="h-4 w-4" />
                </div>
                <div>
                  <h3 className="text-base font-bold text-foreground">
                    AI 深度高开与抢筹逻辑剖析
                  </h3>
                  <p className="text-xs text-muted">
                    针对当前筛选出的 {rows.length} 只标的，结合行业资讯、重大政策、公司公告与主力抢筹意图深度推演
                  </p>
                </div>
              </div>
              <button
                onClick={() => setShowAiModal(false)}
                className="h-7 w-7 rounded-lg border border-border text-muted hover:text-foreground hover:bg-elevated flex items-center justify-center transition-colors cursor-pointer"
              >
                ✕
              </button>
            </div>

            {/* Modal 内容区 */}
            <div className="flex-1 overflow-y-auto p-6 space-y-5">
              {isAnalyzing && (
                <div className="py-16 text-center space-y-3">
                  <div className="inline-block h-8 w-8 animate-spin rounded-full border-2 border-accent border-r-transparent" />
                  <div className="text-sm font-semibold text-foreground">
                    大模型正在全网检索公告与题材资讯，深度剖析高开逻辑…
                  </div>
                  <p className="text-xs text-muted">
                    正在分析 {rows.map(r => r.name).join('、')} 的催化背景与竞价量价意图
                  </p>
                </div>
              )}

              {!isAnalyzing && aiAnalysis && (
                <>
                  {/* 整体盘面主线总结 */}
                  {aiAnalysis.market_summary && (
                    <div className="p-4 rounded-xl border border-amber-500/30 bg-gradient-to-r from-amber-500/10 via-orange-500/10 to-red-500/10 space-y-1.5">
                      <div className="flex items-center gap-1.5 text-xs font-bold text-amber-300">
                        <Zap className="h-3.5 w-3.5" />
                        今日竞价抢筹资金主线研判
                      </div>
                      <p className="text-xs text-foreground/90 leading-relaxed">
                        {aiAnalysis.market_summary}
                      </p>
                    </div>
                  )}

                  {/* 个股逻辑卡片列表 */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {(aiAnalysis.items || []).map((item: any) => {
                      const matchedRow = rows.find(r => r.symbol === item.symbol)
                      return (
                        <div
                          key={item.symbol}
                          className="rounded-xl border border-border bg-elevated/40 p-4 space-y-3 hover:border-amber-500/40 transition-colors cursor-pointer"
                          onClick={() => setPreviewSymbol(item.symbol)}
                        >
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <span className="font-bold text-sm text-foreground">
                                {item.name}
                              </span>
                              <span className="font-mono text-xs text-muted">
                                {item.symbol}
                              </span>
                              {matchedRow && (
                                <span className="font-mono font-bold text-xs text-red-400 bg-red-500/10 border border-red-500/20 px-1.5 py-0.5 rounded">
                                  +{matchedRow.open_gap_pct}%
                                </span>
                              )}
                            </div>
                            <span className="text-[11px] font-semibold text-amber-300 bg-amber-500/10 border border-amber-500/25 px-2 py-0.5 rounded-full">
                              {item.logic_rating}
                            </span>
                          </div>

                          <div className="space-y-2 text-xs">
                            <div className="p-2.5 rounded-lg bg-surface/70 border border-border/80 space-y-1">
                              <div className="text-[11px] font-bold text-amber-400">
                                🎯 核心高开原因
                              </div>
                              <p className="text-foreground font-medium">
                                {item.gap_reason}
                              </p>
                            </div>

                            <div className="space-y-1 text-muted">
                              <div className="text-[11px] font-semibold text-secondary">
                                📰 催化背景与公告资讯:
                              </div>
                              <p className="text-foreground/80 leading-relaxed">
                                {item.catalyst_detail}
                              </p>
                            </div>

                            <div className="space-y-1 text-muted">
                              <div className="text-[11px] font-semibold text-emerald-400">
                                🛡️ 盘中应对策略:
                              </div>
                              <p className="text-foreground/80 leading-relaxed">
                                {item.tactics}
                              </p>
                            </div>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </>
              )}
            </div>

            {/* Modal 底栏 */}
            <div className="px-6 py-3 border-t border-border bg-elevated/30 flex items-center justify-between">
              <span className="text-xs text-muted">
                提示：点击任意卡片可直接查看该个股的分时图与量化指标
              </span>
              <button
                onClick={() => setShowAiModal(false)}
                className="px-4 py-1.5 rounded-lg bg-surface hover:bg-elevated border border-border text-xs font-medium text-foreground transition-colors cursor-pointer"
              >
                关闭
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 个股预览弹窗 */}
      {previewSymbol && (
        <StockPreviewDialog
          symbol={previewSymbol}
          onClose={() => setPreviewSymbol(null)}
        />
      )}
    </div>
  )
}
