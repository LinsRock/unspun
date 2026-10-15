// @vitest-environment jsdom
import { onlineManager, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import FeedPage from './FeedPage'
import EventCard from './EventCard'
import type { EventOut } from './api'

const event: EventOut = { id: 1, title: '事件一', summary_zh: null, score_final: 60, score_decayed: null, score_breakdown: null, first_seen_at: '2026-10-14T00:00:00Z', changed_at: '2026-10-14T03:00:00Z', articles: [], viewpoint: null }
beforeEach(() => { localStorage.clear(); onlineManager.setOnline(true) })
function stubFetch(fetch: (url: string, options?: RequestInit) => unknown) {
  vi.stubGlobal('fetch', (url: string, options?: RequestInit) => url === '/api/feed-preferences' ? Promise.resolve({ ok: true, json: async () => ({ sort: 'newest', range: '7d', version: options?.method === 'PUT' ? 1 : 0 }) }) : fetch(url, options))
}
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals() })
function mount(path = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><FeedPage /></MemoryRouter></QueryClientProvider>)
}
function response(events: EventOut[] = [], next_cursor: string | null = null) {
  return { ok: true, json: async () => ({ events, next_cursor, as_of: '2026-10-14T05:00:00Z', window_start: '2026-10-07T05:00:00Z', window_end: '2026-10-14T05:00:00Z' }) }
}
test('defaults to latest seven days and keeps range while changing sort', async () => {
  const fetch = vi.fn().mockResolvedValue(response()); stubFetch(fetch)
  mount()
  await waitFor(() => expect(fetch).toHaveBeenCalled())
  expect(String(fetch.mock.calls[0]![0])).toContain('sort=newest')
  expect(String(fetch.mock.calls[0]![0])).toContain('range=7d')
  fireEvent.change(screen.getByRole('combobox', { name: '时间范围' }), { target: { value: '24h' } })
  await waitFor(() => expect(String(fetch.mock.calls.at(-1)![0])).toContain('range=24h'))
  fireEvent.click(screen.getByRole('button', { name: '重要优先' }))
  await waitFor(() => expect(String(fetch.mock.calls.at(-1)![0])).toContain('sort=important'))
  expect(String(fetch.mock.calls.at(-1)![0])).toContain('range=24h')
})
test('loads server cursor and deduplicates cards across pages', async () => {
  const fetch = vi.fn().mockResolvedValueOnce(response([event], 'cursor-one')).mockResolvedValueOnce(response([event, { ...event, id: 2, title: '事件二' }]))
  stubFetch(fetch); mount()
  fireEvent.click(await screen.findByRole('button', { name: '加载更多' }))
  await screen.findByText('事件二')
  expect(screen.getAllByText('事件一')).toHaveLength(1)
  expect(String(fetch.mock.calls[1]![0])).toContain('cursor=cursor-one')
})
test('invalid URL filters recover without querying invalid values', async () => {
  const fetch = vi.fn().mockResolvedValue(response()); stubFetch(fetch); mount('/?sort=garbage&range=forever')
  await screen.findByText(/筛选参数无效/)
  await waitFor(() => expect(String(fetch.mock.calls[0]?.[0])).toContain('sort=newest'))
})
test('date-only reports stay dates without exposing system processing', () => {
  render(<EventCard event={{ ...event, earliest_reported_at: null, earliest_reported_date: '2026-10-13', earliest_reported_precision: 'date' }} />)
  expect(screen.getByText(/最早报道 2026-10-13.*仅日期/)).toBeTruthy()
  expect(screen.queryByText(/最早报道.*00:00/)).toBeNull()
  expect(screen.queryByText('系统处理时间')).toBeNull()
  expect(screen.queryByText(/系统处理于/)).toBeNull()
})
test('unknown reports show discovery separately without inventing report time', () => {
  render(<EventCard event={event} />)
  expect(screen.getByText(/报道时间未知/)).toBeTruthy()
})


