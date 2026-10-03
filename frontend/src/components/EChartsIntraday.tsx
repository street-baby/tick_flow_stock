import { useEffect, useMemo, useRef, useState } from 'react'
import * as echarts from 'echarts'
import type { ECharts, EChartsOption } from 'echarts'
import type { MinuteKlineRow, PriceLimitInfo } from '@/lib/api'
import { useChartTheme, type ChartTheme } from '@/lib/theme'

type YMode = 'adaptive' | 'limit'
/** cn = A股固定 9:30~15:00 242 槽时间轴; crypto = 按数据自身 UTC 时间滚动轴 (24/7) */
type AxisMode = 'cn' | 'crypto'
/**
 * 分时均价口径。
 * - vwap: 累计成交额 / 累计成交量, 适用于「成交量与价格同量纲」的标的 (个股/ETF/crypto)。
 * - amount-weighted: 成交额加权均价 Σ(价×额)/Σ额, 用于指数 —— 指数成交量是成分股股数之和,
 *   额/量 得到的是全市场每股均价 (~17 元), 与指数点位 (~3900) 不同量纲。
 */
type AvgMode = 'vwap' | 'amount-weighted'

// 序列颜色 (双主题通用); 画布轴/网格/十字线等主题相关色走 ChartTheme
const THEME = {
  line: '#3B82F6',
  areaFill: 'rgba(59,130,246,0.40)',
  avgLine: '#F59E0B',
  volUp: 'rgba(240,68,56,0.6)',
  volDown: 'rgba(18,183,106,0.6)',
}

interface Props {
  data: MinuteKlineRow[]
  height?: number
  prevClose?: number
  date?: string
  priceLimit?: PriceLimitInfo
  onPriceHover?: (price: number | null) => void
  showLimitLines?: boolean
  showAvgLine?: boolean
  /** crypto: UTC 滚动时间轴 + 无涨跌停语义 + 小额价格自适应精度 (默认 cn) */
  mode?: AxisMode
  /** 均价口径, 默认 vwap; 指数分时必须传 amount-weighted (见 AvgMode) */
  avgMode?: AvgMode
}

function fmtTime(dt: string): string {
  const match = dt.match(/(?:T|\s)?(\d{2}):(\d{2})/)
  if (!match) return dt.slice(11, 16)
  const rawH = parseInt(match[1], 10)
  // 若时间已经是北京时间 (9点~15点)，直接使用；若为 UTC 时间 (1点~7点)，加 8 小时转北京时间
  const h = rawH >= 9 && rawH <= 15 ? rawH : (rawH + 8) % 24
  return `${String(h).padStart(2, '0')}:${match[2]}`
}

function computeAvgPrice(data: MinuteKlineRow[], volScale = 100, mode: AvgMode = 'vwap'): number[] {
  // vwap: 累计成交额 / 累计成交量。cn 个股: volume 单位是手 → ×100 转股;
  //       crypto: volume 是币量, amount 是 USDT → volScale=1。
  // amount-weighted: 指数专用, 见 AvgMode 注释。
  const result: number[] = []
  let sumAmt = 0
  let sumVol = 0
  let sumWeighted = 0
  for (const d of data) {
    sumAmt += d.amount
    sumVol += d.volume * volScale
    sumWeighted += d.close * d.amount
    if (mode === 'amount-weighted' && sumAmt > 0) {
      result.push(sumWeighted / sumAmt)
    } else {
      result.push(sumVol > 0 ? sumAmt / sumVol : d.close)
    }
  }
  return result
}

/**
 * 均价是否与价格同量纲: VWAP 按定义落在当日 [最低价, 最高价] 内, 越界即说明该数据源的
 * amount/volume 口径与价格不一致 (如指数)。此时不画均价线, 也不能让它参与 Y 轴范围计算,
 * 否则一根 ~17 元的均价线会把 ±0.5% 的指数分时图撑到 ±100%, 价格线被压成横线。
 */
function isAvgInPriceRange(data: MinuteKlineRow[], avgPrices: number[]): boolean {
  let lo = Infinity
  let hi = -Infinity
  for (const d of data) {
    for (const v of [d.low, d.high, d.close]) {
      if (!isValidPrice(v)) continue
      if (v < lo) lo = v
      if (v > hi) hi = v
    }
  }
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return false
  const tolerance = (hi - lo) * 0.05
  const inside = avgPrices.filter(v => isValidPrice(v) && v >= lo - tolerance && v <= hi + tolerance).length
  return inside * 2 >= avgPrices.length
}

