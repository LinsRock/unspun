// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import App from '../App'
import { MemberTaskDrawer } from './MemberTasks'
import TopicEditor from './TopicEditor'
import TopicsPage from './TopicsPage'
import type { MemberContent, MemberTaskDetail, TopicDetail, TopicMember } from './topicApi'

const topicId = 'a0766133-d589-47fe-bfb6-e94190141150'
const quote = '这是该事件的真实原文材料，必须保留完整的来源归属。'
const topic: TopicDetail['topic'] = { id: topicId, title: '原文核验话题', kind: 'event', domains: ['technology'], status: 'active', revision: 7, definition_revision: 1, created_at: '2026-10-21T08:00:00Z', updated_at: '2026-10-22T08:00:00Z' }
const member: TopicMember = {
  article_id: 7, title: '成员原始报道', source_id: 'xinhua', material_id: 100, scope: 'open_text_unit', active: true, relation: 'report', basis: '该报道记述了本事件。', decision_version: 'r2-member-v6', evidence: [{ article_id: 7, material_id: 100, paragraph: 0, quote, voice: 'reported' }], check: { valid: true, reasons: [] },
  url: 'https://example.com/original',
}
const content: MemberContent = { article_id: 7, requested_article_id: 7, title: '成员原始报道', url: member.url, source_id: 'xinhua', material_id: 100, scope: 'open_text_unit', paragraphs: [{ index: 0, text: quote, voice: null, allowed_voices: ['reported', 'author', 'question', 'description'] }] }
const detail: TopicDetail = {
  topic, members: [member], members_total: 1, member_page: 1, page_size: 25,
  changes: [{ revision: 7, mutation_id: 'receipt-7', actor: 'reviewer@example.com', reason: '校正原文对应关系', command: { action: 'member' }, before: { relation: 'background' }, after: { relation: 'report' }, recorded_at: topic.updated_at }], changes_total: 1, history_page: 1,
  updates: [], updates_total: 0, derivations: [{ kind: 'overview', revision: 3, status: 'draft', payload: { claims: ['保留的旧概览'] }, contract: { version: 'retained-v1' }, contract_verification: 'stored_contract_only', check: { valid: false, reasons: ['derivation_input_changed'] } }], derivations_total: 1, version_record_limit: 100,
}

beforeEach(() => {
  sessionStorage.clear()
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
})
afterEach(() => { cleanup(); sessionStorage.clear(); vi.unstubAllGlobals() })

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } })
function renderQuery(element: ReactNode, path = '/admin/topics') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}>{element}</MemoryRouter></QueryClientProvider>)
}
function topicFetch(url: string) {
  if (url.startsWith(`/api/admin/topics/${topicId}?`)) return json(detail)
  if (url.startsWith('/api/admin/topics?')) return json({ items: [{ ...topic, active_member_count: 1 }], total: 1, page: 1, page_size: 20, processing_enabled: false })
  if (url.startsWith('/api/admin/member-tasks?')) return json({ items: [], total: 0, page: 1, page_size: 20 })
  if (url.startsWith('/api/admin/member-contents/')) return json(content)
  return json({ detail: 'Not found' }, 404)
}

test('topics load independently of date ranges and preserve evidence, history and invalidated drafts', async () => {
  const requests: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string) => { requests.push(url); return topicFetch(url) }))
  renderQuery(<App />, `/admin/topics?topic=${topicId}`)
  expect(await screen.findByText('成员自动处理当前关闭', {}, { timeout: 5000 })).toBeTruthy()
  expect(screen.queryByText('正在确认查询时间…')).toBeNull()
  expect(requests.some(url => url.startsWith('/api/admin/range'))).toBe(false)
  const members = await screen.findByRole('region', { name: '话题成员与证据' })
  expect(within(members).getByText(quote)).toBeTruthy()
  expect(within(members).getByRole('link', { name: '打开原文 ↗' }).getAttribute('href')).toBe(member.url)
  fireEvent.click(screen.getByRole('tab', { name: '修订历史（1）' }))
  expect(await screen.findByText('r7 · 校正原文对应关系')).toBeTruthy()
  expect(screen.getByText(/reviewer@example.com/)).toBeTruthy()
  expect(screen.getByText('修改前')).toBeTruthy()
  expect(screen.getByText('修改后')).toBeTruthy()
  fireEvent.click(screen.getByRole('tab', { name: '更新与派生版本' }))
  const versions = await screen.findByRole('region', { name: '保留的派生版本' })
  expect(within(versions).getByText('已失效')).toBeTruthy()
  expect(within(versions).getByText('派生依据已变化')).toBeTruthy()
  expect(within(versions).getByText(/保留的旧概览/)).toBeTruthy()
}, 15_000)