test('returning to a filter resets cached pagination', async () => {
  const fetch = vi.fn((url: string) => Promise.resolve(response(url.includes('cursor=') ? [{ ...event, id: 2, title: '旧第二页' }] : [event], url.includes('cursor=') ? null : 'next')))
  stubFetch(fetch); mount()
  fireEvent.click(await screen.findByRole('button', { name: '加载更多' }))
  await screen.findByText('旧第二页')
  fireEvent.click(screen.getByRole('button', { name: '重要优先' }))
  await waitFor(() => expect(String(fetch.mock.calls.at(-1)![0])).toContain('sort=important'))
  fireEvent.click(screen.getByRole('button', { name: '最新事件' }))
  await waitFor(() => expect(screen.queryByText('旧第二页')).toBeNull())
  expect(String(fetch.mock.calls.at(-1)![0])).not.toContain('cursor=')
})
test('five-minute refresh discards later pages and only fetches first page', async () => {
  vi.useFakeTimers()
  const fetch = vi.fn((url: string) => Promise.resolve(response(url.includes('cursor=') ? [{ ...event, id: 2, title: '第二页' }] : [event], url.includes('cursor=') ? null : 'next')))
  stubFetch(fetch)
  mount()
  await act(async () => { await vi.advanceTimersByTimeAsync(10) })
  await act(async () => { await vi.advanceTimersByTimeAsync(10) })
  fireEvent.click(screen.getByRole('button', { name: '加载更多' }))
  await act(async () => { await vi.advanceTimersByTimeAsync(10) })
  expect(screen.getByText('第二页')).toBeTruthy()
  fetch.mockClear()
  await act(async () => { await vi.advanceTimersByTimeAsync(300000) })
  expect(fetch).toHaveBeenCalledTimes(1)
  expect(String(fetch.mock.calls[0]![0])).not.toContain('cursor=')
  expect(screen.queryByText('第二页')).toBeNull()
})
test('missing scores are not presented as zero importance', () => {
  render(<EventCard event={{ ...event, score_final: null }} />)
  expect(screen.queryByText('0')).toBeNull()
})

