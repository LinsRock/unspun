// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import HybridPage from './HybridPage'
import TopicPage from './TopicPage'
import ContentPage from './ContentPage'
import InterestsPage from './InterestsPage'
import type { ContentDetail, HybridItem, HybridPage as Page, ReaderState, TopicDetail } from './api'
import { mutationId } from './api'
import { readingPositions, readingReturn } from './navigation'

const id = '12345678-1234-4234-8234-123456789abc'
const material: ContentDetail = {
  id: 10, title: '独立文章', original_title: 'Original',
  url: 'https://example.org/10',
  source_id: 'xinhua', source_name: '新华社', channels: [],
  metadata: { form: 'article', genre: 'news', platform: null, publisher: null, authors: [], times: [], original_url: null, media_url: null, duration_seconds: null },
  material_scope: 'preview', material_id: 1, input_fingerprint: 'fixture',
  card: { title_zh: '独立文章', genre: 'news', domains: ['science'], claims: [{ text: '作者主张需要保留语境。', quote: '原始引用内容。', voice: 'author' }], reading_value: 2, reading_reason: null },
  feedback: null, ranking: {}, preview: false, requested_alias_id: null,
  material: { scope: 'preview', paragraphs: [{ kind: 'paragraph', text: '只取得的材料' }], retrieved_at: '2026-10-23T08:00:00Z', extractor_version: 'test' },
  guide: { status: 'unavailable', reason: null, requestable: false, payload: null, task_id: null },
}
const claim = { text: '已有材料中的计划尚未实施。', attribution: '报道转述', limitations: ['仅据现有材料。'], evidence: [{ article_id: 10, material_id: 1, paragraph: 0, quote: '原文中的完整引用，计划尚未实施。', voice: 'reported' }] }
const detail: TopicDetail = { id, title: '工程话题', kind: 'issue', domains: ['science'], version: 'v1', revision: 3, overview: [claim], guide: [claim], progress: [{ ...claim, classification: 'development', progress_key: 'one', occurred: { precision: 'date', on: '2026-10-20', basis: '材料明确日期' }, reported: { precision: 'unknown' } }], context: [{ ...claim, classification: 'opinion', progress_key: null, occurred: { precision: 'unknown' }, reported: { precision: 'unknown' } }], related: [{ ...material, relation: 'opinion' }], engineering_preview: true }
const topic: HybridItem = { type: 'topic', id, title: '工程话题', version: 'v1', time: { kind: 'occurred', precision: 'date', on: '2026-10-20' }, presentation: 'full', reference_to: [], content: null, topic: { overview: [claim], engineering_preview: true, material_scope: [{ source_id: 'xinhua', scope: 'preview' }] }, ranking: {} }
const content: HybridItem = { type: 'content', id: '10', title: '独立文章', version: 'v1', time: { kind: 'original', precision: 'unknown' }, presentation: 'full', reference_to: [], content: material, topic: null, ranking: {} }
let state: ReaderState
let calls: { path: string; method: string; body?: Record<string, unknown> }[]
let page: Page
function setup(path = '/discover') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><Routes><Route path="/discover" element={<HybridPage />} /><Route path="/topics/:id" element={<TopicPage />} /><Route path="/reading/:id" element={<ContentPage />} /><Route path="/interests" element={<InterestsPage />} /></Routes></MemoryRouter></QueryClientProvider>)
  return client
}
beforeEach(() => {
  readingPositions.clear()
  state = { version: 0, sort: 'recommended', interests: [], feedback: [], topic_preferences: [] }
  page = { items: structuredClone([topic, content]), next_cursor: null, sort: 'recommended', as_of: '2026-10-23T08:00:00Z', snapshot: 'v1', engineering_preview: true }; calls = []
  vi.stubGlobal('scrollTo', vi.fn())
  vi.stubGlobal('fetch', vi.fn(async (path: string, options?: RequestInit) => {
    const method = options?.method ?? 'GET'
    const body = options?.body ? JSON.parse(String(options.body)) as Record<string, unknown> : undefined
    calls.push({ path, method, body })
    if (path === '/api/reading-capabilities') return Response.json({ hybrid: true, topic_preferences: true, home: 'discover', engineering_preview: true })
    if (path === '/api/topic-preferences') return Response.json(state)
    if (path.startsWith('/api/feed?')) return Response.json(page)
    if (path === `/api/topics/${id}`) return Response.json(detail)
    if (path === '/api/contents/10') return Response.json(material)
    if (path === '/api/reader-preferences' && method === 'PUT') { state = { ...state, version: state.version + 1, sort: body?.sort as ReaderState['sort'] }; const { topic_preferences: _topics, ...old } = state; return Response.json(old) }
    if (path === '/api/topic-follows') {
      if (body?.version !== state.version) return Response.json({ detail: { current: state } }, { status: 409 })
      state = { ...state, version: state.version + 1, topic_preferences: method === 'DELETE' ? [] : [{ target: { type: 'topic', id }, followed: true, feedback: null, version: state.version + 1 }] }
      return Response.json(state)
    }
    if (path === '/api/target-feedback') {
      state = { ...state, version: state.version + 1, feedback: method === 'DELETE' ? [] : [{ content_id: 10, value: body?.value as 'interested', version: state.version + 1 }] }
      return Response.json(state)
    }
    return Response.json({}, { status: 404 })
  }))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('renders both types, scopes, truthful reasons and page-local references', async () => {
  page.items[1] = { ...content, presentation: 'reference', reference_to: [id], content: { ...material, card: undefined } }
  setup()
  await screen.findByRole('link', { name: '工程话题' })
  expect(screen.getByRole('button', { name: '推荐' }).getAttribute('aria-pressed')).toBe('true')
  expect(screen.getByText(/重复概况已在本页/)).toBeTruthy()
  expect(screen.queryByText('作者主张需要保留语境。')).toBeNull()
  expect(screen.getByRole('link', { name: '独立文章' }).getAttribute('href')).toBe('/reading/10')
  expect(screen.getAllByText(/暂无直接公共关注观测/).length).toBe(2)
})

it('latest keeps server order and distinguishes date precision from unknown', async () => {
  page.items = [content, topic]
  setup('/discover?sort=latest')
  await screen.findByRole('link', { name: '工程话题' })
  expect(screen.getAllByRole('heading', { level: 2 }).map(h => h.textContent)).toEqual(['独立文章', '工程话题'])
  expect(screen.getByText(/2026-10-20（仅日期）/)).toBeTruthy()
  expect(screen.getByText('原始发布未知')).toBeTruthy()
  expect(calls.some(c => c.path.includes('sort=latest'))).toBe(true)
})

it.each([400, 409])('discards an invalid snapshot (%s) and restarts at the first page', async status => {
  page.next_cursor = 'second'
  const original = vi.mocked(fetch).getMockImplementation()!
  vi.stubGlobal('fetch', vi.fn((path: string, options?: RequestInit) => path.includes('cursor=second') ? Promise.resolve(Response.json({ detail: 'hybrid_changed_restart' }, { status })) : original(path, options)))
  setup(); await screen.findByRole('link', { name: '工程话题' })
  fireEvent.click(screen.getByRole('button', { name: '继续阅读' }))
  await screen.findByRole('alert')
  expect(screen.queryByRole('link', { name: '工程话题' })).toBeNull()
  page.next_cursor = null
  fireEvent.click(screen.getByRole('button', { name: '重新加载' }))
  await screen.findByRole('link', { name: '工程话题' })
})

it('shows current CAS state and waits for a new user action', async () => {
  setup(); await screen.findByRole('button', { name: '关注话题' })
  state = { ...state, version: 4, topic_preferences: [{ target: { type: 'topic', id }, followed: true, feedback: null, version: 4 }] }
  fireEvent.click(screen.getByRole('button', { name: '关注话题' }))
  await screen.findByText(/另一台设备已更新设置/)
  expect((await screen.findByRole('button', { name: '已关注 · 取消' })).getAttribute('aria-pressed')).toBe('true')
  expect(calls.filter(c => c.path === '/api/topic-follows')).toHaveLength(1)
  fireEvent.click(screen.getByRole('button', { name: '已关注 · 取消' }))
  await screen.findByRole('button', { name: '关注话题' })
  expect(calls.filter(c => c.path === '/api/topic-follows')[1]?.body?.version).toBe(4)
})

it('modifies and revokes typed content feedback', async () => {
  setup(); await screen.findByRole('link', { name: '独立文章' })
  const actions = () => screen.getByRole('group', { name: '独立文章的偏好' })
  fireEvent.click(within(actions()).getByRole('button', { name: '感兴趣' }))
  await screen.findByRole('button', { name: '撤销感兴趣' })
  fireEvent.click(within(actions()).getByRole('button', { name: '不感兴趣' }))
  await screen.findByRole('button', { name: '撤销不感兴趣' })
  fireEvent.click(within(actions()).getByRole('button', { name: '撤销不感兴趣' }))
  await waitFor(() => expect(within(actions()).getByRole('button', { name: '不感兴趣' })).toBeTruthy())
  expect(calls.filter(c => c.path === '/api/target-feedback').map(c => c.method)).toEqual(['PUT', 'PUT', 'DELETE'])
  expect(calls.find(c => c.path === '/api/target-feedback')?.body?.target).toEqual({ type: 'content', id: 10 })
})

it('returns through topic and content details to the original sort', async () => {
  setup('/discover?sort=latest'); await screen.findByRole('link', { name: '工程话题' })
  fireEvent.click(screen.getByRole('link', { name: '工程话题' }))
  await screen.findByRole('heading', { name: '话题概况' })
  expect(screen.getByRole('link', { name: '← 返回阅读列表' }).getAttribute('href')).toBe('/discover?sort=latest')
  expect(screen.getByText('发生时间 2026-10-20（仅日期） · 报道时间未知')).toBeTruthy()
  fireEvent.click(screen.getByRole('link', { name: '独立文章' }))
  await screen.findByRole('heading', { name: '已审核要点' })
  fireEvent.click(screen.getByRole('link', { name: '← 返回话题' }))
  await screen.findByRole('heading', { name: '话题概况' })
  expect(screen.getByRole('link', { name: '← 返回阅读列表' }).getAttribute('href')).toBe('/discover?sort=latest')
})

it('keeps all pages and scroll position when returning from a detail', async () => {
  page = { ...page, items: [topic], next_cursor: 'second' }
  const original = vi.mocked(fetch).getMockImplementation()!
  vi.stubGlobal('fetch', vi.fn((path: string, options?: RequestInit) => path.includes('cursor=second') ? Promise.resolve(Response.json({ ...page, items: [content], next_cursor: null })) : original(path, options)))
  setup(); await screen.findByRole('button', { name: '继续阅读' }); fireEvent.click(screen.getByRole('button', { name: '继续阅读' }))
  await screen.findByRole('link', { name: '独立文章' })
  vi.stubGlobal('scrollY', 960)
  fireEvent.click(screen.getByRole('link', { name: '独立文章' }))
  await screen.findByRole('heading', { name: '已审核要点' })
  fireEvent.click(screen.getByRole('link', { name: '← 返回阅读列表' }))
  await screen.findByRole('link', { name: '独立文章' })
  await waitFor(() => expect(scrollTo).toHaveBeenLastCalledWith(0, 960))
  expect(screen.getByRole('link', { name: '工程话题' })).toBeTruthy()
})

it('lets unavailable followed topics be revoked without leaking stale titles', async () => {
  state.topic_preferences = [{ target: { type: 'topic', id }, followed: true, feedback: null, version: 0 }]
  const original = vi.mocked(fetch).getMockImplementation()!
  vi.stubGlobal('fetch', vi.fn((path: string, options?: RequestInit) => path.startsWith('/api/topics/') ? Promise.resolve(Response.json({}, { status: 404 })) : original(path, options)))
  setup('/interests'); await screen.findByText(/暂时无法读取当前话题/)
  expect(screen.queryByText('工程话题')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '已关注 · 取消' }))
  await screen.findByText('尚未保存话题偏好。')
})