/** 价格自适应精度: A股 2 位小数不变; crypto 小额币 (0.0012) 不至于显示成 0.00 */
function fmtPx(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '—'
  if (v === 0) return '0.00'
  const abs = Math.abs(v)
  if (abs < 0.0001) return v.toFixed(6)
  if (abs < 0.01) return v.toFixed(5)
  if (abs < 1) return v.toFixed(4)
  return v.toFixed(2)
}

function fmtAmt(v: number): string {
  if (v >= 1_000_000_000) return `${(v / 1_000_000_000).toFixed(2)}亿`
  if (v >= 10_000) return `${(v / 10_000).toFixed(0)}万`
  return v.toFixed(0)
}

function isValidPrice(v: number | null | undefined): v is number {
  return typeof v === 'number' && Number.isFinite(v) && v > 0
}

/** 生成全天分时时间刻度 9:30 ~ 11:30, 13:00 ~ 15:00, 每分钟一个点 (共242个) */
function generateFullDayTimes(): string[] {
  const times: string[] = []
  // 上午 9:30 ~ 11:30 (121 分钟)
  for (let h = 9; h <= 11; h++) {
    const startM = h === 9 ? 30 : 0
    const endM = h === 11 ? 30 : 59
    for (let m = startM; m <= endM; m++) {
      times.push(`${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`)
    }
  }
  // 下午 13:00 ~ 15:00 (121 分钟)
  for (let h = 13; h <= 15; h++) {
    const endM = h === 15 ? 0 : 59
    for (let m = 0; m <= endM; m++) {
      times.push(`${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`)
    }
  }
  return times
}

const FULL_DAY_TIMES = generateFullDayTimes()

/** 计算实际涨跌停价 (四舍五入到2位小数) 和实际涨跌停幅度 */
function getLimitPrices(prevClose: number, priceLimit?: PriceLimitInfo): {
  limitUp: number      // 涨停价 (四舍五入)
  limitDown: number    // 跌停价 (四舍五入)
  upPct: number        // 实际涨停幅度 (如 9.97)
  downPct: number      // 实际跌停幅度 (如 -9.97)
} {
  const pct = priceLimit && Number.isFinite(priceLimit.rate) ? priceLimit.rate : 0.10
  const rawUp = prevClose * (1 + pct)
  const rawDown = prevClose * (1 - pct)
  // A股涨跌停价四舍五入到分 (2位小数)
  const limitUp = isValidPrice(priceLimit?.limit_up)
    ? priceLimit.limit_up
    : Math.round(rawUp * 100) / 100
  const limitDown = isValidPrice(priceLimit?.limit_down)
    ? priceLimit.limit_down
    : Math.round(rawDown * 100) / 100
  const upPct = (limitUp - prevClose) / prevClose * 100
  const downPct = (limitDown - prevClose) / prevClose * 100
  return { limitUp, limitDown, upPct, downPct }
}

