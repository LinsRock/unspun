// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import OverviewPage from './OverviewPage'

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const range = { period: 'custom' as const, start: '2026-10-10T00:00:00.000Z', end: '2026-10-11T00:00:00.000Z' }
const overview = {
  range: { start: range.start, end: range.end, timezone: 'Asia/Shanghai', end_exclusive: true },
  as_of: range.end,
  period: { articles: 4, new_events: 2, runs: 1, fetch_errors: 1, sources: { configured_total: 2, enabled_total: 2, successful_sources: 1, productive_sources: 1, failed_sources: 1 }, cost: { total_confirmed_usd: null, calls: { count: 3, cost_usd: '0.125' }, fixed: { confirmed_usd: null, expected_usd: null, unconverted_currencies: ['CNY'] } } },
  current: { scope: 'current', consistency: 'live', source_health: { error: 1, no_runs: 0, ok: 1 }, backlog: { pending_summaries: 1, abandoned_summaries: 1, pending_embeddings: 0, pending_scores: 0 } },
  article_trend: [{ day: '2026-10-10', articles: 4 }], call_trend: [{ day: '2026-10-10', cost_usd: '0.125' }], purposes: [{ name: 'summary', cost_usd: '0.125' }],
  recent_run: { id: 7, run_at: range.start, summarized: 4, embedded: 2, clustered: 1, new_events: 2, scored: 1, status: null, ended_at: null, duration_seconds: null, missing_fields: ['status'] },
  exceptions: { source_error_total: 1, abandoned_summaries: 1, sources: [{ source_id: 'source-1', name: 'Source 1', last_error: 'timeout', last_error_at: range.start }] },
}

function renderPage(data = overview) {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => data }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/admin?period=custom&start=2026-10-10T00%3A00%3A00.000Z&end=2026-10-11T00%3A00%3A00.000Z']}><OverviewPage range={range} /></MemoryRouter></QueryClientProvider>)
}

test('shows real period metrics and preserves range in drilldowns', async () => {
  renderPage()
  expect(await screen.findByRole('link', { name: '新入库文章：4 篇' })).toBeTruthy()
  expect(screen.getByText('未换算')).toBeTruthy()
  expect(screen.getByText(/运行状态未记录/)).toBeTruthy()
  const articleLink = screen.getByRole('link', { name: /新入库文章/ })
  expect(articleLink.getAttribute('href')).toContain('period=custom')
  expect(articleLink.getAttribute('href')).toContain('tab=articles')
  expect(screen.getByRole('link', { name: /Source 1/ }).getAttribute('href')).toContain('source_detail=source-1')
})

test('shows a retry control when the overview request fails', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter><OverviewPage range={range} /></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByRole('alert')).toBeTruthy()
  expect(screen.getByRole('button', { name: /重\s*试/ })).toBeTruthy()
})

test('opens a day detail without changing the selected global range', async () => {
  const fetchMock = vi.fn().mockImplementation(async (url: string) => ({
    ok: true,
    json: async () => url.includes('/articles?')
      ? { total: 1, page: 1, page_size: 25, items: [{ id: 12, title: 'Article', source_id: 'source-1', fetched_at: '2026-10-10T04:00:00Z' }] }
      : overview,
  }))
  vi.stubGlobal('fetch', fetchMock)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter><OverviewPage range={range} /></MemoryRouter></QueryClientProvider>)
  fireEvent.click(await screen.findByRole('button', { name: '查看 2026-10-10 文章明细' }))
  expect(await screen.findByText('Article')).toBeTruthy()
  const requestedUrl = fetchMock.mock.calls.map(call => String(call[0])).find(url => url.includes('/articles?'))
  expect(requestedUrl).toContain('start=2026-10-10T00%3A00%3A00.000Z')
  expect(requestedUrl).toContain('end=2026-10-10T16%3A00%3A00.000Z')
  expect(screen.getByRole('link', { name: '新入库文章：4 篇' }).getAttribute('href')).toContain('end=2026-10-11T00%3A00%3A00.000Z')
})
