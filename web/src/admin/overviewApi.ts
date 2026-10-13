import type { AdminRange } from './adminFilters'
import { fetchAdmin } from './adminApi'

export interface OverviewData {
  range: { start: string; end: string; timezone: 'Asia/Shanghai'; end_exclusive: true }
  as_of: string
  period: {
    articles: number
    new_events: number
    runs: number
    fetch_errors: number
    sources: { configured_total: number; enabled_total: number; successful_sources: number; productive_sources: number; failed_sources: number }
    cost: { total_confirmed_usd: string | null; calls: { count: number; cost_usd: string }; fixed: { confirmed_usd: string | null; expected_usd: string | null; unconverted_currencies: string[] } }
  }
  current: { scope: 'current'; consistency: 'live'; source_health: { error: number; no_runs: number; ok: number }; backlog: { pending_summaries: number; abandoned_summaries: number; pending_embeddings: number; pending_scores: number } }
  article_trend: { day: string; articles: number }[]
  call_trend: { day: string; cost_usd: string }[]
  purposes: { name: string; cost_usd: string }[]
  recent_run: { id: number; run_at: string; summarized: number; embedded: number; clustered: number; new_events: number; scored: number; status: string | null; ended_at: string | null; duration_seconds: number | null; missing_fields: string[] } | null
  exceptions: { source_error_total: number; abandoned_summaries: number; sources: { source_id: string; name: string; last_error: string | null; last_error_at: string | null }[] }
}

export function getOverview(range: AdminRange, signal?: AbortSignal) {
  return fetchAdmin<OverviewData>('overview', new URLSearchParams({ start: range.start, end: range.end }), signal)
}
