import { Link } from 'react-router-dom'
import { ArrowRight, ExternalLink, Flame, Snowflake } from 'lucide-react'
import type { SectorBriefCard, SectorBriefDriver, SectorDriverKey } from '@/lib/api'
import { cn } from '@/lib/cn'
import { fmtBigNum, fmtPct } from '@/lib/format'

interface Props {
  card: SectorBriefCard
  direction: 'bullish' | 'bearish'
}

/** 归因维度配色: 消息面/政策产业/盘面题材/外围指数 各自一种色, 与参考设计一致 */
const DRIVER_BAR: Record<SectorDriverKey, string> = {
  news: 'bg-sky-400',
  policy: 'bg-amber-400',
  market: 'bg-accent',
  overseas: 'bg-violet-400',
}

/** 快讯时间形如 "2026-09-20 12:08:00" → "12:08" */
function clock(time: string): string {
  const match = (time || '').match(/\d{2}:\d{2}/)
  return match ? match[0] : ''
}

/** 单个归因维度: 标签 + 权重条 + 证据文案 */
function DriverRow({ driver }: { driver: SectorBriefDriver }) {
  const weight = Math.max(0, Math.min(100, driver.weight))
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-2">
        <span className="w-14 shrink-0 text-[11px] text-secondary">{driver.label}</span>
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-elevated">
          <div
            className={cn('h-full rounded-full', DRIVER_BAR[driver.key] ?? 'bg-accent')}
            style={{ width: `${weight}%` }}
            title={`${driver.label} ${weight}%`}
          />
        </div>
        <span className="w-8 shrink-0 text-right font-mono text-[11px] text-secondary">{weight}%</span>
      </div>
      <p className="text-xs leading-relaxed text-secondary">{driver.text}</p>
    </div>
  )
}

export function SectorBriefCardView({ card, direction }: Props) {
  const isBull = direction === 'bullish'
  const drivers = card.drivers ?? []
  const flash = card.flash ?? []
  // AI 文案缺失时降级到数据派生文案: 两者都不展示在正文里, 放进标题的 tooltip
  const detail = card.ai_logic || card.logic_stats
  const rankText =
    card.prev_rank != null && card.rank != null
      ? `排名 ${card.prev_rank} → ${card.rank}`
      : card.rank != null
        ? `排名第 ${card.rank}`
        : null

  return (
    <div
      className={cn(
        'flex flex-col gap-2.5 rounded-card border bg-surface p-3.5 transition-colors',
        isBull ? 'border-bull/20 hover:border-bull/40' : 'border-bear/20 hover:border-bear/40',
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-1.5">
          {isBull ? (
            <Flame size={14} className="shrink-0 text-bull" />
          ) : (
            <Snowflake size={14} className="shrink-0 text-bear" />
          )}
          <span className="truncate text-sm font-semibold text-foreground">{card.name}</span>
          <span
            className={cn(
              'shrink-0 rounded-sm px-1.5 py-0.5 text-[10px]',
              isBull ? 'bg-bull/10 text-bull' : 'bg-bear/10 text-bear',
            )}
          >
            {isBull ? '利好' : '利空'}
          </span>
        </div>
        <span className={cn('shrink-0 font-mono text-sm font-semibold', isBull ? 'text-bull' : 'text-bear')}>
          {fmtPct(card.change_pct)}
        </span>
      </div>

      {card.headline && (
        <p className="text-[12.5px] font-medium leading-snug text-foreground" title={detail}>
          {card.headline}
        </p>
      )}

      {/* 驱动归因: 权重合计 100, 没有证据的维度不出现 */}
      {drivers.length > 0 && (
        <div className="flex flex-col gap-2.5">
          {drivers.map(driver => (
            <DriverRow key={driver.key} driver={driver} />
          ))}
        </div>
      )}

      {card.stocks.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {card.stocks.map(stock => (
            <span
              key={stock.symbol}
              className={cn(
                'inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px]',
                (stock.change_pct ?? 0) >= 0
                  ? 'border-bull/20 bg-bull/10 text-bull'
                  : 'border-bear/20 bg-bear/10 text-bear',
              )}
              title={`${stock.symbol} ${fmtPct(stock.change_pct)}`}
            >
              <span className="font-medium">{stock.name}</span>
              <span className="font-mono">{fmtPct(stock.change_pct)}</span>
            </span>
          ))}
        </div>
      )}

      {/* 与该板块相关的真实快讯(时间 / 来源 / 原文链接) */}
      {flash.length > 0 && (
        <div className="flex flex-col gap-1 rounded-md border border-border/60 bg-elevated/30 p-2">
          <div className="flex items-center gap-1.5">
            <span className="text-[10px] font-semibold uppercase tracking-wide text-muted">Related 关联快讯</span>
            <span className="rounded-sm bg-elevated px-1.5 text-[10px] text-secondary">{flash.length}</span>
          </div>
          {flash.map(item => {
            const body = (
              <>
                <span className="shrink-0 font-mono text-[10px] text-muted">{clock(item.time)}</span>
                <span className="truncate text-[11px] text-secondary group-hover:text-foreground" title={`${item.source} ${item.time}`}>
                  {item.title}
                </span>
                {item.url && <ExternalLink size={10} className="shrink-0 text-muted group-hover:text-accent" />}
              </>
            )
            return item.url ? (
              <a
                key={item.id}
                href={item.url}
                target="_blank"
                rel="noreferrer"
                className="group flex items-center gap-1.5 transition-colors"
              >
                {body}
              </a>
            ) : (
              <div key={item.id} className="group flex items-center gap-1.5">
                {body}
              </div>
            )
          })}
        </div>
      )}

      <div className="mt-auto flex items-center justify-between gap-2 border-t border-border pt-2 text-[11px] text-muted">
        <span className="truncate font-mono" title={detail}>
          {card.count} 只 · {fmtBigNum(card.amount)}
          {card.window_pct != null ? ` · 近${card.window_pct >= 0 ? '+' : ''}${(card.window_pct * 100).toFixed(2)}%` : ''}
          {rankText ? ` · ${rankText}` : ''}
        </span>
        <Link
          to="/concept-analysis"
          className="inline-flex shrink-0 items-center gap-0.5 whitespace-nowrap text-accent transition-colors hover:text-accent/80"
        >
          查看详情
          <ArrowRight size={11} />
        </Link>
      </div>
    </div>
  )
}