test('create requires a human reason and submits an authenticated manual topic', async () => {
  let body: Record<string, unknown> | null = null
  const onSaved = vi.fn()
  vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
    body = JSON.parse(String(init?.body)) as Record<string, unknown>
    expect(init?.credentials).toBe('same-origin')
    return json({ topic_id: body.topic_id, revision: 1, mutation_id: body.mutation_id }, 201)
  }))
  renderQuery(<TopicEditor mode="create" onClose={vi.fn()} onSaved={onSaved} onRefresh={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('话题名称'), { target: { value: '新建人工议题' } })
  fireEvent.mouseDown(screen.getByLabelText('领域（1–3 个）'))
  fireEvent.click(await screen.findByText('科技'))
  fireEvent.click(screen.getByRole('button', { name: '建立话题' }))
  expect(await screen.findByText('请填写本次人工操作的原因。')).toBeTruthy()
  expect(body).toBeNull()
  fireEvent.change(screen.getByLabelText('建立原因'), { target: { value: '由原文确认需要单独归组' } })
  fireEvent.click(screen.getByRole('button', { name: '建立话题' }))
  await waitFor(() => expect(onSaved).toHaveBeenCalledOnce())
  expect(body).toMatchObject({ title: '新建人工议题', domains: ['technology'], reason: '由原文确认需要单独归组' })
  expect(body).not.toHaveProperty('expected_revision')
  expect(body).not.toHaveProperty('actor')
  expect(body).not.toHaveProperty('change')
}, 10_000)

test('add member uses the canonical ID and exact selected original quote', async () => {
  let body: Record<string, unknown> | null = null
  const onSaved = vi.fn()
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      body = JSON.parse(String(init.body)) as Record<string, unknown>
      return json({ topic_id: topicId, revision: 8, mutation_id: body.mutation_id })
    }
    expect(url).toBe('/api/admin/member-contents/3')
    return json({ ...content, requested_article_id: 3 })
  }))
  renderQuery(<TopicEditor mode="member" topic={topic} onClose={vi.fn()} onSaved={onSaved} onRefresh={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('内容 ID'), { target: { value: '3' } })
  fireEvent.click(screen.getByRole('button', { name: '载入材料' }))
  expect(await screen.findByText('该内容已归并，保存时使用规范内容 #7。')).toBeTruthy()
  const source = screen.getByLabelText('可选择的原文') as HTMLTextAreaElement
  const selected = quote.slice(0, 16)
  source.focus()
  source.setSelectionRange(0, 16)
  fireEvent.mouseUp(source)
  fireEvent.select(source)
  await waitFor(() => expect((screen.getByLabelText('已选原文') as HTMLTextAreaElement).value).toBe(selected))
  fireEvent.click(screen.getByRole('button', { name: '加入这处证据' }))
  expect(await screen.findByText('请按原文选择这处证据的视角。')).toBeTruthy()
  fireEvent.mouseDown(screen.getByLabelText('原文视角'))
  fireEvent.click(await screen.findByText('报道事实'))
  fireEvent.click(screen.getByRole('button', { name: '加入这处证据' }))
  fireEvent.change(screen.getByLabelText('关联依据'), { target: { value: '原文直接报道该事件' } })
  fireEvent.change(screen.getByLabelText('修改原因'), { target: { value: '补入遗漏的直接报道' } })
  fireEvent.click(screen.getByRole('button', { name: '保存成员' }))
  expect(await screen.findByText('请明确选择成员关系。')).toBeTruthy()
  fireEvent.mouseDown(screen.getByLabelText('成员关系'))
  fireEvent.click(await screen.findByText('直接报道'))
  fireEvent.click(screen.getByRole('button', { name: '保存成员' }))
  await waitFor(() => expect(onSaved).toHaveBeenCalledOnce())
  expect(body).toMatchObject({ article_id: 7, material_id: 100, expected_revision: 7, evidence: [{ article_id: 7, material_id: 100, paragraph: 0, voice: 'reported', quote: selected }] })
  expect(body).not.toHaveProperty('decision_version')
}, 10_000)

