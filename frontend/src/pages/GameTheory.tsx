import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Flame,
  Snowflake,
  Sparkles,
  RefreshCw,
  Target,
  Compass,
} from 'lucide-react'
import {
  fetchGameTheoryTemperature,
  fetchGameTheoryFearPool,
  fetchGameTheoryDangerList,
  fetchGameTheoryReport,
  fetchGameTheoryStatus,
  triggerGameTheoryAnalysis,
  StockGameScore,
} from '../lib/api'

export default function GameTheory() {
  const queryClient = useQueryClient()
  const [selectedStock, setSelectedStock] = useState<StockGameScore | null>(null)

  // 状态与数据轮询 (15s 自动刷新)
  const { data: status } = useQuery({
    queryKey: ['gameTheoryStatus'],
    queryFn: fetchGameTheoryStatus,
    refetchInterval: 15000,
  })

  const { data: temp } = useQuery({
    queryKey: ['gameTheoryTemp'],
    queryFn: fetchGameTheoryTemperature,
    refetchInterval: 15000,
  })

  const { data: report } = useQuery({
    queryKey: ['gameTheoryReport'],
    queryFn: fetchGameTheoryReport,
    refetchInterval: 15000,
  })

  const { data: fearPool = [] } = useQuery({
    queryKey: ['gameTheoryFearPool'],
    queryFn: () => fetchGameTheoryFearPool(30),
    refetchInterval: 15000,
  })

  const { data: dangerList = [] } = useQuery({
    queryKey: ['gameTheoryDangerList'],
    queryFn: () => fetchGameTheoryDangerList(30),
    refetchInterval: 15000,
  })

  // 触发手动分析
  const triggerMutation = useMutation({
    mutationFn: triggerGameTheoryAnalysis,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['gameTheoryStatus'] })
      queryClient.invalidateQueries({ queryKey: ['gameTheoryTemp'] })
      queryClient.invalidateQueries({ queryKey: ['gameTheoryReport'] })
      queryClient.invalidateQueries({ queryKey: ['gameTheoryFearPool'] })
      queryClient.invalidateQueries({ queryKey: ['gameTheoryDangerList'] })
    },
  })

  // 温度区间颜色与指示
  const getZoneStyle = (zone?: string) => {
    switch (zone) {
      case 'ice':
        return {
          bg: 'from-cyan-500/20 to-blue-500/10 border-cyan-500/30 text-cyan-400',
          badge: 'bg-cyan-500/15 text-cyan-300 border-cyan-500/30',
          indicator: 'bg-cyan-400',
          desc: '极度恐慌 · 绝佳逆向左侧买点',
        }
      case 'cold':
        return {
          bg: 'from-blue-500/20 to-indigo-500/10 border-blue-500/30 text-blue-400',
          badge: 'bg-blue-500/15 text-blue-300 border-blue-500/30',
          indicator: 'bg-blue-400',
          desc: '情绪低迷 · 适合精选低估地量标的',
        }
      case 'warm':
        return {
          bg: 'from-emerald-500/20 to-teal-500/10 border-emerald-500/30 text-emerald-400',
          badge: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
          indicator: 'bg-emerald-400',
          desc: '温和良性 · 结构分化与个股博弈',
        }
      case 'hot':
        return {
          bg: 'from-amber-500/20 to-orange-500/10 border-amber-500/30 text-amber-400',
          badge: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
          indicator: 'bg-amber-400',
          desc: '情绪过热 · 散户蜂拥追高需防冲高回落',
        }
      case 'boiling':
        return {
          bg: 'from-rose-500/20 to-red-500/10 border-rose-500/30 text-rose-400',
          badge: 'bg-rose-500/15 text-rose-300 border-rose-500/30',
          indicator: 'bg-rose-500',
          desc: '极度狂热 · 击鼓传花末端极度危险',
        }
      default:
        return {
          bg: 'from-primary/20 to-elevated border-border text-foreground',
          badge: 'bg-elevated text-muted border-border',
          indicator: 'bg-muted',
          desc: '博弈情绪稳定',
        }
    }
  }

  const zoneStyle = getZoneStyle(temp?.zone)

  return (
    <div className="space-y-6 pb-12">
      {/* 顶部标题与时钟监控 Banner */}
      <div className="relative overflow-hidden rounded-2xl border border-border/80 bg-gradient-to-br from-card via-card/90 to-elevated/40 p-5 backdrop-blur-xl shadow-lg">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <div className="flex items-center gap-2.5 flex-wrap">
              <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-indigo-500/20 text-indigo-400 border border-indigo-500/30 shadow-sm">
                <Target className="h-4 w-4" />
              </span>
              <h1 className="text-xl font-bold tracking-tight text-foreground flex items-center gap-2">
                博弈派 AI 分析引擎
                <span className="text-xs px-2 py-0.5 rounded-full font-normal bg-indigo-500/10 border border-indigo-500/30 text-indigo-300">
                  反指标陷阱 · 散户心理与对手盘
                </span>
              </h1>
            </div>
            <p className="text-xs text-muted mt-1.5 leading-relaxed">
              核心逻辑：<span className="text-cyan-400 font-medium">散户看指标恐慌割肉（破均线止损 / KDJ负值绝望 / MACD洗盘假死叉）= 主力借指标诱空吸筹的好位置</span> ·{' '}
              <span className="text-rose-400 font-medium">散户看指标追高（高位MACD金叉 / KDJ超买 / 假突破接盘）= 主力借指标诱多出货的危险区</span> · 
              <span className="text-foreground font-semibold ml-1">彻底过滤无量死水僵尸股，只做真正发生激烈博弈的标的</span>
            </p>
          </div>

          {/* 右侧：状态指标与操作 */}
          <div className="flex items-center gap-3 text-xs flex-wrap">
            <div className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
              <span className="text-[10px]">🇨🇳 东八区</span>
              <span className="font-mono font-bold">
                {status?.beijing_time ? status.beijing_time.slice(11) : '北京时间'}
              </span>
            </div>

            <div className="h-3.5 w-px bg-border/60" />

            <div className="flex items-center gap-1 text-muted">
              <span>已评分标的:</span>
              <span className="font-mono font-bold text-foreground">{status?.total_scored || 0} 只</span>
            </div>

            <div className="h-3.5 w-px bg-border/60" />

            <button
              onClick={() => triggerMutation.mutate()}
              disabled={triggerMutation.isPending || status?.is_running}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-indigo-600 hover:bg-indigo-500 text-white cursor-pointer transition-all disabled:opacity-50 shadow-md hover:shadow-indigo-500/20"
              title="立即触发一次全维度博弈数据采集与AI研判"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${triggerMutation.isPending || status?.is_running ? 'animate-spin' : ''}`} />
              <span>{triggerMutation.isPending || status?.is_running ? '全网博弈采集中...' : '即刻博弈分析'}</span>
            </button>
          </div>
        </div>
      </div>

      {/* 核心看板：全市场博弈温度计 + AI 报告 */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        {/* 全市场散户博弈温度计仪表卡 (4 cols) */}
        <div className={`lg:col-span-5 rounded-2xl border p-5 backdrop-blur-xl bg-gradient-to-br ${zoneStyle.bg} shadow-md flex flex-col justify-between`}>
          <div>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Compass className="h-4 w-4" />
                <span className="text-xs font-semibold uppercase tracking-wider">全市场散户情绪温度计</span>
              </div>
              <span className={`text-xs px-2.5 py-0.5 rounded-full font-bold border ${zoneStyle.badge}`}>
                {temp?.zone_label || '温和适中'}
              </span>
            </div>

            {/* 温度大字号展示 */}
            <div className="mt-4 flex items-baseline gap-3">
              <div className="font-mono text-5xl font-black tracking-tight flex items-baseline">
                <span>{temp?.temperature !== undefined ? temp.temperature.toFixed(1) : '50.0'}</span>
                <span className="text-2xl ml-0.5 font-normal">°C</span>
              </div>
              <div className="text-xs space-y-0.5">
                <div className="font-medium text-foreground">{zoneStyle.desc}</div>
                <div className="text-muted text-[11px]">0°(极寒冰点) ↔ 100°(极热沸腾)</div>
              </div>
            </div>

            {/* 温度进度条 */}
            <div className="mt-4">
              <div className="h-2.5 w-full bg-black/30 rounded-full overflow-hidden p-0.5 border border-white/10 relative">
                <div
                  className={`h-full rounded-full transition-all duration-700 ${zoneStyle.indicator}`}
                  style={{ width: `${Math.max(3, Math.min(100, temp?.temperature || 50))}%` }}
                />
              </div>
              <div className="flex justify-between text-[10px] text-muted font-mono mt-1">
                <span>0° 冰点恐慌</span>
                <span>50° 均衡</span>
                <span>100° 狂热高潮</span>
              </div>
            </div>

            {/* 5大细分维度进度 */}
            <div className="mt-5 space-y-2 text-xs">
              <div className="flex items-center justify-between text-muted">
                <span>涨停/封板热度 (25%):</span>
                <span className="font-mono font-bold text-foreground">
                  {temp?.limit_up_score ? temp.limit_up_score.toFixed(0) : 50}分 · 涨停{temp?.limit_up_count || 0}家
                </span>
              </div>
              <div className="flex items-center justify-between text-muted">
                <span>最高连板高度 (15%):</span>
                <span className="font-mono font-bold text-foreground">
                  {temp?.consecutive_score ? temp.consecutive_score.toFixed(0) : 50}分 · {temp?.max_consecutive || 0}连板
                </span>
              </div>
              <div className="flex items-center justify-between text-muted">
                <span>融资杠杆情绪 (20%):</span>
                <span className="font-mono font-bold text-foreground">
                  {temp?.margin_score ? temp.margin_score.toFixed(0) : 50}分 · 变动{temp?.margin_change ? (temp.margin_change > 0 ? `+${temp.margin_change.toFixed(2)}%` : `${temp.margin_change.toFixed(2)}%`) : '0%'}
                </span>
              </div>
              <div className="flex items-center justify-between text-muted">
                <span>机构龙虎博弈 (20%):</span>
                <span className="font-mono font-bold text-foreground">
                  {temp?.lhb_inst_score ? temp.lhb_inst_score.toFixed(0) : 50}分 · 净额{(temp?.inst_net_total || 0) > 0 ? `+${((temp?.inst_net_total || 0)/10000).toFixed(0)}万` : `${((temp?.inst_net_total || 0)/10000).toFixed(0)}万`}
                </span>
              </div>
              <div className="flex items-center justify-between text-muted">
                <span>散户人气集中度 (20%):</span>
                <span className="font-mono font-bold text-foreground">
                  {temp?.crowd_score ? temp.crowd_score.toFixed(0) : 50}分
                </span>
              </div>
            </div>
          </div>

          <div className="mt-4 pt-3 border-t border-border/40 flex items-center justify-between text-[11px] text-muted">
            <span>更新时间: {temp?.updated_at || '待采集'}</span>
            <span className="text-emerald-400 font-medium">● 自动实时监控</span>
          </div>
        </div>

        {/* AI 博弈策略日报卡 (7 cols) */}
        <div className="lg:col-span-7 rounded-2xl border border-border/80 bg-card/70 p-5 backdrop-blur-xl shadow-md flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-indigo-400 font-semibold text-xs uppercase tracking-wider">
                <Sparkles className="h-4 w-4" />
                <span>AI 席位行为与散户博弈策略内参</span>
              </div>
              <span className="text-[11px] font-mono text-muted">
                {report?.date || status?.beijing_time?.slice(0, 10)}
              </span>
            </div>

            <div className="mt-4 space-y-4">
              <div className="rounded-xl border border-border/60 bg-elevated/40 p-3.5">
                <div className="text-xs font-semibold text-foreground flex items-center gap-1.5 mb-1.5">
                  <span className="h-2 w-2 rounded-full bg-indigo-400" />
                  今日市场博弈格局
                </div>
                <p className="text-xs text-muted-foreground leading-relaxed">
                  {report?.market_summary || '正在采集全市场龙虎榜、东财人气榜与融资数据生成今日博弈格局...'}
                </p>
              </div>

              <div className="rounded-xl border border-indigo-500/20 bg-indigo-500/5 p-3.5">
                <div className="text-xs font-semibold text-indigo-300 flex items-center gap-1.5 mb-1.5">
                  <span className="h-2 w-2 rounded-full bg-emerald-400" />
                  明日博弈实操战术
                </div>
                <p className="text-xs text-indigo-200/90 leading-relaxed">
                  {report?.strategy_advice || '建议重点关注散户恐惧区中出现地量萎缩且机构逆势收集的品种，避开高位放量散户扎堆追高的标的。'}
                </p>
              </div>
            </div>
          </div>

          <div className="mt-4 pt-3 border-t border-border/40 flex items-center justify-between text-xs text-muted">
            <div className="flex items-center gap-4">
              <span>
                散户恐惧好位置: <strong className="text-cyan-400 font-mono">{fearPool.length}</strong> 只
              </span>
              <span>
                散户扎堆危险区: <strong className="text-rose-400 font-mono">{dangerList.length}</strong> 只
              </span>
            </div>
            <span className="text-[11px]">大模型实时分析</span>
          </div>
        </div>
      </div>

      {/* 核心双栏：散户恐惧区 (潜在好位置) vs 散户拥挤区 (危险规避) */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* 左栏：散户恐惧区 · 逆向买入池 */}
        <div className="rounded-2xl border border-cyan-500/30 bg-gradient-to-b from-cyan-950/20 via-card to-card p-5 backdrop-blur-xl shadow-md">
          <div className="flex items-center justify-between pb-3 border-b border-cyan-500/20">
            <div className="flex items-center gap-2">
              <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-cyan-500/15 text-cyan-400 border border-cyan-500/30">
                <Snowflake className="h-4 w-4" />
              </span>
              <div>
                <h2 className="text-base font-bold text-cyan-400 flex items-center gap-2">
                  散户恐慌割肉区 · 反指标买入机会
                  <span className="text-xs px-2 py-0.5 rounded-full bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 font-normal">
                    {fearPool.length} 只标的
                  </span>
                </h2>
                <p className="text-[11px] text-muted">
                  假破MA20均线诱空 / KDJ极端恐慌负值 / 日内大跳水探底神针 / MACD洗盘假死叉
                </p>
              </div>
            </div>
          </div>

          {/* 列表 */}
          <div className="mt-3 space-y-2.5 max-h-[620px] overflow-y-auto pr-1">
            {fearPool.length === 0 ? (
              <div className="py-12 text-center text-xs text-muted">
                暂无达到恐惧阈值的标的，点击右上角「即刻博弈分析」拉取最新数据
              </div>
            ) : (
              fearPool.map((stock) => (
                <div
                  key={stock.symbol}
                  onClick={() => setSelectedStock(stock)}
                  className="group rounded-xl border border-cyan-500/20 bg-cyan-500/5 hover:bg-cyan-500/10 p-3.5 transition-all cursor-pointer hover:border-cyan-500/40 hover:shadow-md hover:shadow-cyan-500/5"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-foreground text-sm group-hover:text-cyan-400 transition-colors">
                        {stock.name}
                      </span>
                      <span className="font-mono text-xs text-muted">{stock.symbol}</span>
                      {stock.fear_index >= 60 && (
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-cyan-400/20 text-cyan-300 border border-cyan-400/30">
                          ⭐ 极度恐慌好位置
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 font-mono">
                      <span className="text-xs font-bold text-foreground">
                        ¥{stock.close ? stock.close.toFixed(2) : '--'}
                      </span>
                      <span
                        className={`text-xs font-bold ${
                          stock.change_pct >= 0 ? 'text-rose-400' : 'text-emerald-400'
                        }`}
                      >
                        {stock.change_pct >= 0 ? `+${stock.change_pct.toFixed(2)}%` : `${stock.change_pct.toFixed(2)}%`}
                      </span>
                    </div>
                  </div>

                  {/* 核心反指标指标栏 */}
                  <div className="mt-2 flex items-center gap-3 text-[11px] font-mono text-muted">
                    {stock.amount ? (
                      <span>成交: <strong className="text-foreground">¥{(stock.amount / 1e8).toFixed(2)}亿</strong></span>
                    ) : null}
                    {stock.amplitude ? (
                      <span>振幅: <strong className="text-foreground">{stock.amplitude.toFixed(1)}%</strong></span>
                    ) : null}
                    {stock.kdj_j !== undefined ? (
                      <span>KDJ J: <strong className={stock.kdj_j <= 0 ? 'text-rose-400 font-bold' : 'text-cyan-300'}>{stock.kdj_j.toFixed(1)}</strong></span>
                    ) : null}
                  </div>

                  {/* 恐惧指数指标条 */}
                  <div className="mt-2 flex items-center gap-3">
                    <div className="flex-1">
                      <div className="flex justify-between text-[10px] text-muted mb-1">
                        <span>散户恐惧指数:</span>
                        <span className="font-mono font-bold text-cyan-400">{stock.fear_index.toFixed(0)} / 100</span>
                      </div>
                      <div className="h-1.5 w-full bg-black/40 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-gradient-to-r from-cyan-500 to-blue-400 rounded-full"
                          style={{ width: `${stock.fear_index}%` }}
                        />
                      </div>
                    </div>

                    <div className="text-[11px] font-mono text-muted pl-2 border-l border-border/40">
                      换手: <strong className="text-foreground">{stock.turnover_rate ? `${stock.turnover_rate.toFixed(2)}%` : '--'}</strong>
                    </div>
                  </div>

                  {/* 信号原因标签 */}
                  <div className="mt-2.5 flex items-center gap-1.5 flex-wrap">
                    {stock.signal_reasons?.slice(0, 3).map((r, idx) => (
                      <span
                        key={idx}
                        className="px-2 py-0.5 rounded-md text-[10px] bg-cyan-950/40 text-cyan-300/90 border border-cyan-500/20"
                      >
                        {r}
                      </span>
                    ))}
                    {stock.inst_net_amount > 0 && (
                      <span className="px-2 py-0.5 rounded-md text-[10px] bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 font-mono">
                        机构逆买 ¥{(stock.inst_net_amount / 10000).toFixed(0)}万
                      </span>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {/* 右栏：散户拥挤区 · 危险规避清单 */}
        <div className="rounded-2xl border border-rose-500/30 bg-gradient-to-b from-rose-950/20 via-card to-card p-5 backdrop-blur-xl shadow-md">
          <div className="flex items-center justify-between pb-3 border-b border-rose-500/20">
            <div className="flex items-center gap-2">
              <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-rose-500/15 text-rose-400 border border-rose-500/30">
                <Flame className="h-4 w-4" />
              </span>
              <div>
                <h2 className="text-base font-bold text-rose-400 flex items-center gap-2">
                  散户狂热追高区 · 反指标诱多危险
                  <span className="text-xs px-2 py-0.5 rounded-full bg-rose-500/20 text-rose-300 border border-rose-500/30 font-normal">
                    {dangerList.length} 只标的
                  </span>
                </h2>
                <p className="text-[11px] text-muted">
                  高位MACD假金叉 / KDJ极度超买高潮 / 假突破长上影 / 散户蜂拥扎堆接盘
                </p>
              </div>
            </div>
          </div>

          {/* 列表 */}
          <div className="mt-3 space-y-2.5 max-h-[620px] overflow-y-auto pr-1">
            {dangerList.length === 0 ? (
              <div className="py-12 text-center text-xs text-muted">
                当前暂无极度拥挤危险标的，市场投机狂热度处于可控状态
              </div>
            ) : (
              dangerList.map((stock) => (
                <div
                  key={stock.symbol}
                  onClick={() => setSelectedStock(stock)}
                  className="group rounded-xl border border-rose-500/20 bg-rose-500/5 hover:bg-rose-500/10 p-3.5 transition-all cursor-pointer hover:border-rose-500/40 hover:shadow-md hover:shadow-rose-500/5"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-foreground text-sm group-hover:text-rose-400 transition-colors">
                        {stock.name}
                      </span>
                      <span className="font-mono text-xs text-muted">{stock.symbol}</span>
                      {stock.hot_rank > 0 && stock.hot_rank <= 20 && (
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-rose-500/20 text-rose-300 border border-rose-500/30">
                          🔥 人气 Top {stock.hot_rank}
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 font-mono">
                      <span className="text-xs font-bold text-foreground">
                        ¥{stock.close ? stock.close.toFixed(2) : '--'}
                      </span>
                      <span
                        className={`text-xs font-bold ${
                          stock.change_pct >= 0 ? 'text-rose-400' : 'text-emerald-400'
                        }`}
                      >
                        {stock.change_pct >= 0 ? `+${stock.change_pct.toFixed(2)}%` : `${stock.change_pct.toFixed(2)}%`}
                      </span>
                    </div>
                  </div>

                  {/* 核心反指标指标栏 */}
                  <div className="mt-2 flex items-center gap-3 text-[11px] font-mono text-muted">
                    {stock.amount ? (
                      <span>成交: <strong className="text-foreground">¥{(stock.amount / 1e8).toFixed(2)}亿</strong></span>
                    ) : null}
                    {stock.turnover_rate ? (
                      <span>换手: <strong className="text-rose-400">{stock.turnover_rate.toFixed(1)}%</strong></span>
                    ) : null}
                    {stock.kdj_j !== undefined ? (
                      <span>KDJ J: <strong className={stock.kdj_j >= 95 ? 'text-rose-400 font-bold' : 'text-foreground'}>{stock.kdj_j.toFixed(1)}</strong></span>
                    ) : null}
                  </div>

                  {/* 拥挤指数指标条 */}
                  <div className="mt-2 flex items-center gap-3">
                    <div className="flex-1">
                      <div className="flex justify-between text-[10px] text-muted mb-1">
                        <span>散户拥挤指数:</span>
                        <span className="font-mono font-bold text-rose-400">{stock.greed_index.toFixed(0)} / 100</span>
                      </div>
                      <div className="h-1.5 w-full bg-black/40 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-gradient-to-r from-amber-500 to-rose-500 rounded-full"
                          style={{ width: `${stock.greed_index}%` }}
                        />
                      </div>
                    </div>
                  </div>

                  {/* 信号原因标签 */}
                  <div className="mt-2.5 flex items-center gap-1.5 flex-wrap">
                    {stock.signal_reasons?.slice(0, 3).map((r, idx) => (
                      <span
                        key={idx}
                        className="px-2 py-0.5 rounded-md text-[10px] bg-rose-950/40 text-rose-300/90 border border-rose-500/20"
                      >
                        {r}
                      </span>
                    ))}
                    {stock.inst_net_amount < 0 && (
                      <span className="px-2 py-0.5 rounded-md text-[10px] bg-rose-500/15 text-rose-300 border border-rose-500/30 font-mono">
                        机构高位净卖 ¥{Math.abs(stock.inst_net_amount / 10000).toFixed(0)}万
                      </span>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {/* 个股博弈多维雷达详情模态弹窗 */}
      {selectedStock && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="w-full max-w-lg rounded-2xl border border-border bg-card p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between border-b border-border/60 pb-3">
              <div>
                <h3 className="text-lg font-bold text-foreground flex items-center gap-2">
                  {selectedStock.name}
                  <span className="text-xs font-mono text-muted">{selectedStock.symbol}</span>
                </h3>
                <p className="text-xs text-muted mt-0.5">博弈多维量化剖析</p>
              </div>
              <button
                onClick={() => setSelectedStock(null)}
                className="rounded-lg p-1.5 text-muted hover:bg-elevated hover:text-foreground cursor-pointer"
              >
                ✕
              </button>
            </div>

            {/* 双核心评分条 */}
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-xl border border-cyan-500/30 bg-cyan-500/10 p-3">
                <div className="text-xs text-cyan-400 font-medium">散户恐惧指数</div>
                <div className="text-2xl font-black font-mono text-cyan-300 mt-1">
                  {selectedStock.fear_index.toFixed(0)}
                  <span className="text-xs font-normal text-muted ml-1">/ 100</span>
                </div>
                <div className="text-[10px] text-muted mt-1">
                  {selectedStock.fear_index >= 50 ? '散户不敢买 · 潜在好位置' : '散户未见明显恐慌'}
                </div>
              </div>

              <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-3">
                <div className="text-xs text-rose-400 font-medium">散户拥挤指数</div>
                <div className="text-2xl font-black font-mono text-rose-300 mt-1">
                  {selectedStock.greed_index.toFixed(0)}
                  <span className="text-xs font-normal text-muted ml-1">/ 100</span>
                </div>
                <div className="text-[10px] text-muted mt-1">
                  {selectedStock.greed_index >= 50 ? '散户扎堆蜂拥 · 极度危险' : '未见散户盲目追高'}
                </div>
              </div>
            </div>

            {/* 反指标与散户心理博弈量化剖析表 */}
            <div className="rounded-xl border border-border/60 bg-elevated/30 p-3.5 space-y-2.5 text-xs">
              <div className="font-semibold text-foreground mb-1 flex items-center justify-between">
                <span>反指标与散户心理博弈剖析:</span>
                <span className="text-[10px] text-muted font-normal">排除无量死水 · 聚焦真实对手盘</span>
              </div>
              <div className="flex justify-between items-center text-muted">
                <span>1. 真实活跃流动性:</span>
                <span className="font-mono font-bold text-foreground">
                  成交 ¥{selectedStock.amount ? `${(selectedStock.amount / 1e8).toFixed(2)}亿` : '--'} · 换手 {selectedStock.turnover_rate ? `${selectedStock.turnover_rate.toFixed(2)}%` : '--'} · 振幅 {selectedStock.amplitude ? `${selectedStock.amplitude.toFixed(1)}%` : '--'}
                </span>
              </div>
              <div className="flex justify-between items-center text-muted">
                <span>2. KDJ 极端恐慌 / 超买:</span>
                <span className="font-mono font-bold text-foreground">
                  J值 {selectedStock.kdj_j !== undefined ? selectedStock.kdj_j.toFixed(1) : '--'} {selectedStock.kdj_j !== undefined && selectedStock.kdj_j <= 0 ? '(极端负值恐慌割肉)' : selectedStock.kdj_j !== undefined && selectedStock.kdj_j >= 95 ? '(极度超买亢奋追高)' : ''}
                </span>
              </div>
              <div className="flex justify-between items-center text-muted">
                <span>3. MACD 假死叉 / 假金叉:</span>
                <span className="font-mono font-bold text-foreground">
                  MACD柱 {selectedStock.macd_hist !== undefined ? selectedStock.macd_hist.toFixed(3) : '--'}
                </span>
              </div>
              <div className="flex justify-between items-center text-muted">
                <span>4. 龙虎榜主力席位对决:</span>
                <span className="font-mono font-bold text-foreground">
                  {selectedStock.inst_net_amount ? (selectedStock.inst_net_amount > 0 ? `机构逆势扫货 +¥${(selectedStock.inst_net_amount / 10000).toFixed(0)}万` : `机构出逃 -¥${Math.abs(selectedStock.inst_net_amount / 10000).toFixed(0)}万`) : '无近期龙虎席位'}
                </span>
              </div>
              <div className="flex justify-between items-center text-muted">
                <span>5. 散户人气与雪球舆论:</span>
                <span className="font-mono font-bold text-foreground">
                  东财人气 {selectedStock.hot_rank ? `Top ${selectedStock.hot_rank}` : '无人问津'} · 雪球讨论 {selectedStock.xq_tweet ? `${selectedStock.xq_tweet}条` : '冷清'}
                </span>
              </div>
              <div className="flex justify-between items-center text-muted">
                <span>6. 5日量比与筹码衰竭:</span>
                <span className="font-mono font-bold text-foreground">
                  量比 {selectedStock.vol_ratio_5d ? `${selectedStock.vol_ratio_5d.toFixed(2)}x` : '--'} {selectedStock.vol_ratio_5d && selectedStock.vol_ratio_5d <= 0.55 ? '(缩至极度地量)' : ''}
                </span>
              </div>
            </div>

            {/* 触发的所有原因清单 */}
            <div>
              <div className="text-xs font-semibold text-foreground mb-2">博弈信号理由:</div>
              <div className="flex flex-wrap gap-1.5">
                {selectedStock.signal_reasons?.map((r, i) => (
                  <span key={i} className="px-2.5 py-1 rounded-md text-xs bg-card border border-border text-foreground">
                    {r}
                  </span>
                ))}
              </div>
            </div>

            <div className="pt-3 border-t border-border/60 flex justify-end">
              <button
                onClick={() => setSelectedStock(null)}
                className="px-4 py-1.5 rounded-lg text-xs font-medium bg-elevated hover:bg-border text-foreground transition-all cursor-pointer"
              >
                关闭
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