it.each([401, 404, 503])('explains API failure %s without showing an empty success', async status => {
  const original = vi.mocked(fetch).getMockImplementation()!
  vi.stubGlobal('fetch', vi.fn((path: string, options?: RequestInit) => path.startsWith('/api/feed?') ? Promise.resolve(Response.json({}, { status })) : original(path, options)))
  setup(); await screen.findByRole('alert')
  expect(screen.queryByText('暂时没有可公开的话题或内容')).toBeNull()
  if (status === 401) expect(screen.getByRole('link', { name: '重新登录并加载' })).toBeTruthy()
})

it('renders an honest empty result and rejects unsafe return locations', async () => {
  page.items = []; setup(); await screen.findByText('暂时没有可公开的话题或内容')
  expect(readingReturn('//evil.example')).toBe('/discover')
  expect(readingReturn('/topics/' + id)).toBe('/topics/' + id)
})

it('loads current typed preferences after a conflict from an old reader endpoint', async () => {
  const original = vi.mocked(fetch).getMockImplementation()!
  vi.stubGlobal('fetch', vi.fn((path: string, options?: RequestInit) => {
    if (path === '/api/reader-preferences' && options?.method === 'PUT') {
      state = { ...state, version: 9, topic_preferences: [{ target: { type: 'topic', id }, followed: true, feedback: null, version: 9 }] }
      const { topic_preferences: _topics, ...current } = state
      return Promise.resolve(Response.json({ detail: { current } }, { status: 409 }))
    }
    return original(path, options)
  }))
  setup(); await screen.findByRole('link', { name: '工程话题' })
  fireEvent.click(screen.getByRole('button', { name: '最新' }))
  await screen.findByText(/另一台设备已更新设置/)
  await screen.findByRole('button', { name: '已关注 · 取消' })
  expect(screen.getByRole('button', { name: '推荐' }).getAttribute('aria-pressed')).toBe('true')
})

