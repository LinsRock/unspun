import type { AdminRange } from './adminFilters'

export interface CostSummary {
  calls: { count: number; prompt_tokens: number; completion_tokens: number; cost_usd: string }
  filtered_calls: { count: number; prompt_tokens: number; completion_tokens: number; cost_usd: string }
  fixed: { confirmed_by_currency: Record<string, string>; expected_by_currency: Record<string, string>; spend_by_currency: Record<string, string>; confirmed_usd: string | null; expected_usd: string | null; spend_usd: string | null; spend_precision: 'day' | 'time_incomplete'; exact_spend_by_currency: Record<string, string>; date_only_unplaced_by_currency: Record<string, string>; unconverted_currencies: string[] }
  total_confirmed_usd: string | null
  covered_days: number
  average_daily_usd: string | null
  trend: { day: string; cost_usd: string }[]
  purposes: { name: string; cost_usd: string }[]
  models: { name: string; cost_usd: string }[]
  budget: { period: 'current_month'; limit: string; spent: string }
}

export interface CallRow { id: number; created_at: string; purpose: string; model: string; prompt_tokens: number; completion_tokens: number; cost_usd: string; association: 'not_recorded' }
export interface FixedCostRow { id: number; name: string; category: string; status: string; currency: string; amount: string; allocated: string; period_start: string; period_end: string }
export interface ExpenseRule { id: number; name: string; category: string; amount: string; currency: string; cadence: string; anchor_date: string; once_end: string | null; stop_before: string | null; reminder_days: number; version: number }
export interface ExpenseEntry { id: number; rule_id: number | null; name: string; category: string; amount: string; currency: string; kind: 'fixed' | 'topup'; period_start: string | null; period_end: string | null; status: 'pending' | 'paid' | 'canceled'; paid_on: string | null; paid_at: string | null; version: number }
export interface FxRate { id: number; currency: string; effective_on: string; rate_to_usd: string; source: string; version: number }
export interface Paged<T> { total: number; page: number; page_size: number; items: T[] }

export function costParams(range: AdminRange, filters: { model?: string; purpose?: string; page?: number } = {}) {
  const params = new URLSearchParams({ start: range.start, end: range.end })
  if (filters.model) params.set('model', filters.model)
  if (filters.purpose) params.set('purpose', filters.purpose)
  if (filters.page) params.set('page', String(filters.page))
  return params
}

export async function getCost<T>(path: string, params?: URLSearchParams, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api/admin/${path}${params ? `?${params}` : ''}`, { credentials: 'same-origin', cache: 'no-store', signal })
  if (!response.ok) throw new Error(`Request failed: ${response.status}`)
  return await response.json() as T
}

export async function writeExpense<T>(path: string, method: 'POST' | 'PATCH' | 'PUT', body: object): Promise<T> {
  if (!navigator.onLine) throw new Error('离线时无法提交账务，请联网后重试。')
  const response = await fetch(`/api/admin/${path}`, { method, credentials: 'same-origin', cache: 'no-store', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  if (!response.ok) throw new Error(response.status === 409 ? '记录已变更，请刷新后重试。' : `提交失败 (${response.status})`)
  return await response.json() as T
}

export async function downloadCalls(range: AdminRange, model?: string, purpose?: string) {
  const response = await fetch(`/api/admin/costs/calls/export.csv?${costParams(range, { model, purpose })}`, { credentials: 'same-origin', cache: 'no-store' })
  if (response.status === 422) throw new Error('匹配记录超过 5000 条，请缩小范围。')
  if (!response.ok) throw new Error('导出失败。')
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = url
  link.download = 'llm-calls.csv'
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}

export function money(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return '未换算'
  const numeric = Number(value)
  if (numeric === 0) return '0'
  if (Math.abs(numeric) < 0.000001) return numeric.toExponential(2)
  return numeric.toLocaleString('zh-CN', { maximumFractionDigits: 6 })
}
