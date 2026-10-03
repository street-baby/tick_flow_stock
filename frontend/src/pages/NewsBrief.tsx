import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  Clock,
  ExternalLink,
  Flame,
  Newspaper,
  RefreshCw,
  Snowflake,
  Sparkles,
  TrendingDown,
  TrendingUp,
} from 'lucide-react'
import { api, type FlashTaggedItem, type SectorBriefData } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { cn } from '@/lib/cn'
import { SectorBriefCardView } from '@/components/news/SectorBriefCard'
import { cnSessionPhase, formatCountdown } from '@/lib/tradingSession'
import { toast } from '@/components/Toast'

type Kind = 'concept' | 'industry'
type DirectionFilter = 'all' | 'bullish' | 'bearish' | 'related'

const DIRECTION_LABEL: Record<FlashTaggedItem['direction'], string> = {
  bullish: '利好',
  bearish: '利空',
  neutral: '中性',
}

const AI_STATUS_LABEL: Record<SectorBriefData['ai_status'], string> = {
  cached: 'AI 研判已生成',
  generated: 'AI 研判已生成',
  missing: 'AI 研判未生成',
  unavailable: 'AI 研判不可用',
}

/** 快讯时间形如 "2026-09-19 10:30:00", 解析失败时原样返回 */
function parseFlashTime(value: string): { day: string; clock: string } {
  const text = (value || '').trim()
  const match = text.match(/^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})/)
  if (!match) return { day: text.slice(0, 10), clock: text.slice(11, 16) }
  return { day: match[1], clock: match[2] }
}

function dayLabel(day: string, today: string, yesterday: string): string {
  if (!day) return '时间未知'
  if (day === today) return '今天'
  if (day === yesterday) return '昨天'
  return day
}