it('keeps an explicit loading state while the feed is pending', async () => {
  const original = vi.mocked(fetch).getMockImplementation()!
  vi.stubGlobal('fetch', vi.fn((path: string, options?: RequestInit) => path.startsWith('/api/feed?') ? new Promise<Response>(() => {}) : original(path, options)))
  setup(); await screen.findByRole('button', { name: '推荐' })
  expect(screen.getByLabelText('正在加载阅读内容')).toBeTruthy()
  expect(screen.queryByText('暂时没有可公开的话题或内容')).toBeNull()
})

it('reports network failure and recovers without retaining an invalid list', async () => {
  const original = vi.mocked(fetch).getMockImplementation()!
  let broken = true
  vi.stubGlobal('fetch', vi.fn((path: string, options?: RequestInit) => path.startsWith('/api/feed?') && broken ? Promise.reject(new TypeError('offline')) : original(path, options)))
  setup(); await screen.findByText('暂时无法连接服务器。请检查网络后重试。')
  broken = false
  fireEvent.click(screen.getByRole('button', { name: '重新加载' }))
  await screen.findByRole('link', { name: '工程话题' })
})

it('uses cryptographic UUIDs on the HTTP LAN preview without randomUUID', () => {
  vi.stubGlobal('crypto', { getRandomValues: (bytes: Uint8Array) => bytes.fill(255) })
  expect(mutationId()).toBe('ffffffff-ffff-4fff-bfff-ffffffffffff')
})
