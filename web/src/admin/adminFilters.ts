import dayjs from 'dayjs'
import timezone from 'dayjs/plugin/timezone'
import utc from 'dayjs/plugin/utc'

dayjs.extend(utc)
dayjs.extend(timezone)

const ZONE = 'Asia/Shanghai'
const DAY_MS = 86_400_000

export const periodLabels = {
  today: '今天',
  yesterday: '昨天',
  week: '本周',
  lastWeek: '上周',
  month: '本月',
  lastMonth: '上月',
  year: '今年',
  last24h: '最近 24 小时',
  last7d: '最近 7 天',
  custom: '自定义',
} as const

export type Period = keyof typeof periodLabels
export interface AdminRange {
  period: Period
  start: string
  end: string
}

function localMidnight(date: string): number {
  return dayjs.tz(`${date}T00:00:00`, ZONE).valueOf()
}

export function presetRange(period: Exclude<Period, 'custom'>, now = new Date()): AdminRange {
  const local = dayjs(now).tz(ZONE)
  const today = localMidnight(local.format('YYYY-MM-DD'))
  const dayOfWeek = (local.day() + 6) % 7
  let start = today
  let end = now.getTime()
  switch (period) {
    case 'yesterday':
      start = today - DAY_MS
      end = today
      break
    case 'week':
      start = today - dayOfWeek * DAY_MS
      break
    case 'lastWeek':
      end = today - dayOfWeek * DAY_MS
      start = end - 7 * DAY_MS
      break
    case 'month':
      start = localMidnight(local.startOf('month').format('YYYY-MM-DD'))
      break
    case 'lastMonth':
      end = localMidnight(local.startOf('month').format('YYYY-MM-DD'))
      start = localMidnight(local.subtract(1, 'month').startOf('month').format('YYYY-MM-DD'))
      break
    case 'year':
      start = localMidnight(local.startOf('year').format('YYYY-MM-DD'))
      break
    case 'last24h':
      start = end - DAY_MS
      break
    case 'last7d':
      start = end - 7 * DAY_MS
      break
    case 'today':
      break
  }
  return { period, start: new Date(start).toISOString(), end: new Date(end).toISOString() }
}

function validTimestamp(value: string | null): value is string {
  return value !== null && /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) && !Number.isNaN(Date.parse(value))
}

export function parseRange(search: URLSearchParams, now = new Date()): AdminRange {
  const start = search.get('start')
  const end = search.get('end')
  const period = search.get('period')
  if (
    !validTimestamp(start) ||
    !validTimestamp(end) ||
    Date.parse(start) >= Date.parse(end) ||
    Date.parse(start) >= now.getTime()
  ) {
    return presetRange('today', now)
  }
  const normalizedStart = new Date(start).toISOString()
  const normalizedEnd = new Date(Math.min(Date.parse(end), now.getTime())).toISOString()
  let restoredPeriod: Period = 'custom'
  if (period && period in periodLabels && period !== 'custom') {
    const candidate = period as Exclude<Period, 'custom'>
    const canonical = presetRange(candidate, now)
    const sameStart = normalizedStart === canonical.start
    const sameEnd = normalizedEnd === canonical.end
    if (candidate === 'today' || candidate === 'week' || candidate === 'month' || candidate === 'year') {
      if (sameStart && Date.parse(normalizedEnd) <= now.getTime()) restoredPeriod = candidate
    } else if (candidate === 'last24h' || candidate === 'last7d') {
      if (Math.abs(Date.parse(normalizedEnd) - now.getTime()) <= 60_000 &&
          Date.parse(normalizedEnd) - Date.parse(normalizedStart) ===
            Date.parse(canonical.end) - Date.parse(canonical.start)) restoredPeriod = candidate
    } else if (sameStart && sameEnd) {
      restoredPeriod = candidate
    }
  }
  return { period: restoredPeriod, start: normalizedStart, end: normalizedEnd }
}

export function rangeSearch(existing: URLSearchParams, range: AdminRange): URLSearchParams {
  const next = new URLSearchParams(existing)
  next.set('period', range.period)
  next.set('start', range.start)
  next.set('end', range.end)
  return next
}

export function sharedRangeSearch(search: URLSearchParams): string {
  const next = new URLSearchParams()
  for (const key of ['period', 'start', 'end']) {
    const value = search.get(key)
    if (value) next.set(key, value)
  }
  return next.toString()
}
