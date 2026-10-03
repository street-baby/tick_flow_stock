/**
 * A 股交易时段判定(北京时间)。
 *
 * 纯函数 —— 供资讯页展示「距开盘/收盘」倒计时与时段标签。
 * A 股时段固定: 09:15-09:25 集合竞价, 09:30-11:30 / 13:00-15:00 连续交易。
 * 与 TradePlan 页的内联时段判断口径一致(那里含页面专属文案, 暂未合并)。
 */

export type CnSessionPhase = 'pre-open' | 'auction' | 'pre-open-lock' | 'trading' | 'lunch' | 'closed'

export interface CnSessionState {
  phase: CnSessionPhase
  /** 时段名称, 如「连续交易中」 */
  label: string
  /** 时段说明(一句话) */
  desc: string
  /** Tailwind 文本色 class, 与 TradePlan 的时段配色保持同一套语义 */
  colorClass: string
  /** 距下一个关键时点(开盘/收盘/竞价结束)的剩余秒数; 无后续时点为 null */
  secondsToNext: number | null
  /** 下一个关键时点的名称, 如「开盘」 */
  nextLabel: string | null
}

const MINUTES = (h: number, m: number) => h * 60 + m

const AUCTION_START = MINUTES(9, 15)
const AUCTION_END = MINUTES(9, 25)
const OPEN = MINUTES(9, 30)
const MORNING_END = MINUTES(11, 30)
const AFTERNOON_START = MINUTES(13, 0)
const CLOSE = MINUTES(15, 0)

function secondsUntil(now: Date, targetMinutes: number): number {
  const target = new Date(now)
  target.setHours(Math.floor(targetMinutes / 60), targetMinutes % 60, 0, 0)
  return Math.max(0, Math.floor((target.getTime() - now.getTime()) / 1000))
}

export function cnSessionPhase(now: Date = new Date()): CnSessionState {
  const cur = now.getHours() * 60 + now.getMinutes()

  if (cur >= AUCTION_START && cur < AUCTION_END) {
    return {
      phase: 'auction',
      label: '集合竞价中',
      desc: '9:15-9:25 竞价撮合，9:25 出开盘价',
      colorClass: 'text-purple-400',
      secondsToNext: secondsUntil(now, AUCTION_END),
      nextLabel: '竞价结束',
    }
  }
  if (cur >= AUCTION_END && cur < OPEN) {
    return {
      phase: 'pre-open-lock',
      label: '即将开盘',
      desc: '9:25-9:30 委托撮合锁定，等待开盘',
      colorClass: 'text-cyan-400',
      secondsToNext: secondsUntil(now, OPEN),
      nextLabel: '开盘',
    }
  }
  if (cur >= OPEN && cur <= MORNING_END) {
    return {
      phase: 'trading',
      label: '连续交易中',
      desc: '早盘 9:30-11:30',
      colorClass: 'text-emerald-400',
      secondsToNext: secondsUntil(now, MORNING_END),
      nextLabel: '午间休市',
    }
  }
  if (cur > MORNING_END && cur < AFTERNOON_START) {
    return {
      phase: 'lunch',
      label: '午间休市',
      desc: '11:30-13:00 休市，13:00 恢复交易',
      colorClass: 'text-amber-400',
      secondsToNext: secondsUntil(now, AFTERNOON_START),
      nextLabel: '午后开盘',
    }
  }
  if (cur >= AFTERNOON_START && cur <= CLOSE) {
    return {
      phase: 'trading',
      label: '连续交易中',
      desc: '午后 13:00-15:00',
      colorClass: 'text-emerald-400',
      secondsToNext: secondsUntil(now, CLOSE),
      nextLabel: '收盘',
    }
  }
  if (cur > CLOSE) {
    return {
      phase: 'closed',
      label: '已收盘',
      desc: '当日交易结束，数据为盘后静态口径',
      colorClass: 'text-muted',
      secondsToNext: null,
      nextLabel: null,
    }
  }
  // 盘前: 距 09:15 集合竞价还有多久对盘前资讯更有意义
  return {
    phase: 'pre-open',
    label: '盘前准备',
    desc: '开盘前 9:15 开始集合竞价',
    colorClass: 'text-amber-400',
    secondsToNext: secondsUntil(now, AUCTION_START),
    nextLabel: '集合竞价',
  }
}

/** 秒数 → HH:MM:SS(用于倒计时展示) */
export function formatCountdown(seconds: number | null): string {
  if (seconds == null) return '--:--:--'
  const s = Math.max(0, Math.floor(seconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  return [h, m, sec].map(v => String(v).padStart(2, '0')).join(':')
}
