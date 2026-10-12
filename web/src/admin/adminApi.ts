import type { AdminRange } from './adminFilters'

export interface AdminRangeResult {
  range: { start: string; end: string; timezone: 'Asia/Shanghai'; end_exclusive: true }
  as_of: string
  page: number
  page_size: number
  sort: 'newest' | 'oldest'
}

export async function fetchAdminRange(range: AdminRange, signal?: AbortSignal): Promise<AdminRangeResult> {
  const params = new URLSearchParams({ start: range.start, end: range.end })
  const response = await fetch(`/api/admin/range?${params}`, {
    signal,
    credentials: 'same-origin',
    cache: 'no-store',
  })
  if (!response.ok) throw new Error(`Admin range request failed: ${response.status}`)
  return (await response.json()) as AdminRangeResult
}
