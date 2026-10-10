export interface ArticleOut {
  id: number
  title: string
  title_zh: string | null
  url: string
  source_id: string
  source_name: string
  published_at: string | null
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
}

export interface ViewpointDisagreement {
  point: string
  claim_indexes: number[]
}

export interface ViewpointOut {
  claims: ViewpointClaim[]
  disagreements: ViewpointDisagreement[]
  model: string
  generated_at: string
}

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
}

export interface EventsResponse {
  events: EventOut[]
}

export async function fetchEvents(): Promise<EventsResponse> {
  const res = await fetch('/api/events?limit=50')
  if (!res.ok) throw new Error(`API ${res.status}`)
  return res.json() as Promise<EventsResponse>
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