export function NewsBrief() {
  const qc = useQueryClient()
  const [kind, setKind] = useState<Kind>('concept')
  const [direction, setDirection] = useState<DirectionFilter>('all')
  const [activeDay, setActiveDay] = useState<string>('all')
  const [now, setNow] = useState(() => new Date())
  // AI 文案每次会话只自动请求一次, 失败后由用户点按钮重试(避免反复烧 token)
  const autoNarrateTried = useRef(false)
  // 只有用户主动点的重试才弹 toast —— 自动尝试失败只做内联提示, 不刷屏
  const manualNarrate = useRef(false)
  const [narrateError, setNarrateError] = useState<string | null>(null)

  // 交易时段倒计时
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(timer)
  }, [])

  const session = cnSessionPhase(now)

  const briefQuery = useQuery({
    queryKey: QK.sectorBrief(kind),
    queryFn: () => api.sectorBrief(kind, 5),
    placeholderData: prev => prev,
    staleTime: 60_000,
    // 板块数据是日级的, 但「关联快讯」来自盘中快讯池 —— 低频跟一次就够
    refetchInterval: 120_000,
  })

  const flashQuery = useQuery({
    queryKey: QK.flashTagged(200),
    queryFn: () => api.flashTagged(200),
    // 主路径是 SSE news_updated(服务端抓到新快讯就推); 30s 轮询只是兜底 ——
    // SSE 断了或长连接被中间层掐掉时, 页面仍然在动。后台页也刷, 切回来就是新的。
    refetchInterval: 30_000,
    refetchIntervalInBackground: true,
    staleTime: 15_000,
    placeholderData: prev => prev,
  })

  // 抓取器状态: 低频拉一次, 只在真的连续抓取失败时给用户提示
  const liveStatusQuery = useQuery({
    queryKey: QK.newsLiveStatus,
    queryFn: () => api.newsLiveStatus(),
    refetchInterval: 60_000,
    staleTime: 30_000,
  })

  const narrate = useMutation({
    mutationFn: () => api.sectorBriefNarrate(kind, 5),
    onSuccess: data => {
      qc.setQueryData(QK.sectorBrief(kind), data)
      setNarrateError(null)
      if (manualNarrate.current) toast('AI 板块研判已生成', 'success')
      manualNarrate.current = false
    },
    // 降级: 保留数据派生文案, 只提示失败, 不阻塞页面
    onError: (err: unknown) => {
      const message = err instanceof Error ? err.message : 'AI 板块研判生成失败'
      setNarrateError(message)
      if (manualNarrate.current) toast(message, 'error')
      manualNarrate.current = false
    },
  })

  const brief = briefQuery.data
  const narratePending = narrate.isPending

  useEffect(() => {
    if (!brief || autoNarrateTried.current) return
    if (!brief.ai_configured || brief.ai_status !== 'missing') return
    if (!brief.bullish.length && !brief.bearish.length) return
    autoNarrateTried.current = true
    narrate.mutate()
    // narrate 由 mutation 自身管理状态, 这里只做一次性的自动触发
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [brief])

  const flashItems = flashQuery.data?.items ?? []

  // ── 实时状态: 由 SSE 推送 / 兜底轮询换来的 dataUpdatedAt 推算, 不靠猜 ──
  const flashUpdatedAt = flashQuery.dataUpdatedAt
  const flashAge = flashUpdatedAt ? Math.max(0, Math.floor((now.getTime() - flashUpdatedAt) / 1000)) : null
  const flashAgeLabel =
    flashAge == null ? null : flashAge < 5 ? '刚刚' : flashAge < 60 ? `${flashAge} 秒前` : `${Math.floor(flashAge / 60)} 分钟前`
  // 超过两个抓取周期没有新数据: 推送和轮询至少断了一环, 页面要如实说而不是继续假装实时
  const pushStalled = flashAge != null && flashAge > 90
  const liveStatus = liveStatusQuery.data
  const fetchErrors = liveStatus?.consecutive_errors ?? 0

  // ── 新到达的快讯高亮 ──────────────────────────────────────────────
  // 首屏不闪(整页都是新的), 之后每次重取只闪真正新增的那些;
  // 一下子涌进太多条(离开很久再回来)也不闪 —— 满屏跳动比不闪更难读。
  const seenIdsRef = useRef<Set<string>>(new Set())
  const firstFlashRef = useRef(true)
  const [freshIds, setFreshIds] = useState<Set<string>>(() => new Set())

  useEffect(() => {
    const items = flashQuery.data?.items
    if (!items) return
    const seen = seenIdsRef.current
    if (firstFlashRef.current) {
      firstFlashRef.current = false
      items.forEach(item => seen.add(item.id))
      return
    }
    const arrived = items.filter(item => !seen.has(item.id)).map(item => item.id)
    items.forEach(item => seen.add(item.id))
    if (arrived.length === 0 || arrived.length > 20) return
    setFreshIds(new Set(arrived))
    const timer = setTimeout(() => setFreshIds(new Set()), 3_000)
    return () => clearTimeout(timer)
  }, [flashQuery.data])

  const today = now.toISOString().slice(0, 10)
  const yesterday = useMemo(() => {
    const d = new Date(now)
    d.setDate(d.getDate() - 1)
    return d.toISOString().slice(0, 10)
  }, [now])

  // 日期分组 chip: 只列出现过的日期, 避免空筛选
  const dayOptions = useMemo(() => {
    const days: string[] = []
    for (const item of flashItems) {
      const { day } = parseFlashTime(item.time)
      if (day && !days.includes(day)) days.push(day)
    }
    return days.sort().reverse()
  }, [flashItems])

  const visibleFlash = useMemo(() => {
    return flashItems.filter(item => {
      const { day } = parseFlashTime(item.time)
      if (activeDay !== 'all' && day !== activeDay) return false
      if (direction === 'all') return true
      if (direction === 'related') return item.sectors.length > 0 || item.symbols.length > 0
      return item.direction === direction
    })
  }, [flashItems, activeDay, direction])

  const bullishCount = brief?.bullish.length ?? 0
  const bearishCount = brief?.bearish.length ?? 0

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* 顶栏: 数据日期 + 距开盘 + 统计 + 维度切换 */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-card border border-border bg-surface px-4 py-3">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <Newspaper size={18} className="text-accent" />
            <span className="text-base font-semibold text-foreground">资讯</span>
          </div>
          <span className="text-xs text-muted">
            板块简报数据日期：
            <span className="font-mono text-secondary">{brief?.as_of ?? '—'}</span>
          </span>
          <div className="flex items-center gap-1.5 text-xs">
            <Clock size={13} className={session.colorClass} />
            <span className={session.colorClass}>{session.label}</span>
            {session.secondsToNext != null && (
              <span className="font-mono text-secondary">
                距{session.nextLabel} {formatCountdown(session.secondsToNext)}
              </span>
            )}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <span className="text-xs text-muted">
            快讯 <span className="font-mono text-secondary">{flashItems.length}</span> 条 · 利好{' '}
            <span className="font-mono text-bull">{bullishCount}</span> 板块 · 利空{' '}
            <span className="font-mono text-bear">{bearishCount}</span> 板块
          </span>
          <div className="flex rounded-btn border border-border p-0.5">
            {(['concept', 'industry'] as Kind[]).map(k => (
              <button
                key={k}
                onClick={() => setKind(k)}
                className={cn(
                  'rounded-btn px-2.5 py-1 text-xs transition-colors',
                  kind === k ? 'bg-elevated text-foreground' : 'text-muted hover:text-foreground',
                )}
              >
                {k === 'concept' ? '概念' : '行业'}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* 板块简报 */}
      {briefQuery.isLoading ? (
        <div className="rounded-card border border-border bg-surface px-4 py-10 text-center text-sm text-muted">
          正在加载板块简报…
        </div>
      ) : briefQuery.isError ? (
        <div className="flex items-center gap-2 rounded-card border border-bear/30 bg-bear/5 px-4 py-4 text-sm text-bear">
          <AlertTriangle size={15} />
          板块简报加载失败：{(briefQuery.error as Error)?.message ?? '未知错误'}
          <button className="ml-auto text-xs underline" onClick={() => briefQuery.refetch()}>
            重试
          </button>
        </div>
      ) : !brief || (bullishCount === 0 && bearishCount === 0) ? (
        <div className="rounded-card border border-border bg-surface px-4 py-10 text-center text-sm text-muted">
          暂无板块数据。板块简报依赖概念/行业维度与当日行情，请先在「数据」页同步概念/行业数据后再查看。
        </div>
      ) : (
        <>
          <div className="flex items-center gap-2 text-xs text-muted">
            <Sparkles size={13} className={brief.ai_status === 'cached' || brief.ai_status === 'generated' ? 'text-accent' : 'text-muted'} />
            <span>
              {AI_STATUS_LABEL[brief.ai_status]}
              {brief.ai_generated_at ? ` · ${brief.ai_generated_at.replace('T', ' ').slice(0, 16)}` : ''}
            </span>
            {brief.ai_status !== 'cached' && brief.ai_status !== 'generated' && (
              <span className="text-muted">（当前显示数据派生文案）</span>
            )}
            {brief.ai_configured && brief.ai_status !== 'generated' && (
              <button
                onClick={() => {
                  manualNarrate.current = true
                  narrate.mutate()
                }}
                disabled={narratePending}
                className="ml-1 inline-flex items-center gap-1 rounded-btn border border-border px-2 py-0.5 text-[11px] text-secondary transition-colors hover:text-foreground disabled:opacity-50"
              >
                <RefreshCw size={11} className={narratePending ? 'animate-spin' : ''} />
                {narratePending ? 'AI 生成中…' : 'AI 生成研判'}
              </button>
            )}
            {!brief.ai_configured && (
              <span className="text-muted">（未配置 AI 模型，可在设置中开启后生成研判）</span>
            )}
            {narrateError && (
              <span className="inline-flex items-center gap-1 text-bear">
                <AlertTriangle size={11} />
                {narrateError}
              </span>
            )}
          </div>

          <section className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <Flame size={15} className="text-bull" />
              <h2 className="text-sm font-semibold text-foreground">利好板块</h2>
              <span className="text-[11px] text-muted">当日板块均涨幅前 5 · 近 {brief.days} 个交易日排名参照</span>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-5">
              {brief.bullish.map(card => (
                <SectorBriefCardView key={card.name} card={card} direction="bullish" />
              ))}
            </div>
          </section>

          <section className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <Snowflake size={15} className="text-bear" />
              <h2 className="text-sm font-semibold text-foreground">利空板块</h2>
              {/* 强市里后 5 名也可能是正收益, 标成「后 5 名」才是事实 */}
              <span className="text-[11px] text-muted">当日板块均涨幅后 5（相对弱势）· 数据口径同上</span>
            </div>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-5">
              {brief.bearish.map(card => (
                <SectorBriefCardView key={card.name} card={card} direction="bearish" />
              ))}
            </div>
          </section>
        </>
      )}

      {/* 重点快讯 */}
      <section className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <TrendingUp size={15} className="text-accent" />
            <h2 className="text-sm font-semibold text-foreground">重点快讯</h2>
            {/* 实时状态: 服务端持续抓取 → SSE 推送 → 这里显示「刚刚」而不是让用户猜 */}
            <span
              className="flex items-center gap-1 text-[11px]"
              title={
                liveStatus?.enabled
                  ? `服务端每 ${liveStatus.interval_seconds}s 抓取一次 · 池内 ${liveStatus.stored ?? 0} 条`
                  : '未启用后台抓取, 打开本页时才拉取'
              }
            >
              <span
                className={cn(
                  'h-1.5 w-1.5 rounded-full',
                  pushStalled ? 'bg-amber-400' : 'animate-quant-pulse bg-accent',
                )}
              />
              <span className={pushStalled ? 'text-amber-400' : 'text-accent'}>
                {pushStalled ? '更新停滞' : '实时更新'}
              </span>
              {flashAgeLabel && <span className="font-mono text-secondary">· {flashAgeLabel}</span>}
              {flashQuery.data?.updated_at && (
                <span className="text-muted">· 数据源 {flashQuery.data.updated_at.slice(11, 19)}</span>
              )}
            </span>
            {fetchErrors > 0 && (
              <span className="flex items-center gap-1 text-[11px] text-amber-400" title={liveStatus?.last_error ?? ''}>
                <AlertTriangle size={11} />
                抓取失败 {fetchErrors} 次
              </span>
            )}
            <span className="text-[11px] text-muted">7x24 财经快讯 · 自动标注方向与关联板块/标的</span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex rounded-btn border border-border p-0.5">
              {(
                [
                  ['all', '全部'],
                  ['bullish', '利好'],
                  ['bearish', '利空'],
                  ['related', '有板块关联'],
                ] as [DirectionFilter, string][]
              ).map(([value, label]) => (
                <button
                  key={value}
                  onClick={() => setDirection(value)}
                  className={cn(
                    'rounded-btn px-2 py-0.5 text-[11px] transition-colors',
                    direction === value ? 'bg-elevated text-foreground' : 'text-muted hover:text-foreground',
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
            {dayOptions.length > 0 && (
              <div className="flex flex-wrap items-center gap-1">
                <button
                  onClick={() => setActiveDay('all')}
                  className={cn(
                    'rounded-btn border px-2 py-0.5 text-[11px] transition-colors',
                    activeDay === 'all'
                      ? 'border-accent/40 bg-accent/10 text-accent'
                      : 'border-border text-muted hover:text-foreground',
                  )}
                >
                  全部日期
                </button>
                {dayOptions.slice(0, 6).map(day => (
                  <button
                    key={day}
                    onClick={() => setActiveDay(day)}
                    className={cn(
                      'rounded-btn border px-2 py-0.5 font-mono text-[11px] transition-colors',
                      activeDay === day
                        ? 'border-accent/40 bg-accent/10 text-accent'
                        : 'border-border text-muted hover:text-foreground',
                    )}
                  >
                    {dayLabel(day, today, yesterday)}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {flashQuery.isLoading ? (
          <div className="rounded-card border border-border bg-surface px-4 py-10 text-center text-sm text-muted">
            正在加载快讯…
          </div>
        ) : flashQuery.isError ? (
          <div className="flex items-center gap-2 rounded-card border border-bear/30 bg-bear/5 px-4 py-4 text-sm text-bear">
            <AlertTriangle size={15} />
            快讯加载失败：{(flashQuery.error as Error)?.message ?? '未知错误'}
            <button className="ml-auto text-xs underline" onClick={() => flashQuery.refetch()}>
              重试
            </button>
          </div>
        ) : visibleFlash.length === 0 ? (
          <div className="rounded-card border border-border bg-surface px-4 py-10 text-center text-sm text-muted">
            当前筛选条件下没有快讯。
          </div>
        ) : (
          <div className="flex flex-col divide-y divide-border overflow-hidden rounded-card border border-border bg-surface">
            {visibleFlash.map(item => {
              const { day, clock } = parseFlashTime(item.time)
              return (
                <article
                  key={item.id}
                  className={cn(
                    'flex gap-3 px-3.5 py-2.5 transition-colors hover:bg-elevated/40',
                    freshIds.has(item.id) && 'news-arrive',
                  )}
                >
                  <div className="w-24 shrink-0 text-right">
                    <div className="font-mono text-xs text-secondary">{clock || '—'}</div>
                    <div className="text-[10px] text-muted">{dayLabel(day, today, yesterday)}</div>
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="mb-1 flex flex-wrap items-center gap-1.5">
                      <span className="rounded-sm bg-elevated px-1.5 py-0.5 text-[10px] text-muted">{item.tag || '快讯'}</span>
                      {item.direction !== 'neutral' && (
                        <span
                          className={cn(
                            'inline-flex items-center gap-0.5 rounded-sm px-1.5 py-0.5 text-[10px]',
                            item.direction === 'bullish' ? 'bg-bull/10 text-bull' : 'bg-bear/10 text-bear',
                          )}
                        >
                          {item.direction === 'bullish' ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
                          {DIRECTION_LABEL[item.direction]}
                        </span>
                      )}
                      {item.is_fallback && (
                        <span className="rounded-sm bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-400">
                          示例内容 · 上游暂不可用
                        </span>
                      )}
                      <span className="truncate text-sm font-medium text-foreground">
                        {item.title || item.content.slice(0, 40)}
                      </span>
                    </div>
                    <p className="line-clamp-2 text-xs leading-relaxed text-secondary" title={item.content}>
                      {item.content}
                    </p>
                    {(item.sectors.length > 0 || item.symbols.length > 0) && (
                      <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-muted">
                        {item.sectors.length > 0 && (
                          <span>
                            关联板块：
                            <span className="text-secondary">{item.sectors.join(' · ')}</span>
                          </span>
                        )}
                        {item.symbols.length > 0 && (
                          <span>
                            关联标的：
                            <span className="font-mono text-secondary">
                              {item.symbols.map(s => s.name).join(' · ')}
                            </span>
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                  {item.url && (
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noreferrer"
                      className="shrink-0 self-center text-muted transition-colors hover:text-accent"
                      title="查看原文"
                    >
                      <ExternalLink size={13} />
                    </a>
                  )}
                </article>
              )
            })}
          </div>
        )}
      </section>
    </div>
  )
}
