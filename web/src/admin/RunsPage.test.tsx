// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'

import App from '../App'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function renderPage(path: string, failed = false) {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
  vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
    const url = String(input)
    if (failed && url.includes('/api/admin/runs?')) return Promise.resolve({ ok: false, status: 503 })
    const payload = url.includes('/api/admin/range') ? {
      range: { start: '2026-10-12T00:00:00Z', end: '2026-10-12T08:00:00Z', timezone: 'Asia/Shanghai', end_exclusive: true },
      as_of: '2026-10-12T08:00:00Z', page: 1, page_size: 25, sort: 'newest',
    } : url.includes('/api/admin/configuration') ? {
      sources: [], pipeline: { fetch_interval_minutes: 30, summary_batch_limit: 50, embed_batch_limit: 200, score_batch_limit: 40, max_summary_failures: 3, digest_hour: 8, digest_timezone: 'Asia/Shanghai', grounding_budget_24h_usd: 0.4, summary_model: 'model-a', importance_model: 'model-b', viewpoint_model: 'model-b', digest_model: 'model-a', embedding_model: 'model-c' },
      credentials: { openrouter_configured: true }, audit: { status: 'not_recorded', message: 'Historical audit was not recorded' },
    } : url.includes('/api/admin/backlog') ? {
      scope: 'current', consistency: 'live', counts: { pending_summaries: 2, abandoned_summaries: 1, pending_embeddings: 3, pending_scores: 4 }, stage: 'pending_summary', total: 1, page: 1, page_size: 20, items: [{ id: 42, title: '待处理文章', source_id: 'a3', stage: 'pending_summary', failures: 0 }],
    } : url.endsWith('/api/admin/runs/17') ? { id: 17, run_at: '2026-10-12T03:00:00Z', summarized: 4, embedded: 3, clustered: 2, new_events: 1, scored: 5, status: null, ended_at: null, duration_seconds: null, cost_usd: null, stage_results: null, missing_fields: ['status'] } : { range: { start: '2026-10-12T00:00:00Z', end: '2026-10-12T08:00:00Z' }, as_of: '2026-10-12T08:00:00Z', total: 1, page: 1, page_size: 20, items: [{ id: 17, run_at: '2026-10-12T03:00:00Z', summarized: 4, embedded: 3, clustered: 2, new_events: 1, scored: 5, status: null, ended_at: null, duration_seconds: null, cost_usd: null, stage_results: null, missing_fields: ['status'] }] }
    return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) })
  }))
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>)
}

test('runs show recorded counts and missing historical status', async () => {
  renderPage('/admin/runs')
  expect(await screen.findByText('17', {}, { timeout: 5000 })).toBeTruthy()
  expect(screen.getAllByText('未记录').length).toBeGreaterThan(0)
  fireEvent.click(screen.getByRole('button', { name: /详\s*情/ }))
  expect(await screen.findByText(/历史阶段状态/)).toBeTruthy()
})

test('runs distinguish request failure from an empty list', async () => {
  renderPage('/admin/runs', true)
  expect(await screen.findByText(/运行记录加载失败/)).toBeTruthy()
})

test('configuration shows credentials state and absent audit', async () => {
  renderPage('/admin/configuration')
  expect(await screen.findByText('已配置')).toBeTruthy()
  fireEvent.click(screen.getByText('变更与操作记录'))
  expect(await screen.findByText(/历史操作记录未记录/)).toBeTruthy()
})

test('backlog links to the available A2 article detail', async () => {
  renderPage('/admin/runs?period=custom&start=2026-10-01T00%3A00%3A00Z&end=2026-10-02T00%3A00%3A00Z&tab=backlog')
  const link = await screen.findByRole('link', { name: '查看文章 #42' }, { timeout: 5000 })
  expect(link.getAttribute('href')).toContain('/admin/content?')
  expect(link.getAttribute('href')).toContain('article_detail=42')
  expect(link.getAttribute('href')).toContain('period=custom')
})
