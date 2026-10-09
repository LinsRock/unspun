// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { expect, test, vi } from 'vitest'

import type { EventsResponse } from './api'
import App from './App'

const sample: EventsResponse = {
  events: [
    {
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
      articles: [
        {
          id: 11,
          title: 'original title',
          title_zh: '中文标题',
          url: 'https://example.com/a',
          source_id: 'bbc-world',
          source_name: 'BBC World',
          published_at: null,
        },
      ],
    },
  ],
}

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  )
}

test('renders event cards from the API', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(sample) }),
  )
  renderApp()
  await waitFor(() => {
    expect(screen.getByText('某重大事件')).toBeTruthy()
  })
  expect(screen.getByText('这是事件摘要。')).toBeTruthy()
  expect(screen.getByText(/评分理由/).textContent).toContain('多国央行同步行动。')
  const link = screen.getByRole('link', { name: /BBC World/ })
  expect(link.getAttribute('href')).toBe('https://example.com/a')
  expect(screen.getByRole('button', { name: '73' })).toBeTruthy()
})

test('shows the empty state when there are no events', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({ events: [] }) }),
  )
  renderApp()
  await waitFor(() => {
    expect(screen.getByText(/暂无事件/)).toBeTruthy()
  })
})