test('editing author evidence preserves its voice when the original allows it', async () => {
  let body: Record<string, unknown> | null = null
  const onSaved = vi.fn()
  const author: TopicMember = { ...member, relation: 'opinion', evidence: member.evidence.map(item => ({ ...item, voice: 'author' })) }
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method !== 'POST') return topicFetch(url)
    body = JSON.parse(String(init.body)) as Record<string, unknown>
    return json({ topic_id: topicId, revision: 8, mutation_id: body.mutation_id })
  }))
  renderQuery(<TopicEditor mode="member" topic={topic} member={author} onClose={vi.fn()} onSaved={onSaved} onRefresh={vi.fn()} />)
  await screen.findByLabelText('可选择的原文')
  fireEvent.change(screen.getByLabelText('修改原因'), { target: { value: '确认作者自述，保留其视角' } })
  fireEvent.click(screen.getByRole('button', { name: '保存成员' }))
  await waitFor(() => expect(onSaved).toHaveBeenCalledOnce())
  expect(body).toMatchObject({ relation: 'opinion', evidence: [{ ...member.evidence[0], voice: 'author' }] })
})

test('network retry after reopening keeps the identical mutation and payload', async () => {
  const writes: Record<string, unknown>[] = []
  const onSaved = vi.fn()
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method !== 'POST') return topicFetch(url)
    writes.push(JSON.parse(String(init.body)) as Record<string, unknown>)
    expect(init.credentials).toBe('same-origin')
    if (writes.length === 1) throw new TypeError('Network unavailable')
    return json({ topic_id: topicId, revision: 8, mutation_id: writes[0]?.mutation_id })
  }))
  const editor = <TopicEditor mode="member" topic={topic} member={member} onClose={vi.fn()} onSaved={onSaved} onRefresh={vi.fn()} />
  const first = renderQuery(editor)
  await screen.findByLabelText('可选择的原文')
  fireEvent.change(screen.getByLabelText('修改原因'), { target: { value: '确认来源归属' } })
  fireEvent.click(screen.getByRole('button', { name: '保存成员' }))
  expect(await screen.findByText(/尚未确认保存结果/)).toBeTruthy()
  expect((screen.getByLabelText('修改原因') as HTMLTextAreaElement).disabled).toBe(true)
  first.unmount()
  renderQuery(editor)
  fireEvent.click(screen.getByRole('button', { name: '重试同一提交' }))
  await waitFor(() => expect(onSaved).toHaveBeenCalledOnce())
  expect(writes).toHaveLength(2)
  expect(writes[0]).toEqual(writes[1])
  expect(sessionStorage.length).toBe(0)
}, 10_000)

