// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import type { ArticleOut, EventOut, EventsResponse } from './api'
import App from './App'

function article(id: number, overrides: Partial<ArticleOut> = {}): ArticleOut {
  return {
    id,
    title: `original title ${id}`,
    title_zh: `中文标题 ${id}`,
    url: `https://example.com/${id}`,
    source_id: 'bbc-world',
    source_name: 'BBC World',
    published_at: null,
    ...overrides,
  }
}

const baseEvent: EventOut = {
  id: 1,
  title: '某重大事件',
  summary_zh: '这是事件摘要。',
  score_final: 72.5,
  score_decayed: 70.1,
  score_breakdown: {
    objective: { score: 60, breadth: 60, growth: 40, source_quality: 90, community: 0 },
    importance: {
      score: 76,
      scope: 4,
      durability: 3,
      novelty: 4,
      domain_importance: 4,
      reason: '多国央行同步行动。',
      confidence: 'medium',
    },
  },
  first_seen_at: '2026-10-09T00:00:00Z',
  changed_at: '2026-10-09T01:00:00Z',
  articles: [article(11, { title: 'original title', title_zh: '中文标题', url: 'https://example.com/a' })],
}

const sample: EventsResponse = { events: [baseEvent] }

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  delete document.documentElement.dataset.theme
  localStorage.clear()
})

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  )
}

function stubEvents(response: EventsResponse) {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(response) }),
  )
}

test('renders event cards from the API', async () => {
  stubEvents(sample)
  renderApp()
  await waitFor(() => {
    expect(screen.getByText('某重大事件')).toBeTruthy()
  })
  expect(screen.getByText('这是事件摘要。')).toBeTruthy()
  const link = screen.getByRole('link', { name: /BBC World/ })
  expect(link.getAttribute('href')).toBe('https://example.com/a')
  expect(screen.getByText(/1 源 · 更新于/)).toBeTruthy()
})

test('score badge toggles the breakdown with the scoring reason', async () => {
  stubEvents(sample)
  renderApp()
  const badge = await screen.findByRole('button', { name: '73' })
  expect(screen.queryByText(/多国央行同步行动/)).toBeNull()
  fireEvent.click(badge)
  expect(screen.getByText('评分理由')).toBeTruthy()
  expect(screen.getByText(/多国央行同步行动/)).toBeTruthy()
  expect(screen.getByText('重要性')).toBeTruthy()
  expect(screen.getByText('报道广度')).toBeTruthy()
  fireEvent.click(badge)
  expect(screen.queryByText(/多国央行同步行动/)).toBeNull()
})

test('collapses sources beyond two behind the more bar', async () => {
  const multi: EventsResponse = {
    events: [{ ...baseEvent, articles: [article(21), article(22), article(23), article(24)] }],
  }
  stubEvents(multi)
  renderApp()
  await screen.findByText('某重大事件')
  expect(screen.getAllByRole('link')).toHaveLength(2)
  const more = screen.getByRole('button', { name: /另有 2 篇来源报道/ })
  fireEvent.click(more)
  expect(screen.getAllByRole('link')).toHaveLength(4)
  expect(screen.queryByRole('button', { name: /另有 2 篇来源报道/ })).toBeNull()
})

test('shows the empty state when there are no events', async () => {
  stubEvents({ events: [] })
  renderApp()
  await waitFor(() => {
    expect(screen.getByText(/暂无事件/)).toBeTruthy()
  })
})

test('theme toggle applies and persists the choice', async () => {
  stubEvents({ events: [] })
  renderApp()
  fireEvent.click(screen.getByRole('button', { name: '暗色' }))
  expect(document.documentElement.dataset.theme).toBe('dark')
  expect(localStorage.getItem('unspun-theme')).toBe('dark')
  fireEvent.click(screen.getByRole('button', { name: '跟随系统' }))
  expect(document.documentElement.dataset.theme).toBeUndefined()
})