function buildOption(data: MinuteKlineRow[], prevClose: number | undefined, avgPrices: number[], lineColor: string, areaColor: string, yMode: YMode, ct: ChartTheme, priceLimit?: PriceLimitInfo, showLimitLines = true, showAvgLine = true, mode: AxisMode = 'cn'): EChartsOption {
  // 将数据映射到全天时间轴上的正确位置
  // crypto: 类目轴直接用数据自身时间标签 (UTC, 每分钟一根), 不做 A 股 242 槽对齐
  const axisTimes = mode === 'crypto' ? data.map(d => fmtTime(d.datetime)) : FULL_DAY_TIMES
  const timeIndexMap = new Map(axisTimes.map((t, i) => [t, i]))
  const closes = new Array(axisTimes.length).fill(null) as (number | null)[]
  const highs = new Array(axisTimes.length).fill(null) as (number | null)[]
  const lows = new Array(axisTimes.length).fill(null) as (number | null)[]
  const avgData = new Array(axisTimes.length).fill(null) as (number | null)[]
  const volumes = new Array(axisTimes.length).fill(null) as (any | null)[]

  const volNeutral = 'rgba(161,161,170,0.5)'
  for (let i = 0; i < data.length; i++) {
    const timeKey = fmtTime(data[i].datetime)
    const idx = timeIndexMap.get(timeKey)
    if (idx !== undefined) {
      closes[idx] = data[i].close
      highs[idx] = data[i].high
      lows[idx] = data[i].low
      avgData[idx] = avgPrices[i]
      volumes[idx] = {
        value: data[i].volume,
        itemStyle: {
          color: data[i].close > data[i].open ? THEME.volUp : data[i].close < data[i].open ? THEME.volDown : volNeutral,
        },
      }
    }
  }

  const areaStyle: any = {
    color: {
      type: 'linear',
      x: 0, y: 0, x2: 0, y2: 1,
      colorStops: [
        { offset: 0, color: areaColor },
        { offset: 1, color: 'rgba(0,0,0,0)' },
      ],
    },
  }

  const markLineData: any[] = []
  if (prevClose != null) {
    markLineData.push({
      yAxis: prevClose,
      lineStyle: { color: ct.crosshair, type: 'dashed', width: 1 },
      label: { show: false },
      symbol: 'none',
    })
  }

  let yMin: number | undefined
  let yMax: number | undefined
  let maxDiff = 0
  if (isValidPrice(prevClose) && data.length > 0) {
    const priceArrays = showAvgLine ? [closes, highs, lows, avgData] : [closes, highs, lows]
    for (const arr of priceArrays) {
      for (const v of arr) {
        if (!isValidPrice(v)) continue
        const diff = Math.abs(v - prevClose)
        if (diff > maxDiff) maxDiff = diff
      }
    }

    if (showLimitLines && yMode === 'limit' && mode !== 'crypto') {
      const { limitUp, limitDown } = getLimitPrices(prevClose, priceLimit)
      const limitDiffUp = limitUp - prevClose
      const limitDiffDown = prevClose - limitDown
      const limitDiff = Math.max(limitDiffUp, limitDiffDown)
      // 涨跌停模式: Y 轴按实际涨跌停价
      maxDiff = limitDiff
      yMin = prevClose - maxDiff
      yMax = prevClose + maxDiff
      // 加 markLine 标注涨停价和跌停价 (仅虚线, 不显示文字)
      markLineData.push(
        {
          yAxis: limitUp,
          lineStyle: { color: 'rgba(199,64,64,0.4)', type: 'dashed', width: 1 },
          label: { show: false },
          symbol: 'none',
        },
        {
          yAxis: limitDown,
          lineStyle: { color: 'rgba(45,155,101,0.4)', type: 'dashed', width: 1 },
          label: { show: false },
          symbol: 'none',
        },
      )
    } else {
      // 自适应模式: Y 轴按实际涨跌幅对称。crypto 无涨跌停, 直接自适应 ±10% 余量。
      if (showLimitLines && mode !== 'crypto') {
        const { limitUp, limitDown } = getLimitPrices(prevClose, priceLimit)
        const limitDiff = Math.max(limitUp - prevClose, prevClose - limitDown)
        maxDiff = Math.min(maxDiff, limitDiff)
      }
      if ((!showLimitLines || mode === 'crypto') && maxDiff > 0) {
        maxDiff *= 1.1
      }
      // 至少保证一个可视范围 (防止数据平时 maxDiff=0)。指数不使用涨跌停范围，最小范围要更紧，否则低波动指数会被压成横线。
      const minDiff = showLimitLines && mode !== 'crypto' ? prevClose * 0.01 : prevClose * 0.001
      if (maxDiff < minDiff) maxDiff = minDiff
      yMin = prevClose - maxDiff
      yMax = prevClose + maxDiff
    }
  }

  // x 轴标签: 9:30, 10:30, 11:30/13:00, 14:00, 15:00
  // 11:30(idx 120) 和 13:00(idx 121) 相邻会重叠, 合并为一个标签
  // crypto: 类目轴 label 全部隐藏, 由 axisPointer 十字线按槽位显示时间 (轴是数据自适应的)
  const xAxisLabelMap: Record<number, string> = mode === 'crypto'
    ? {}
    : {
        0: '9:30',
        60: '10:30',
        120: '11:30/13:00',
        181: '14:00',
        241: '15:00',
      }
  const xAxisLabelFormatter = (_value: string, idx: number) => {
    return xAxisLabelMap[idx] ?? ''
  }

  return {
    animation: false,
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'transparent',
      borderWidth: 0,
      textStyle: { fontSize: 0 },
      formatter: () => '',
      axisPointer: {
        type: 'cross',
        label: {
          show: true,
          backgroundColor: ct.tooltipBg,
          borderColor: ct.tooltipBorder,
          borderWidth: 1,
          padding: [2, 5],
          color: ct.tooltipText,
          fontSize: 10,
          fontFamily: 'JetBrains Mono, monospace',
        },
        crossStyle: { color: ct.crosshair, type: 'dashed', width: 1 },
        lineStyle: { color: ct.crosshair, type: 'dashed', width: 1 },
      },
    },
    axisPointer: {
      link: [{ xAxisIndex: 'all' }],
    },
    grid: [
      { left: 60, right: 55, top: 24, bottom: '28%' },
      { left: 60, right: 55, top: '74%', bottom: 20 },
    ],
    xAxis: [
      {
        type: 'category',
        data: axisTimes,
        boundaryGap: false,
        axisPointer: {
          show: true,
          lineStyle: { color: ct.crosshair, type: 'dashed', width: 1 },
          label: {
            show: true,
            backgroundColor: ct.tooltipBg,
            borderColor: ct.tooltipBorder,
            borderWidth: 1,
            padding: [2, 4],
            color: ct.tooltipText,
            fontSize: 10,
            fontFamily: 'JetBrains Mono, monospace',
            formatter: (params: any) => {
              return params.value ?? ''
            },
          },
        },
        axisLine: { show: false },
        axisLabel: {
          color: ct.text,
          fontSize: 10,
          fontFamily: 'JetBrains Mono, monospace',
          formatter: xAxisLabelFormatter,
          interval: 0,
        },
        axisTick: { show: false },
        splitLine: {
          show: true,
          lineStyle: { color: ct.grid },
        },
      },
      {
        type: 'category',
        gridIndex: 1,
        data: axisTimes,
        boundaryGap: false,
        axisLine: { show: false },
        axisLabel: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
      },
    ],
    yAxis: [
      {
        type: 'value',
        min: yMin,
        max: yMax,
        interval: maxDiff || undefined,
        splitArea: { show: false },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { lineStyle: { color: ct.grid } },
        axisPointer: {
          label: {
            formatter: (params: any) => {
              const v = params.value
              return typeof v === 'number' ? fmtPx(v) : ''
            },
          },
        },
        axisLabel: {
          color: ct.text,
          fontSize: 10,
          fontFamily: 'JetBrains Mono, monospace',
          formatter: (v: number) => fmtPx(v),
        },
      },
      {
        scale: true,
        gridIndex: 1,
        splitNumber: 2,
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
        axisLabel: { show: false },
      },
      ...(isValidPrice(prevClose) && yMin != null && yMax != null ? [{
        type: 'value' as const,
        position: 'right' as const,
        gridIndex: 0,
        min: yMin,
        max: yMax,
        interval: maxDiff || undefined,
        splitArea: { show: false },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { show: false },
        axisPointer: {
          label: {
            formatter: (params: any) => {
              const v = params.value
              if (typeof v !== 'number') return ''
              const pct = (v - prevClose) / prevClose * 100
              if (Math.abs(pct) < 0.01) return '0.00%'
              return (pct > 0 ? '+' : '') + pct.toFixed(2) + '%'
            },
          },
        },
        axisLabel: {
          color: ct.text,
          fontSize: 10,
          fontFamily: 'JetBrains Mono, monospace',
          formatter: (v: number) => {
            const pct = (v - prevClose) / prevClose * 100
            if (Math.abs(pct) < 0.01) return '0.00%'
            return (pct > 0 ? '+' : '') + pct.toFixed(2) + '%'
          },
        },
      }] : []),
    ],
    series: [
      {
        name: '价格',
        type: 'line',
        data: closes,
        smooth: false,
        symbol: 'none',
        cursor: 'crosshair',
        lineStyle: { width: 1.2, color: lineColor },
        areaStyle,
        connectNulls: true,
        markLine: markLineData.length > 0 ? { symbol: 'none', data: markLineData, animation: false, silent: true } : undefined,
      },
      ...(showAvgLine ? [{
        name: '均价',
        type: 'line' as const,
        data: avgData,
        smooth: false,
        symbol: 'none',
        cursor: 'crosshair',
        lineStyle: { width: 1, color: THEME.avgLine },
        connectNulls: true,
      }] : []),
      {
        name: '成交量',
        type: 'bar',
        data: volumes,
        xAxisIndex: 1,
        yAxisIndex: 1,
        cursor: 'crosshair',
      },
    ],
  }
}