test('CAS conflict stops saving until stale edit is discarded and reviewed again', async () => {
  const refresh = vi.fn()
  const writes: RequestInit[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method !== 'POST') return topicFetch(url)
    writes.push(init)
    return json({ detail: 'topic revision changed' }, 409)
  }))
  renderQuery(<TopicEditor mode="member" topic={topic} member={member} onClose={vi.fn()} onSaved={vi.fn()} onRefresh={refresh} />)
  await screen.findByLabelText('可选择的原文')
  fireEvent.change(screen.getByLabelText('修改原因'), { target: { value: '校正成员' } })
  fireEvent.click(screen.getByRole('button', { name: '保存成员' }))
  expect(await screen.findByText(/话题修订或操作收据已变化/)).toBeTruthy()
  expect((screen.getByRole('button', { name: /重试同一提交/ }) as HTMLButtonElement).disabled).toBe(true)
  expect(writes).toHaveLength(1)
  fireEvent.click(screen.getByRole('button', { name: '刷新并重新审阅' }))
  expect(refresh).toHaveBeenCalledOnce()
  expect(sessionStorage.length).toBe(0)
}, 10_000)

test('stale material evidence cannot be submitted under a fresh material ID', async () => {
  const fetchMock = vi.fn(async () => json({ ...content, material_id: 101 }))
  vi.stubGlobal('fetch', fetchMock)
  renderQuery(<TopicEditor mode="member" topic={topic} member={member} onClose={vi.fn()} onSaved={vi.fn()} onRefresh={vi.fn()} />)
  await screen.findByLabelText('可选择的原文')
  fireEvent.change(screen.getByLabelText('修改原因'), { target: { value: '检查新材料' } })
  fireEvent.click(screen.getByRole('button', { name: '保存成员' }))
  expect(await screen.findByText(/已有证据属于旧材料/)).toBeTruthy()
  expect(fetchMock).toHaveBeenCalledTimes(1)
})

test('refreshing a conflict blocks another edit until the current revision arrives', async () => {
  let holdRefresh = false
  let releaseRefresh: (() => void) | undefined
  let revision = 7
  const writes: Record<string, unknown>[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === 'POST') {
      writes.push(JSON.parse(String(init.body)) as Record<string, unknown>)
      if (writes.length === 1) { revision = 8; return json({ detail: 'topic revision changed' }, 409) }
      return json({ topic_id: topicId, revision: 9, mutation_id: writes[1]?.mutation_id })
    }
    if (url.startsWith(`/api/admin/topics/${topicId}?`)) {
      if (holdRefresh) await new Promise<void>(resolve => { releaseRefresh = resolve })
      return json({ ...detail, topic: { ...topic, revision } })
    }
    return topicFetch(url)
  }))
  renderQuery(<TopicsPage />, `/admin/topics?topic=${topicId}`)
  fireEvent.click(await screen.findByRole('button', { name: '修正成员' }))
  await screen.findByLabelText('可选择的原文')
  fireEvent.change(screen.getByLabelText('修改原因'), { target: { value: '旧版本编辑' } })
  fireEvent.click(screen.getByRole('button', { name: '保存成员' }))
  const refresh = await screen.findByRole('button', { name: '刷新并重新审阅' })
  holdRefresh = true
  fireEvent.click(refresh)
  await screen.findByText('正在刷新当前修订，请稍候再编辑…')
  expect((screen.getByRole('button', { name: '修正成员' }) as HTMLButtonElement).disabled).toBe(true)
  holdRefresh = false
  releaseRefresh!()
  await waitFor(() => expect((screen.getByRole('button', { name: '修正成员' }) as HTMLButtonElement).disabled).toBe(false))
  fireEvent.click(screen.getByRole('button', { name: '修正成员' }))
  await screen.findByLabelText('可选择的原文')
  expect((screen.getByLabelText('修改原因') as HTMLTextAreaElement).value).toBe('')
  fireEvent.change(screen.getByLabelText('修改原因'), { target: { value: '已审阅最新版本' } })
  fireEvent.click(screen.getByRole('button', { name: '保存成员' }))
  await waitFor(() => expect(writes).toHaveLength(2))
  expect(writes[1]).toMatchObject({ expected_revision: 8, reason: '已审阅最新版本' })
}, 10_000)

