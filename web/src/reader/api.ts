export type Sort = 'recommended' | 'latest'
export type Feedback = 'interested' | 'not_interested'
export interface InterestTarget { kind: 'domain' | 'term' | 'source' | 'author'; value: string; platform?: string | null; author_id?: string | null }
export interface ReaderState {
  version: number; sort: Sort
  interests: { resource_key: string; label: string; target: InterestTarget; support: { matching: string; collection: string; dedicated_author_collection: boolean } }[]
  feedback: { content_id: number; value: Feedback; version: number }[]
}
export interface Claim { text: string; quote: string; voice: string }
export interface Metadata {
  form: string; genre: string | null; platform: string | null; publisher: string | null
  authors: { name: string; role: string; platform: string | null; platform_id: string | null; basis: string }[]
  times: { kind: string; precision: string; at: string | null; on: string | null; basis: string | null }[]
  original_url: string | null; media_url: string | null; duration_seconds: number | null
}
export interface ContentItem {
  id: number; title: string; original_title: string; url: string; source_id: string; source_name: string
  channels: { id: string; name: string }[]; metadata: Metadata; material_scope: string; material_id: number; input_fingerprint: string
  card: { title_zh: string; genre: string; domains: string[]; claims: Claim[]; reading_value: number; reading_reason: Claim | null; model_input_truncated?: boolean }
  feedback: Feedback | null
  ranking: { reading_value?: number; current_value?: number; interest?: number; feedback?: number; similar_feedback?: number; diversity?: number; matched_interests?: string[]; total_score?: number }
}
export interface FeedPage { items: ContentItem[]; next_cursor: string | null; sort: Sort; as_of: string; ranking_version: string; preview: boolean; empty_reason: string | null }
export interface GuideState { status: string; reason: string | null; requestable: boolean; task_id: number | null; payload: { sections: { heading: string; claims: Claim[] }[] } | null }
export interface ContentDetail extends ContentItem {
  preview: boolean; requested_alias_id: number | null
  material: { scope: string; paragraphs: { kind: string; text: string }[]; retrieved_at: string; extractor_version: string }
  guide: GuideState
}
export class ReaderError extends Error {
  status: number
  current?: ReaderState
  constructor(status: number, current?: ReaderState) { super(`API ${status}`); this.status = status; this.current = current }
}
export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { ...options, cache: 'no-store', headers: { Accept: 'application/json', ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...options.headers } })
  if (!response.ok) {
    let current: ReaderState | undefined
    if (response.status === 409) { const body = await response.json() as { detail?: { current?: ReaderState } }; current = body.detail?.current }
    throw new ReaderError(response.status, current)
  }
  return response.json() as Promise<T>
}
export function getFeed(sort: Sort, cursor?: string, signal?: AbortSignal) {
  const query = new URLSearchParams({ sort, limit: '20' }); if (cursor) query.set('cursor', cursor)
  return request<FeedPage>(`/api/feed?${query}`, { signal })
}
export const getDetail = (id: number, signal?: AbortSignal) => request<ContentDetail>(`/api/contents/${id}`, { signal })