export function EChartsIntraday({ data, height = 320, prevClose, date, priceLimit, onPriceHover, showLimitLines = true, showAvgLine = true, mode = 'cn', avgMode = 'vwap' }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<ECharts | null>(null)
  const roRef = useRef<ResizeObserver | null>(null)
  const moRef = useRef<MutationObserver | null>(null)
  const dataRef = useRef(data)
  dataRef.current = data
  const onPriceHoverRef = useRef(onPriceHover)
  onPriceHoverRef.current = onPriceHover
  // 全日索引 → 数据数组索引 的映射 (ref 避免重建 chart)
  const fullDayToDataIdx = useRef<Map<number, number>>(new Map())

  const [infoIdx, setInfoIdx] = useState(data.length - 1)
  const [yMode, setYMode] = useState<YMode>('adaptive')
  const ct = useChartTheme()
  // cn: volume 单位是手(×100 转股); crypto: volume 是币量, amount 已是 USDT 计价额
  const avgPrices = useMemo(() => computeAvgPrice(data, mode === 'crypto' ? 1 : 100, avgMode), [data, mode, avgMode])
  // 均价与价格不同量纲时不画均价线 (也不参与 Y 轴范围), 见 isAvgInPriceRange
  const showAvg = showAvgLine && isAvgInPriceRange(data, avgPrices)

  // 分时线颜色：基于最新价 vs 昨收
  const lastClose = data.length > 0 ? data[data.length - 1].close : null
  const lineIsUp = lastClose != null && prevClose != null ? lastClose > prevClose : true
  const lineIsFlat = lastClose != null && prevClose != null ? lastClose === prevClose : false
  const lineColor = lineIsFlat ? '#A1A1AA' : lineIsUp ? '#C74040' : '#2D9B65'
  const areaFill = lineIsFlat ? 'rgba(180,180,190,0.40)' : lineIsUp ? 'rgba(199,64,64,0.40)' : 'rgba(34,197,94,0.40)'

  useEffect(() => {
    setInfoIdx(data.length - 1)
  }, [data.length])

  useEffect(() => {
    const el = containerRef.current
    if (!el) return

    let chart = chartRef.current
    if (!chart) {
      chart = echarts.init(el, undefined, { renderer: 'canvas' })
      chartRef.current = chart
      // 强制 canvas 使用十字光标，覆盖 ECharts 默认的 pointer
      const forceCursor = () => {
        const canvases = el.querySelectorAll('canvas')
        canvases.forEach(c => { c.style.setProperty('cursor', 'crosshair', 'important') })
      }
      forceCursor()
      // MutationObserver: ECharts 内部可能重建/修改 canvas 属性，持续强制 cursor
      const mo = new MutationObserver(forceCursor)
      mo.observe(el, { childList: true, subtree: true, attributes: true, attributeFilter: ['style', 'class'] })
      moRef.current = mo
      roRef.current = new ResizeObserver(() => {
        chart!.resize()
        forceCursor()
      })
      roRef.current.observe(el)

      chart.on('updateAxisPointer', (event: any) => {
        const axesInfo = event.axesInfo
        if (!axesInfo) return
        for (const info of Object.values(axesInfo)) {
          const val = (info as any)?.value
          if (val == null) continue
          const fullDayIdx = typeof val === 'number' ? val : -1
          if (fullDayIdx >= 0) {
            const dataIdx = fullDayToDataIdx.current.get(fullDayIdx) ?? -1
            setInfoIdx(dataIdx)
            const d = dataRef.current
            if (dataIdx >= 0 && dataIdx < d.length) {
              onPriceHoverRef.current?.(d[dataIdx].close)
            }
            return
          }
        }
      })

      chart.on('globalout', () => {
        onPriceHoverRef.current?.(null)
      })
    }

    if (data.length > 0) {
      // 构建轴索引 → 数据索引 的映射 (crypto 轴即数据序号, 恒等映射)
      const axisTimes = mode === 'crypto' ? data.map(d => fmtTime(d.datetime)) : FULL_DAY_TIMES
      const timeIndexMap = new Map(axisTimes.map((t, i) => [t, i]))
      const mapping = new Map<number, number>()
      for (let i = 0; i < data.length; i++) {
        const timeKey = fmtTime(data[i].datetime)
        const fullDayIdx = timeIndexMap.get(timeKey)
        if (fullDayIdx !== undefined) {
          mapping.set(fullDayIdx, i)
        }
      }
      fullDayToDataIdx.current = mapping

      chart.setOption(buildOption(data, prevClose, avgPrices, lineColor, areaFill, yMode, ct, priceLimit, showLimitLines && mode !== 'crypto', showAvg, mode), true)
    } else {
      chart.clear()
    }
  }, [data, prevClose, height, lineColor, areaFill, yMode, ct, priceLimit, showLimitLines, showAvg, mode])

  useEffect(() => {
    return () => {
      chartRef.current?.off('updateAxisPointer')
      chartRef.current?.off('globalout')
      moRef.current?.disconnect()
      roRef.current?.disconnect()
      chartRef.current?.dispose()
      chartRef.current = null
      moRef.current = null
      roRef.current = null
    }
  }, [])

  const d = infoIdx >= 0 && infoIdx < data.length ? data[infoIdx] : null
  const avg = d != null ? avgPrices[infoIdx] : null
  const chg = d && prevClose != null ? d.close - prevClose : null
  const isUp = chg != null ? chg > 0 : true
  const isFlat = chg != null ? chg === 0 : false
  const priceClr = isFlat ? '#A1A1AA' : isUp ? '#C74040' : '#2D9B65'

  return (
    <div className="w-full">
      {/* 按钮行: 切换式按钮组, 居右 (crypto 无涨跌停语义, 隐藏切换) */}
      {showLimitLines && mode !== 'crypto' && <div className="flex items-center justify-end px-1 pb-0.5">
        <div className="inline-flex items-center rounded bg-elevated overflow-hidden">
          <button
            onClick={() => setYMode('adaptive')}
            className={`px-2.5 py-0.5 text-[10px] font-mono cursor-pointer transition-colors ${
              yMode === 'adaptive'
                ? 'bg-accent/20 text-accent'
                : 'text-muted hover:text-secondary'
            }`}
          >
            自适应
          </button>
          <div className="w-px h-3 bg-border/40" />
          <button
            onClick={() => setYMode('limit')}
            className={`px-2.5 py-0.5 text-[10px] font-mono cursor-pointer transition-colors ${
              yMode === 'limit'
                ? 'bg-accent/20 text-accent'
                : 'text-muted hover:text-secondary'
            }`}
          >
            涨跌停
          </button>
        </div>
      </div>}
      <div style={{ backgroundColor: ct.infoBarBg }}>
        {/* 第一行: 日期 + OHLC */}
        <div className="flex items-center gap-x-2 px-2 font-mono text-[11px] select-none flex-wrap" style={{ height: 20 }}>
          {!d && <span className="text-muted">—</span>}
          {d && (
            <>
              {date && <span className="text-muted">{date}</span>}
              <span className="text-muted">开</span>
              <span style={{ color: priceClr }}>{fmtPx(d.open)}</span>
              <span className="text-muted">高</span>
              <span style={{ color: priceClr }}>{fmtPx(d.high)}</span>
              <span className="text-muted">低</span>
              <span style={{ color: priceClr }}>{fmtPx(d.low)}</span>
              <span className="text-muted">收</span>
              <span style={{ color: priceClr }} className="font-semibold">{fmtPx(d.close)}</span>
            </>
          )}
        </div>
        {/* 第二行: 价格+均价+量+额 */}
        <div className="flex items-center gap-x-4 px-2 font-mono text-[11px] select-none" style={{ height: 20 }}>
          {d && (
            <>
              <span className="flex items-center gap-x-1">
                <span style={{ display: 'inline-block', width: 14, height: 2, background: priceClr }} />
                <span style={{ color: priceClr }}>{fmtPx(d.close)}</span>
              </span>
              {showAvgLine && (showAvg ? (
                <span className="flex items-center gap-x-1">
                  <span style={{ display: 'inline-block', width: 14, height: 2, background: THEME.avgLine }} />
                  <span style={{ color: THEME.avgLine }}>{fmtPx(avg)}</span>
                </span>
              ) : (
                <span className="text-muted">均价 —</span>
              ))}
              <span className="text-muted">量</span>
              <span className="text-secondary">{d.volume.toFixed(0)}</span>
              <span className="text-muted">额</span>
              <span className="text-secondary">{fmtAmt(d.amount)}</span>
            </>
          )}
        </div>
      </div>
      <div ref={containerRef} className="w-full" style={{ height: height - 42, cursor: 'crosshair' }} />
    </div>
  )
}
