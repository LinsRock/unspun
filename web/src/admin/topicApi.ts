export type MemberRelation = 'report' | 'background' | 'opinion' | 'explanation' | 'reprint'
export type EvidenceVoice = 'reported' | 'author' | 'question' | 'description'
export interface VersionCheck { valid: boolean; reasons: string[] }
export interface TopicEvidence { article_id: number; material_id: number; paragraph: number; quote: string; voice: EvidenceVoice }
export interface TopicRow {
  id: string; kind: 'event' | 'issue'; title: string; domains: string[]; status: string; revision: number; active_member_count: number
}
export interface TopicMember {
  article_id: number; title: string; url: string; source_id: string; material_id: number; scope: string; active: boolean
  relation: MemberRelation; basis: string; decision_version: string; evidence: TopicEvidence[]; check: VersionCheck
}
export interface TopicChange {
  revision: number; mutation_id: string; actor: string; reason: string; command: Record<string, unknown>
  before: Record<string, unknown> | null; after: Record<string, unknown>; recorded_at: string
}
export interface TopicVersion {
  revision: number; kind?: string; update_id?: string; status: string; check: VersionCheck
  payload: Record<string, unknown>; contract?: Record<string, unknown>; contract_verification?: 'stored_contract_only'
}
export interface TopicDetail {
  topic: Omit<TopicRow, 'active_member_count'> & { definition_revision: number; created_at: string; updated_at: string }
  members: TopicMember[]; members_total: number; member_page: number; page_size: number
  changes: TopicChange[]; changes_total: number; history_page: number
  updates: TopicVersion[]; derivations: TopicVersion[]; updates_total: number; derivations_total: number; version_record_limit: number
}
export interface TopicPage { items: TopicRow[]; total: number; page: number; page_size: number; processing_enabled: boolean }
export interface MemberContent {
  article_id: number; requested_article_id: number; title: string; url: string; source_id: string; material_id: number; scope: string
  paragraphs: { index: number; text: string; voice: EvidenceVoice | null; allowed_voices: EvidenceVoice[] }[]
}
export interface MutationBase { mutation_id: string; expected_revision: number; reason: string }
export interface CreateTopicInput extends Omit<MutationBase, 'expected_revision'> { topic_id: string; kind: 'event' | 'issue'; title: string; domains: string[] }
export interface SetMemberInput extends MutationBase {
  article_id: number; material_id: number; relation: MemberRelation; basis: string; evidence: TopicEvidence[]
}
export interface MutationReceipt { topic_id: string; revision: number; mutation_id: string }
export interface MemberTask {
  id: number; kind: 'topic_recall' | 'topic_judge' | 'topic_review'; status: string; article_id: number | null
  source_id: string | null; object_key: string; strategy_version: string; attempts: number; failures: number; last_error: string | null
  created_at: string; finished_at: string | null; lease_until: string | null; result: Record<string, unknown> | null
}
export interface MemberTaskPage { items: MemberTask[]; total: number; page: number; page_size: number }
export interface MemberAttempt {
  id: number; status: string; claim_version: number; worker: string; started_at: string; ended_at: string | null; error: string | null
}
export interface MemberJudgment {
  input_fingerprint: string; task_id: number; article_id: number; topic_id: string; topic_revision: number; status: string
  applied_revision: number | null; decision: Record<string, unknown>; review: Record<string, unknown> | null; created_at: string
}
export interface MemberCall {
  id: string; stage: string | null; phase: string | null; status: string; model: string; task_id: number | null; task_attempt_id: number | null
  provider_generation_id: string | null; http_status: number | null; known_cost_usd: string | null; reserved_usd: string | null
  error: string | null; started_at: string; ended_at: string | null
}
export interface MemberTaskDetail {
  task: MemberTask; attempts: MemberAttempt[]; judgments: MemberJudgment[]; calls: MemberCall[]
  attempts_total: number; judgments_total: number; calls_total: number; record_limit: number
  costs: { known_usd: string; held_usd: string; unknown_requests: number; physical_requests: number }
}

export class TopicApiError extends Error {
  status: number
  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'TopicApiError'
    this.status = status
  }
}

async function topicRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api/admin/${path}`, { credentials: 'same-origin', cache: 'no-store', ...init })
  if (!response.ok) {
    const fallback = response.status === 409 ? '话题已变化，请刷新后重新审阅。' : response.status === 422 ? '材料或证据不符合保存条件，请检查原文后重试。' : `请求失败（${response.status}）`
    let detail = fallback
    try {
      const data = await response.json() as { detail?: unknown }
      if (typeof data.detail === 'string') detail = `${fallback} ${data.detail}`
    } catch { /* Preserve the status even if the response body is unavailable. */ }
    throw new TopicApiError(response.status, detail)
  }
  return await response.json() as T
}

export function getTopics(filters: { q?: string; status?: string; page: number }, signal?: AbortSignal) {
  const params = new URLSearchParams({ page: String(filters.page), page_size: '20' })
  if (filters.q) params.set('q', filters.q)
  if (filters.status) params.set('status', filters.status)
  return topicRequest<TopicPage>(`topics?${params}`, { signal })
}

export function getTopic(id: string, memberPage: number, historyPage: number, signal?: AbortSignal) {
  const params = new URLSearchParams({ member_page: String(memberPage), history_page: String(historyPage) })
  return topicRequest<TopicDetail>(`topics/${encodeURIComponent(id)}?${params}`, { signal })
}

export function getMemberContent(articleId: number, signal?: AbortSignal) {
  return topicRequest<MemberContent>(`member-contents/${articleId}`, { signal })
}

export function getMemberTasks(filters: { topic_id?: string; article_id?: number; status?: string; page: number }, signal?: AbortSignal) {
  const params = new URLSearchParams({ page: String(filters.page), page_size: '20' })
  if (filters.topic_id) params.set('topic_id', filters.topic_id)
  if (filters.article_id) params.set('article_id', String(filters.article_id))
  if (filters.status) params.set('status', filters.status)
  return topicRequest<MemberTaskPage>(`member-tasks?${params}`, { signal })
}

export function getMemberTask(id: number, signal?: AbortSignal) {
  return topicRequest<MemberTaskDetail>(`member-tasks/${id}`, { signal })
}

export type TopicWrite =
  | { kind: 'create'; body: CreateTopicInput }
  | { kind: 'member'; topicId: string; body: SetMemberInput }
  | { kind: 'remove'; topicId: string; articleId: number; body: MutationBase }

export function writeTopic(write: TopicWrite) {
  const path = write.kind === 'create' ? 'topics' : write.kind === 'member' ? `topics/${encodeURIComponent(write.topicId)}/members` : `topics/${encodeURIComponent(write.topicId)}/members/${write.articleId}/remove`
  return topicRequest<MutationReceipt>(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(write.body) })
}

export function memberCost(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '' || !Number.isFinite(Number(value))) return '费用未知'
  return `$${Number(value).toLocaleString('en-US', { maximumFractionDigits: 8 })}`
}
