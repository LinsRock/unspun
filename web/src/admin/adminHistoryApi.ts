import type { AdminRange } from './adminFilters'

export interface HistoryPage<T> {
  range: { start: string; end: string; timezone: 'Asia/Shanghai'; end_exclusive: true }
  as_of: string
  page: number
  page_size: number
  total: number
  items: T[]
}

export type HistoryFilters = Record<string, string | number | boolean | null | undefined>

export function historyUrl(resource: 'sources' | 'articles' | 'events', range: AdminRange, filters: HistoryFilters = {}, exportCsv = false): string {
  const params = new URLSearchParams({ start: range.start, end: range.end })
  for (const [key, value] of Object.entries(filters)) {
    if (value !== null && value !== undefined && value !== '') params.set(key, String(value))
  }
  return `/api/admin/${resource}${exportCsv ? '/export.csv' : ''}?${params}`
}

export async function getHistoryPage<T>(resource: 'sources' | 'articles' | 'events', range: AdminRange, filters: HistoryFilters, signal?: AbortSignal): Promise<HistoryPage<T>> {
  const response = await fetch(historyUrl(resource, range, filters), { signal, credentials: 'same-origin', cache: 'no-store' })
  if (!response.ok) throw new Error(`Admin ${resource} request failed: ${response.status}`)
  return (await response.json()) as HistoryPage<T>
}

export async function getHistoryDetail<T>(resource: 'sources' | 'articles' | 'events', id: string | number, range: AdminRange, signal?: AbortSignal): Promise<T> {
  const params = new URLSearchParams({ start: range.start, end: range.end })
  const response = await fetch(`/api/admin/${resource}/${encodeURIComponent(id)}?${params}`, { signal, credentials: 'same-origin', cache: 'no-store' })
  if (!response.ok) throw new Error(`Admin ${resource} detail failed: ${response.status}`)
  return (await response.json()) as T
}

export async function downloadHistoryCsv(resource: 'sources' | 'articles' | 'events', range: AdminRange, filters: HistoryFilters): Promise<void> {
  const response = await fetch(historyUrl(resource, range, filters, true), { credentials: 'same-origin', cache: 'no-store' })
  if (response.status === 422) throw new Error('匹配记录超过 5000 条，请缩小时间范围或增加筛选条件。')
  if (!response.ok) throw new Error('导出失败，请稍后重试。')
  const objectUrl = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = objectUrl
  link.download = `${resource}.csv`
  document.body.append(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0)
}

export interface SourceRow {
  id: string
  name: string | null
  lang: string | null
  region: string | null
  kind: string | null
  configured: boolean
  enabled: boolean
  health: 'ok' | 'error' | 'no_runs'
  period_latest_status: 'ok' | 'error' | null
  new_articles: number
  successful_fetches: number
  failed_fetches: number
  success_rate: number | null
  last_success_at: string | null
  last_error_at: string | null
  last_error: string | null
}

export interface SourceDetailData extends SourceRow {
  config: { url: string; weight: number; max_items: number | null; timeout_seconds: number | null } | null
  fetches: { id: number; run_at: string; status: string; new_articles: number; error: string | null }[]
  articles: { id: number; title: string; fetched_at: string }[]
}

export interface ArticleRow {
  id: number
  source_id: string
  source_name: string | null
  url: string
  title: string
  title_zh: string | null
  lang: string | null
  published_at: string | null
  fetched_at: string
  summary_status: string
  embedding_status: string
  cluster_status: string
  processing_status: string
  quality_status: string | null
  reading_status?: string
  reading_reason?: string | null
  event_id: number | null
}

export interface ArticleDetailData extends ArticleRow {
  content: string | null
  summary_zh: string | null
  summary_grounding: unknown
  reading?: { status: string; reason?: string | null; kind: string }
  summary_failures: number
  event: { id: number; title: string | null } | null
  call_cost: number | null
}

export interface EventRow {
  id: number
  title: string | null
  first_seen_at: string
  changed_at: string
  earliest_published_at: string | null
  latest_published_at: string | null
  article_count: number
  source_count: number
  score_final: number | null
  scored_at: string | null
  processing_status: string
  range_time_basis?: 'published_at' | 'first_seen_at'
}

export interface EventDetailData extends EventRow {
  reading?: { status: string; title: string | null; kind: string; facts: { text: string }[] }
  summary_zh: string | null
  score_breakdown: unknown
  articles: { id: number; title: string; source_id: string; source_name: string | null; published_at: string | null; fetched_at: string; url: string; summary_zh: string | null }[]
  viewpoint: { payload: { claims?: { article_id: number; claim: string; evidence_quote?: string | null }[]; disagreements?: { point: string; kind?: string }[] }; model: string; generated_at: string } | null
}

export function displayTime(value: string | null): string {
  if (!value) return '未记录'
  return new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
}

export function safeExternalUrl(value: string): string | undefined {
  try {
    const url = new URL(value)
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : undefined
  } catch { return undefined }
}
