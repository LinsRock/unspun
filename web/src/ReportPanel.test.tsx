// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import type { ReportResponse } from './api'
import ReportPanel from './ReportPanel'

const sample: ReportResponse = {
  window_hours: 24,
  generated_at: '2026-10-09T10:00:00Z',
  fetch_runs: 48,
  new_articles: 120,
  source_failures: [],
  llm_spend: [],
  llm_cost_total_usd: 0.42,
  backlog: {
    pending_summaries: 37,
    pending_embeddings: 12,
    pending_scores: 5,
    abandoned_total: 3,
    abandoned_articles: [{ id: 6, title: 'broken article', source_id: 'bbc-world' }],
  },
  last_run: {
    run_at: '2026-10-09T09:30:00Z',
    summarized: 50,
    embedded: 48,
    clustered: 40,
    new_events: 7,
    scored: 9,
  },
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ReportPanel />
    </QueryClientProvider>,
  )
}

test('renders backlog metrics, abandoned articles, and last run', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(sample) }),
  )
  renderPanel()
  await waitFor(() => {
    expect(screen.getByText('管线积压')).toBeTruthy()
  })
  const backlog = screen.getByText(/待摘要 37 篇/)
  expect(backlog.textContent).toContain('待 embedding 12 篇')
  expect(backlog.textContent).toContain('待评分事件 5 个')
  expect(screen.getByText(/已放弃的文章（摘要连续失败，共 3 篇）/)).toBeTruthy()
  expect(screen.getByText(/#6 · bbc-world · broken article/)).toBeTruthy()
  expect(screen.getByText(/仅显示最新 1 篇/)).toBeTruthy()
  const lastRun = screen.getByText(/摘要 50/)
  expect(lastRun.textContent).toContain('embedding 48')
  expect(lastRun.textContent).toContain('聚类 40')
  expect(lastRun.textContent).toContain('新事件 7')
  expect(lastRun.textContent).toContain('评分 9')
})

test('tolerates an older API response without the new fields', async () => {
  const legacy = { ...sample, backlog: undefined, last_run: undefined } as unknown as ReportResponse
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(legacy) }),
  )
  renderPanel()
  await waitFor(() => {
    expect(screen.getByText('抓取轮次')).toBeTruthy()
  })
  expect(screen.getByText('48')).toBeTruthy()
  expect(screen.queryByText('管线积压')).toBeNull()
})

test('renders source failures and LLM spend as tables', async () => {
  const busy: ReportResponse = {
    ...sample,
    source_failures: [{ source_id: 'wsj-markets', failures: 6, last_error: 'HTTP 401' }],
    llm_spend: [
      {
        purpose: 'summary',
        model: 'flash-lite',
        calls: 212,
        prompt_tokens: 1000,
        completion_tokens: 500,
        cost_usd: 0.19,
      },
    ],
  }
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(busy) }),
  )
  renderPanel()
  await waitFor(() => {
    expect(screen.getByText('wsj-markets')).toBeTruthy()
  })
  expect(screen.getByText('6 次')).toBeTruthy()
  expect(screen.getByText('HTTP 401')).toBeTruthy()
  expect(screen.queryByText(/所有源抓取正常/)).toBeNull()
  expect(screen.getByText('flash-lite')).toBeTruthy()
  expect(screen.getByText('1,500')).toBeTruthy()
  expect(screen.getByText('$0.1900')).toBeTruthy()
})

test('shows a hint when the AI stages have never run', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ ...sample, last_run: null }),
    }),
  )
  renderPanel()
  await waitFor(() => {
    expect(screen.getByText('AI 阶段尚未运行过')).toBeTruthy()
  })
})
