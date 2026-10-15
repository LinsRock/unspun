export interface ArticleOut {
  id: number
  title: string
  title_zh: string | null
  url: string
  source_id: string
  source_name: string
  published_at: string | null
  content_quality?: 'grounded' | 'limited' | 'review_limited' | null
  reading_status?: string | null
  reading_reason?: string | null
  content_basis?: string
  reported_at?: string | null
  reported_date?: string | null
  publisher_group?: string | null
}

export interface ImportanceBreakdown {
  score: number
  scope: number
  durability: number
  novelty: number
  domain_importance: number
  reason: string
  confidence: string
}

export interface ObjectiveBreakdown {
  score: number
  breadth: number
  growth: number
  source_quality: number
  community: number
}

export interface ScoreBreakdown {
  objective?: ObjectiveBreakdown
  importance?: ImportanceBreakdown
}

export interface ViewpointClaim {
  article_id: number
  claim: string
  evidence_quote?: string | null
}

export interface ViewpointDisagreement {
  point: string
  claim_indexes: number[]
  kind?: string | null
}

export interface ViewpointOut {
  status?: string | null
  claims: ViewpointClaim[]
  disagreements: ViewpointDisagreement[]
  model: string
  generated_at: string
}

export type FeedSort = 'newest' | 'hot' | 'important'
export type FeedRange = 'today' | '24h' | '7d' | 'all'

export interface EventOut {
  id: number
  title: string | null
  summary_zh: string | null
  score_final: number | null
  score_decayed: number | null
  score_breakdown: ScoreBreakdown | null
  first_seen_at: string
  changed_at: string
  articles: ArticleOut[]
  viewpoint: ViewpointOut | null
  earliest_reported_at?: string | null
  earliest_reported_date?: string | null
  earliest_reported_precision?: 'time' | 'date' | 'unknown'
  latest_reported_at?: string | null
  latest_reported_date?: string | null
  latest_reported_precision?: 'time' | 'date' | 'unknown'
  valid_time_count?: number
  missing_time_count?: number
  invalid_time_count?: number
  active_publishers?: number
  heat?: number | null
  public_impact_boosted?: boolean
  content_kind?: string | null
  reading_status?: string | null
  facts?: { text: string; quote: string; article_id: number }[]
  evidence_article_ids?: number[]
}

export interface EventsResponse {
  events: EventOut[]
  next_cursor?: string | null
  as_of?: string
  window_start?: string | null
  window_end?: string
  sort?: FeedSort
  range?: FeedRange
}

export class FeedChangedError extends Error {}

export async function fetchEvents(
  sort: FeedSort = 'newest',
  range: FeedRange = '7d',
  cursor?: string,
  signal?: AbortSignal,
): Promise<EventsResponse> {
  const query = new URLSearchParams({ sort, range, limit: '50' })
  if (cursor) query.set('cursor', cursor)
  const res = await fetch(`/api/events?${query}`, { signal })
  if (res.status === 409) throw new FeedChangedError('Feed changed; restart pagination')
  if (!res.ok) throw new Error(`API ${res.status}`)
  return res.json() as Promise<EventsResponse>
}

export interface DigestResponse {
  report_date: string
  kind: string
  generated_at: string
  payload: {
    intro: string
    window_start: string
    window_end: string
    timezone: string
    events: EventOut[]
  }
}

export async function fetchDigest(
  date: string,
): Promise<DigestResponse | null> {
  const res = await fetch(`/api/digest/${encodeURIComponent(date)}`)
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`API ${res.status}`)
  return res.json() as Promise<DigestResponse>
}

export interface SourceFailure {
  source_id: string
  failures: number
  last_error: string | null
}

export interface LlmSpend {
  purpose: string
  model: string
  calls: number
  prompt_tokens: number
  completion_tokens: number
  cost_usd: number
}

export interface AbandonedArticle {
  id: number
  title: string
  source_id: string
}

export interface PipelineBacklog {
  pending_summaries: number
  pending_embeddings: number
  pending_scores: number
  abandoned_total: number
  abandoned_articles: AbandonedArticle[]
}

export interface LastRun {
  run_at: string
  summarized: number
  embedded: number
  clustered: number
  new_events: number
  scored: number
}

export interface ReportResponse {
  window_hours: number
  generated_at: string
  fetch_runs: number
  new_articles: number
  source_failures: SourceFailure[]
  llm_spend: LlmSpend[]
  llm_cost_total_usd: number
  backlog: PipelineBacklog
  last_run: LastRun | null
}

export async function fetchReport(): Promise<ReportResponse> {
  const res = await fetch('/api/report/daily')
  if (!res.ok) throw new Error(`API ${res.status}`)
  return res.json() as Promise<ReportResponse>
}

export interface FeedPreferences { sort: FeedSort; range: FeedRange; version: number }
export class StateConflict<T> extends Error {
  current: T
  constructor(current: T) { super('State changed on another device'); this.current = current }
}
async function stateRequest<T>(url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, body === undefined ? undefined : {
    method: 'PUT', headers: { 'Content-Type': 'application/json', Origin: window.location.origin }, body: JSON.stringify(body),
  })
  if (res.status === 409) {
    const data = await res.json() as { detail: { current: T } }
    throw new StateConflict(data.detail.current)
  }
  if (!res.ok) throw new Error(`API ${res.status}`)
  return res.json() as Promise<T>
}
export const fetchPreferences = () => stateRequest<FeedPreferences>('/api/feed-preferences')
export const savePreferences = (body: FeedPreferences) => stateRequest<FeedPreferences>('/api/feed-preferences', body)
