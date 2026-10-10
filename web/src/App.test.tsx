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
  articles: [
    article(11, {
      title: 'original title',
      title_zh: '中文标题',
      url: 'https://example.com/a',
    }),
  ],
  viewpoint: null,
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

const viewpointEvent: EventOut = {
  ...baseEvent,
  articles: [
    article(31, { source_name: '财新', title_zh: '财新报道', url: 'https://caixin.example/31' }),
    article(32, { source_name: 'Reuters', title_zh: '路透报道', url: 'https://reuters.example/32' }),
    article(33, { source_name: 'BBC', title_zh: 'BBC 报道', url: 'https://bbc.example/33' }),
  ],
  viewpoint: {
    claims: [
      { article_id: 31, claim: '财新的说法' },
      { article_id: 32, claim: '路透的说法' },
      { article_id: 33, claim: 'BBC 的说法' },
    ],
    disagreements: [{ point: '双方对关税定性分歧', claim_indexes: [0, 1] }],
    model: 'google/gemini-2.5-flash',
    generated_at: '2026-10-10T00:00:00Z',
  },
}

test('viewpoint bar expands claims, each linked to its own article', async () => {
  stubEvents({ events: [viewpointEvent] })
  renderApp()
  await screen.findByText('某重大事件')
  expect(screen.queryByText('财新的说法')).toBeNull()
  const bar = screen.getByRole('button', { name: /观点对比 · 3 源说法/ })
  fireEvent.click(bar)
  // Every claim sits next to the link of exactly its own article.
  const cases: Array<[string, string, string]> = [
    ['财新的说法', 'https://caixin.example/31', '财新报道'],
    ['路透的说法', 'https://reuters.example/32', '路透报道'],
    ['BBC 的说法', 'https://bbc.example/33', 'BBC 报道'],
  ]
  for (const [claim, href, linkTitle] of cases) {
    const column = screen.getByText(claim).closest('div')
    const link = column?.querySelector('a')
    expect(link?.getAttribute('href')).toBe(href)
    expect(link?.textContent).toContain(linkTitle)
  }
  expect(screen.getByText('双方对关税定性分歧')).toBeTruthy()
  expect(screen.getByText('财新 · Reuters')).toBeTruthy()
  fireEvent.click(bar)
  expect(screen.queryByText('财新的说法')).toBeNull()
})

test('claims pointing at foreign articles are dropped', async () => {
  const vp = viewpointEvent.viewpoint
  if (!vp) throw new Error('fixture must carry a viewpoint')
  stubEvents({
    events: [
      {
        ...viewpointEvent,
        viewpoint: {
          ...vp,
          claims: [...vp.claims, { article_id: 999, claim: '张冠李戴的说法' }],
        },
      },
    ],
  })
  renderApp()
  await screen.findByText('某重大事件')
  fireEvent.click(screen.getByRole('button', { name: /观点对比 · 3 源说法/ }))
  expect(screen.queryByText('张冠李戴的说法')).toBeNull()
})

test('viewpoint claim links reject non-http urls', async () => {
  const vp = viewpointEvent.viewpoint
  if (!vp) throw new Error('fixture must carry a viewpoint')
  stubEvents({
    events: [
      {
        ...viewpointEvent,
        articles: [
          ...viewpointEvent.articles.slice(1),
          // eslint-disable-next-line no-script-url
          article(31, { source_name: '财新', title_zh: '财新报道', url: 'javascript:alert(1)' }),
        ],
      },
    ],
  })
  renderApp()
  await screen.findByText('某重大事件')
  fireEvent.click(screen.getByRole('button', { name: /观点对比 · 3 源说法/ }))
  // No anchor at all: an href-less <a> would look clickable but go nowhere.
  const column = screen.getByText('财新的说法').closest('div')
  expect(column?.querySelector('a')).toBeNull()
  expect(column?.textContent).toContain('财新报道')
})

test('events without a viewpoint show no comparison bar', async () => {
  stubEvents(sample)
  renderApp()
  await screen.findByText('某重大事件')
  expect(screen.queryByRole('button', { name: /观点对比/ })).toBeNull()
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
