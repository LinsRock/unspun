// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'

import App from '../App'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

test('article detail drills into its event without losing the range', async () => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
  const requests: string[] = []
  const article = { id: 1, source_id: 'bbc-world', source_name: 'BBC World', url: 'https://example.com/a', title: 'Original headline', title_zh: '报道标题', lang: 'en', published_at: null, fetched_at: '2026-10-01T08:00:00Z', summary_status: 'summarized', embedding_status: 'embedded', cluster_status: 'clustered', processing_status: 'clustered', quality_status: 'grounded', event_id: 2 }
  const event = { id: 2, title: '事件标题', first_seen_at: '2026-10-01T08:00:00Z', changed_at: '2026-10-01T08:00:00Z', earliest_published_at: null, latest_published_at: null, article_count: 1, source_count: 1, score_final: 72, scored_at: '2026-10-01T09:00:00Z', processing_status: 'scored' }
  vi.stubGlobal('fetch', vi.fn((input: string) => {
    requests.push(input)
    const base = { range: { start: '2026-10-01T00:00:00Z', end: '2026-10-02T00:00:00Z', timezone: 'Asia/Shanghai', end_exclusive: true }, as_of: '2026-10-12T08:00:00Z', page: 1, page_size: 25, total: 1 }
    let data: unknown = base
    if (input.includes('/api/admin/articles/1')) data = { ...article, content: 'Full text', summary_zh: '摘要', summary_grounding: null, summary_failures: 0, event: { id: 2, title: '事件标题' } }
    else if (input.includes('/api/admin/events/2')) data = { ...event, summary_zh: '事件摘要', score_breakdown: null, articles: [article], viewpoint: null }
    else if (input.includes('/api/admin/articles?')) data = { ...base, items: [article] }
    else if (input.includes('/api/admin/events?')) data = { ...base, items: [event] }
    return Promise.resolve({ ok: true, json: () => Promise.resolve(data) })
  }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/admin/content?period=custom&start=2026-10-01T00%3A00%3A00Z&end=2026-10-02T00%3A00%3A00Z&processing_status=clustered']}><App /></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByText('报道标题', {}, { timeout: 5000 })).toBeTruthy()
  expect(screen.getByText('未记录')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '查看文章 1 详情' }))
  expect(await screen.findByText('Full text')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '查看关联事件 2' }))
  expect((await screen.findAllByText('事件摘要')).length).toBeGreaterThan(1)
  expect(requests.some(url => url.includes('/api/admin/events/2') && url.includes('start=2026-10-01'))).toBe(true)
  expect(requests.some(url => url.includes('/api/admin/events?') && !url.includes('processing_status=clustered'))).toBe(true)
}, 10_000)

test('missing-report-time mode is explicit and sent to the event query', async () => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
  const requests: string[] = []
  vi.stubGlobal('fetch', vi.fn((input: string) => {
    requests.push(input)
    return Promise.resolve({ ok: true, json: () => Promise.resolve(input.includes('/events?') ? { range: { start: '2026-10-01T00:00:00Z', end: '2026-10-02T00:00:00Z', timezone: 'Asia/Shanghai', end_exclusive: true }, as_of: '2026-10-12T08:00:00Z', page: 1, page_size: 25, total: 0, items: [] } : { range: { start: '2026-10-01T00:00:00Z', end: '2026-10-02T00:00:00Z', timezone: 'Asia/Shanghai', end_exclusive: true }, as_of: '2026-10-12T08:00:00Z', page: 1, page_size: 25, sort: 'newest' }) })
  }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/admin/content?period=custom&start=2026-10-01T00%3A00%3A00Z&end=2026-10-02T00%3A00%3A00Z&tab=events&time_status=missing']}><App /></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByText(/发现时间筛选/)).toBeTruthy()
  expect(requests.some(url => url.includes('/api/admin/events?') && url.includes('time_status=missing'))).toBe(true)
}, 10_000)
