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