test('generation conflict disables stale pagination and retries from first page', async () => {
  const fetch = vi.fn().mockResolvedValueOnce(response([event], 'stale')).mockResolvedValueOnce({ ok: false, status: 409 }).mockResolvedValueOnce(response([{ ...event, id: 2, title: '刷新后的事件' }]))
  stubFetch(fetch); mount()
  fireEvent.click(await screen.findByRole('button', { name: '加载更多' }))
  await screen.findByText(/事件数据已变化/)
  expect((screen.getByRole('button', { name: '加载更多' }) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.click(screen.getByRole('button', { name: '重试' }))
  await screen.findByText('刷新后的事件')
  expect(String(fetch.mock.calls[2]![0])).not.toContain('cursor=')
  expect(screen.queryByText('事件一')).toBeNull()
})
test('changing filters aborts the previous request and ignores its late response', async () => {
  let resolveOld: (value: ReturnType<typeof response>) => void = () => { throw new Error('Missing deferred response') }
  const old = new Promise<ReturnType<typeof response>>((resolve) => { resolveOld = resolve })
  const fetch = vi.fn().mockReturnValueOnce(old).mockResolvedValueOnce(response([{ ...event, title: '新的筛选结果' }]))
  stubFetch(fetch); mount()
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
  const signal = (fetch.mock.calls[0]![1] as RequestInit).signal!
  fireEvent.click(screen.getByRole('button', { name: '重要优先' }))
  await screen.findByText('新的筛选结果')
  expect(signal.aborted).toBe(true)
  await act(async () => { resolveOld(response([event])) })
  expect(screen.queryByText('事件一')).toBeNull()
  expect(screen.getByText('新的筛选结果')).toBeTruthy()
})

test('waits for server preferences before the first feed query and URL never writes preferences', async () => {
  let resolvePreferences!: (value: unknown) => void
  const pending = new Promise((resolve) => { resolvePreferences = resolve })
  const fetch = vi.fn((url: string) => url === '/api/feed-preferences' ? pending : Promise.resolve(response([event])))
  vi.stubGlobal('fetch', fetch); mount('/?sort=hot&keep=yes')
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
  expect(screen.queryByText('事件一')).toBeNull()
  await act(async () => { resolvePreferences({ ok: true, json: async () => ({ sort: 'important', range: 'all', version: 3 }) }) })
  await screen.findByText('事件一')
  const url = String(fetch.mock.calls[1]![0])
  expect(url).toContain('sort=hot'); expect(url).toContain('range=all'); expect(url).not.toContain('unread_only')
  expect(fetch).toHaveBeenCalledTimes(2)
})
test('uses last successful local preferences only when server is unavailable', async () => {
  localStorage.setItem('unspun.feed-preferences.v2', JSON.stringify({ sort: 'important', range: '24h', version: 5 }))
  const fetch = vi.fn((url: string) => url === '/api/feed-preferences' ? Promise.reject(new Error('offline')) : Promise.resolve(response()))
  vi.stubGlobal('fetch', fetch); mount()
  await screen.findByText(/偏好同步失败/)
  await waitFor(() => expect(String(fetch.mock.calls[1]?.[0])).toContain('sort=important'))
  expect(String(fetch.mock.calls[1]![0])).toContain('range=24h')
})

test('preference conflicts refresh the version without replacing explicit URL choices', async () => {
  const fetch = vi.fn((url: string, options?: RequestInit) => {
    if (url === '/api/feed-preferences' && options?.method === 'PUT') return Promise.resolve({ ok: false, status: 409, json: async () => ({ detail: { current: { sort: 'hot', range: 'today', version: 8 } } }) })
    if (url === '/api/feed-preferences') return Promise.resolve({ ok: true, json: async () => ({ sort: 'newest', range: '7d', version: 0 }) })
    return Promise.resolve(response([event]))
  })
  vi.stubGlobal('fetch', fetch); mount('/?sort=newest&range=all&other=keep')
  await screen.findByText('事件一')
  fireEvent.click(screen.getByRole('button', { name: '重要优先' }))
  await screen.findByText(/偏好已在其他设备更新/)
  expect(screen.getByRole('button', { name: '重要优先' }).getAttribute('aria-pressed')).toBe('true')
  fireEvent.click(screen.getByRole('button', { name: '当前热度' }))
  await waitFor(() => expect(fetch.mock.calls.filter((call) => call[1]?.method === 'PUT')).toHaveLength(2))
  const lastWrite = fetch.mock.calls.filter((call) => call[1]?.method === 'PUT').at(-1)!
  expect(JSON.parse(lastWrite[1]!.body as string).version).toBe(8)
})


test('reading interactions retain events and stale unread URLs do not filter the feed', async () => {
  const fetch = vi.fn().mockResolvedValue(response([event])); stubFetch(fetch)
  mount('/?sort=newest&range=all&unread_only=true')
  await screen.findByText('事件一')
  expect(screen.queryByRole('checkbox', { name: '只看未读' })).toBeNull()
  expect(screen.queryByRole('button', { name: /标为已读|标为未读/ })).toBeNull()
  fireEvent.click(screen.getByText(/查看阅读规则/))
  expect(screen.getByText('事件一')).toBeTruthy()
  expect(fetch.mock.calls.every((call) => !String(call[0]).includes('unread_only'))).toBe(true)
  expect(fetch.mock.calls.every((call) => call[1]?.method !== 'PUT')).toBe(true)
})
test('offline disables preference writes without removing displayed events', async () => {
  const fetch = vi.fn().mockResolvedValue(response([event])); stubFetch(fetch); mount()
  await screen.findByText('事件一')
  act(() => window.dispatchEvent(new Event('offline')))
  expect((screen.getByRole('combobox', { name: '时间范围' }) as HTMLSelectElement).disabled).toBe(true)
  expect(screen.getByText('事件一')).toBeTruthy()
})

test('reading card does not repeat its title and opens per-fact provenance', () => {
  const evidenceUrl = 'https://example.org/evidence'
  const cited: EventOut = {
    ...event, title: '一条经过审核的事件', summary_zh: '一条经过审核的事件', content_kind: 'brief',
    facts: [{ text: '这条信息补充了标题之外的具体细节。', quote: 'The original evidence.', article_id: 9 }],
    evidence_article_ids: [9],
    articles: [{ id: 9, title: 'Original title', title_zh: null, source_name: '原始来源', source_id: 'source', url: evidenceUrl, published_at: null }],
  }
  render(<EventCard event={cited} />)
  expect(screen.getAllByText('一条经过审核的事件')).toHaveLength(1)
  expect(screen.getByText('快讯')).toBeTruthy()
  expect(screen.queryByText('The original evidence.')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '查看第 1 条信息依据' }))
  expect(screen.getByText('The original evidence.')).toBeTruthy()
  expect(screen.getByRole('link', { name: '原始来源 ↗' }).getAttribute('href')).toBe(evidenceUrl)
})
