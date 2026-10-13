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

export interface RunRecord {
  id: number
  run_at: string
  summarized: number
  embedded: number
  clustered: number
  new_events: number
  scored: number
  ended_at: string | null
  duration_seconds: number | null
  status: string | null
  stage_results: null
  cost_usd: number | null
  missing_fields: string[]
}

export interface PageResult<T> { total: number; page: number; page_size: number; items: T[] }
export type BacklogStage = 'pending_summary' | 'abandoned_summary' | 'pending_embedding' | 'pending_score'
export interface BacklogItem { id: number; title: string; source_id: string | null; stage: BacklogStage; failures: number | null }
export interface BacklogResult extends PageResult<BacklogItem> {
  scope: 'current'
  consistency: 'live'
  counts: { pending_summaries: number; abandoned_summaries: number; pending_embeddings: number; pending_scores: number }
  stage: BacklogStage
}
export interface ConfigurationResult {
  sources: { id: string; name: string; weight: number; region: string; kind: string; lang: string; max_items: number | null; timeout_seconds: number | null }[]
  pipeline: { fetch_interval_minutes: number; summary_batch_limit: number; embed_batch_limit: number; score_batch_limit: number; max_summary_failures: number; digest_hour: number; digest_timezone: string; grounding_budget_24h_usd: number; summary_model: string; importance_model: string; viewpoint_model: string; digest_model: string; embedding_model: string }
  credentials: { openrouter_configured: boolean }
  audit: { status: 'not_recorded'; message: string }
}

export async function fetchAdmin<T>(path: string, params?: URLSearchParams, signal?: AbortSignal): Promise<T> {
  const suffix = params?.size ? `?${params}` : ''
  const response = await fetch(`/api/admin/${path}${suffix}`, { signal, credentials: 'same-origin', cache: 'no-store' })
  if (!response.ok) throw new Error(`Admin request failed: ${response.status}`)
  return await response.json() as T
}