test('remove member sends only its current revision, operation ID and human reason', async () => {
  let body: Record<string, unknown> | null = null
  const onSaved = vi.fn()
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    expect(url).toBe(`/api/admin/topics/${topicId}/members/7/remove`)
    body = JSON.parse(String(init?.body)) as Record<string, unknown>
    return json({ topic_id: topicId, revision: 8, mutation_id: body.mutation_id })
  }))
  renderQuery(<TopicEditor mode="remove" topic={topic} member={member} onClose={vi.fn()} onSaved={onSaved} onRefresh={vi.fn()} />)
  fireEvent.change(screen.getByLabelText('修改原因'), { target: { value: '原文不支持当前归属' } })
  fireEvent.click(screen.getByRole('button', { name: '确认移除成员' }))
  await waitFor(() => expect(onSaved).toHaveBeenCalledOnce())
  expect(Object.keys(body!)).toEqual(['mutation_id', 'expected_revision', 'reason'])
  expect(body).toMatchObject({ expected_revision: 7, reason: '原文不支持当前归属' })
})

test('task drilldown shows review tasks, raw audit receipts and unknown costs without replacing them with zero', async () => {
  const data: MemberTaskDetail = {
    task: { id: 9, kind: 'topic_review', status: 'blocked', article_id: 7, source_id: 'xinhua', object_key: 'member:7', strategy_version: 'r2-member-v6', attempts: 1, failures: 0, last_error: 'usage_unknown', result: null, created_at: topic.created_at, finished_at: null, lease_until: null },
    attempts: [{ id: 10, claim_version: 1, status: 'blocked', worker: 'retained-worker', started_at: topic.created_at, ended_at: topic.updated_at, error: 'usage_unknown' }], attempts_total: 1,
    judgments: [{ input_fingerprint: 'frozen-fingerprint', task_id: 8, article_id: 7, topic_id: topicId, topic_revision: 6, decision: { classification: 'related' }, review: { status: 'rejected', reason: '原始审核拒绝依据' }, status: 'rejected', applied_revision: null, created_at: topic.created_at }], judgments_total: 1,
    calls: [{ id: 'physical-call-1', stage: 'member_review', phase: 'support', status: 'usage_unknown', model: 'frozen-model', task_id: 9, task_attempt_id: 10, provider_generation_id: 'provider-receipt', http_status: 429, known_cost_usd: null, reserved_usd: '0.03', error: 'usage_unknown', started_at: topic.created_at, ended_at: null }], calls_total: 1,
    costs: { known_usd: '0', held_usd: '0.03', unknown_requests: 1, physical_requests: 1 }, record_limit: 100,
  }
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    expect(url).toBe('/api/admin/member-tasks/9')
    expect(init?.method).toBeUndefined()
    return json(data)
  }))
  renderQuery(<MemberTaskDrawer id={9} onClose={vi.fn()} onTopic={vi.fn()} />)
  expect(await screen.findByText('成员审核')).toBeTruthy()
  expect(screen.getByText('费用未知')).toBeTruthy()
  expect(screen.getByText('费用尚未完整确认')).toBeTruthy()
  expect(screen.getByText('本任务费用')).toBeTruthy()
  expect(screen.getAllByText('$0.03')).toHaveLength(2)
  expect(screen.getByText(/原始审核拒绝依据/)).toBeTruthy()
  expect(screen.getByText('physical-call-1')).toBeTruthy()
  expect(screen.getByText(/provider-receipt/)).toBeTruthy()
  expect(screen.queryByRole('button', { name: /重试任务|重新运行|开启处理/ })).toBeNull()
}, 10_000)

test('topic list filters use the real topic endpoint', async () => {
  const requests: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string) => { requests.push(url); return topicFetch(url) }))
  renderQuery(<TopicsPage />, '/admin/topics?q=%E5%8E%9F%E6%96%87&status=active&page=2')
  expect(await screen.findByText('原文核验话题')).toBeTruthy()
  expect(requests).toContain('/api/admin/topics?page=2&page_size=20&q=%E5%8E%9F%E6%96%87&status=active')
})
