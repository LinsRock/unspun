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
}

export interface EventsResponse {
  events: EventOut[]
}

export async function fetchEvents(): Promise<EventsResponse> {
  const res = await fetch('/api/events?limit=50')
  if (!res.ok) throw new Error(`API ${res.status}`)
  return res.json() as Promise<EventsResponse>
}
