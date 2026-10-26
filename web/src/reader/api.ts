export type Sort = 'recommended' | 'latest'
export type Feedback = 'interested' | 'not_interested'
export interface InterestTarget { kind: 'domain' | 'term' | 'source' | 'author'; value: string; platform?: string | null; author_id?: string | null }
export interface ReaderState {
  version: number; sort: Sort
  interests: { resource_key: string; label: string; target: InterestTarget; support: { matching: string; collection: string; dedicated_author_collection: boolean } }[]
  feedback: { content_id: number; value: Feedback; version: number }[]
  topic_preferences?: { target: { type: 'topic'; id: string }; followed: boolean; feedback: Feedback | null; version: number }[]
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
export function mutationId(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  // Local LAN previews are HTTP; getRandomValues is available there as well.
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6]! & 15) | 64
  bytes[8] = (bytes[8]! & 63) | 128
  const hex = Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}
export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, { ...options, cache: 'no-store', headers: { Accept: 'application/json', ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...options.headers } })
  if (response.redirected && response.headers.get('content-type')?.includes('text/html')) throw new ReaderError(401)
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

export interface Capabilities { hybrid: boolean; topic_preferences: boolean; home: 'events' | 'discover'; engineering_preview: boolean }
export type Target = { type: 'content'; id: number } | { type: 'topic'; id: string }
export interface TopicTime { kind?: string; precision: 'time' | 'date' | 'unknown'; at?: string | null; on?: string | null; basis?: string | null }
export interface TopicClaim {
  text: string; attribution: string; limitations: string[]
  evidence: { article_id: number; material_id: number; paragraph: number; quote: string; voice: string }[]
}
export interface Progress extends TopicClaim { classification: string; occurred: TopicTime; reported: TopicTime; progress_key: string | null }
export interface TopicDetail {
  id: string; title: string; kind: string; domains: string[]; version: string; revision: number
  overview: TopicClaim[]; guide: TopicClaim[]; progress: Progress[]; context: Progress[]
  related: (ContentItem & { relation: string })[]; engineering_preview: boolean
}
export interface HybridItem {
  type: 'content' | 'topic'; id: string; title: string; version: string; time: TopicTime
  presentation: 'full' | 'reference'; reference_to: string[]
  content: (Omit<ContentItem, 'card'> & { card?: ContentItem['card'] }) | null
  topic: { overview: TopicClaim[]; engineering_preview?: boolean; material_scope: { source_id: string; scope: string }[] } | null
  ranking: ContentItem['ranking'] & { followed?: boolean; follow_boost?: number; feedback_value?: Feedback | null; important?: unknown; public_attention?: unknown; missing_signals?: string[] }
}
export interface HybridPage { items: HybridItem[]; next_cursor: string | null; sort: Sort; as_of: string; snapshot: string; engineering_preview?: boolean }
export function getHybridFeed(sort: Sort, cursor?: string, signal?: AbortSignal) {
  const query = new URLSearchParams({ mode: 'mixed', sort, limit: '10' }); if (cursor) query.set('cursor', cursor)
  return request<HybridPage>(`/api/feed?${query}`, { signal })
}
export const getTopic = (id: string, signal?: AbortSignal) => request<TopicDetail>(`/api/topics/${encodeURIComponent(id)}`, { signal })
