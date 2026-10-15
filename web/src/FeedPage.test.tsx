// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import FeedPage from './FeedPage'
import EventCard from './EventCard'
import type { EventOut } from './api'

const event: EventOut = { id: 1, title: '事件一', summary_zh: null, score_final: 60, score_decayed: null, score_breakdown: null, first_seen_at: '2026-10-14T00:00:00Z', changed_at: '2026-10-14T03:00:00Z', articles: [], viewpoint: null }
afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals() })
function mount(path = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><FeedPage /></MemoryRouter></QueryClientProvider>)
}
function response(events: EventOut[] = [], next_cursor: string | null = null) {
  return { ok: true, json: async () => ({ events, next_cursor, as_of: '2026-10-14T05:00:00Z', window_start: '2026-10-07T05:00:00Z', window_end: '2026-10-14T05:00:00Z' }) }
}
test('defaults to latest seven days and keeps range while changing sort', async () => {
  const fetch = vi.fn().mockResolvedValue(response()); vi.stubGlobal('fetch', fetch)
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
  vi.stubGlobal('fetch', fetch); mount()
  fireEvent.click(await screen.findByRole('button', { name: '加载更多' }))
  await screen.findByText('事件二')
  expect(screen.getAllByText('事件一')).toHaveLength(1)
  expect(String(fetch.mock.calls[1]![0])).toContain('cursor=cursor-one')
})
test('invalid URL filters recover without querying invalid values', async () => {
  const fetch = vi.fn().mockResolvedValue(response()); vi.stubGlobal('fetch', fetch); mount('/?sort=garbage&range=forever')
  await screen.findByText(/筛选参数无效/)
  expect(String(fetch.mock.calls[0]![0])).toContain('sort=newest')
})
test('date-only reports stay dates and system processing is labelled separately', () => {
  render(<EventCard event={{ ...event, earliest_reported_at: null, earliest_reported_date: '2026-10-13', earliest_reported_precision: 'date' }} />)
  expect(screen.getByText(/最早报道 2026-10-13.*仅日期/)).toBeTruthy()
  expect(screen.queryByText(/最早报道.*00:00/)).toBeNull()
  fireEvent.click(screen.getByText('系统处理时间'))
  expect(screen.getByText(/系统处理于/)).toBeTruthy()
})
test('unknown reports show discovery separately without inventing report time', () => {
  render(<EventCard event={event} />)
  expect(screen.getByText(/报道时间未知.*首次发现/)).toBeTruthy()
})


test('returning to a filter resets cached pagination', async () => {
  const fetch = vi.fn((url: string) => Promise.resolve(response(url.includes('cursor=') ? [{ ...event, id: 2, title: '旧第二页' }] : [event], url.includes('cursor=') ? null : 'next')))
  vi.stubGlobal('fetch', fetch); mount()
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
  vi.stubGlobal('fetch', fetch)
  mount()
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
test('missing scores have an explicit label', () => {
  render(<EventCard event={{ ...event, score_final: null }} />)
  expect(screen.getByText('尚未评分')).toBeTruthy()
})

test('generation conflict disables stale pagination and retries from first page', async () => {
  const fetch = vi.fn().mockResolvedValueOnce(response([event], 'stale')).mockResolvedValueOnce({ ok: false, status: 409 }).mockResolvedValueOnce(response([{ ...event, id: 2, title: '刷新后的事件' }]))
  vi.stubGlobal('fetch', fetch); mount()
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
  vi.stubGlobal('fetch', fetch); mount()
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1))
  const signal = (fetch.mock.calls[0]![1] as RequestInit).signal!
  fireEvent.click(screen.getByRole('button', { name: '重要优先' }))
  await screen.findByText('新的筛选结果')
  expect(signal.aborted).toBe(true)
  await act(async () => { resolveOld(response([event])) })
  expect(screen.queryByText('事件一')).toBeNull()
  expect(screen.getByText('新的筛选结果')).toBeTruthy()
})
