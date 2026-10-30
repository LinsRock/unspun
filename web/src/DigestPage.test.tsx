// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'

import type { DigestResponse, EventOut } from './api'
import App from './App'

const SOURCE_URL = 'https://example.com/one'
const SECOND_URL = 'https://example.com/two'
const event: EventOut = {
  id: 1,
  title: '排名首位事件',
  summary_zh: '快照摘要',
  score_final: 90,
  score_decayed: 80,
  score_breakdown: null,
  first_seen_at: '2026-10-09T00:00:00Z',
  changed_at: '2026-10-10T00:00:00Z',
  articles: [
    {
      id: 1,
      title: '原文一',
      title_zh: null,
      url: SOURCE_URL,
      source_id: 'a',
      source_name: '来源甲',
      published_at: null,
    },
    {
      id: 2,
      title: '原文二',
      title_zh: null,
      url: SECOND_URL,
      source_id: 'b',
      source_name: '来源乙',
      published_at: null,
    },
  ],
  viewpoint: {
    model: 'm',
    generated_at: '2026-10-10T00:00:00Z',
    claims: [
      { article_id: 1, claim: '甲的观点' },
      { article_id: 2, claim: '乙的观点' },
      { article_id: 999, claim: '无来源观点' },
    ],
    disagreements: [{ point: '影响判断存在分歧', claim_indexes: [0, 1] }],
  },
}
const digest: DigestResponse = {
  report_date: '2026-10-10',
  kind: 'daily',
  generated_at: '2026-10-10T00:00:00Z',
  payload: {
    intro: '日报导语',
    timezone: 'Asia/Shanghai',
    window_start: '2026-10-09T00:00:00Z',
    window_end: '2026-10-10T00:00:00Z',
    events: [event],
  },
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function renderDigest(path = '/digest?date=2026-10-10') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

test('renders the ranked snapshot and traceable viewpoint excerpts', async () => {
  const fetch = vi
    .fn()
    .mockResolvedValue({ ok: true, json: () => Promise.resolve(digest) })
  vi.stubGlobal('fetch', fetch)
  renderDigest()
  await screen.findByText('日报导语')
  expect(fetch).toHaveBeenCalledWith('/api/digest/2026-10-10')
  expect(screen.getByText('快照摘要')).toBeTruthy()
  expect(screen.getByText('80')).toBeTruthy()
  expect(screen.getByText('01')).toBeTruthy()
  const item = within(screen.getByRole('article'))
  expect(
    item.getByRole('link', { name: /来源甲.*甲的观点/ }).getAttribute('href'),
  ).toBe(SOURCE_URL)
  expect(
    item.getByRole('link', { name: /来源乙.*乙的观点/ }).getAttribute('href'),
  ).toBe(SECOND_URL)
  expect(screen.queryByText('无来源观点')).toBeNull()
  expect(screen.getByText(/影响判断存在分歧/)).toBeTruthy()
})

test('date navigation requests a historical digest and latest is explicit', async () => {
  const fetch = vi
    .fn()
    .mockImplementation((url: string) =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            ...digest,
            report_date: url.endsWith('09') ? '2026-10-09' : '2026-10-10',
          }),
      }),
    )
  vi.stubGlobal('fetch', fetch)
  renderDigest()
  await screen.findByText('日报导语')
  fireEvent.click(screen.getByRole('button', { name: '前一天' }))
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith('/api/digest/2026-10-09'),
  )
  fireEvent.click(screen.getByRole('button', { name: '最新一期' }))
  await waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/digest/latest'))
})

test('missing digest and an empty generated digest have distinct states', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404 }))
  const view = renderDigest()
  await screen.findByText(/这一天没有已保存的日报/)
  view.unmount()
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValue({
        ok: true,
        json: () =>
          Promise.resolve({
            ...digest,
            payload: { ...digest.payload, events: [] },
          }),
      }),
  )
  renderDigest()
  await screen.findByText(/过去 24 小时暂无入选事件/)
})

test('invalid calendar date does not request a digest', () => {
  const fetch = vi.fn()
  vi.stubGlobal('fetch', fetch)
  renderDigest('/digest?date=2026-02-30')
  expect(screen.getByText(/日期无效/)).toBeTruthy()
  expect(fetch.mock.calls.every(call => !String(call[0]).startsWith('/api/digest'))).toBe(true)
})

test('network error offers a retry and recovers', async () => {
  const fetch = vi
    .fn()
    .mockRejectedValueOnce(new Error('offline'))
    .mockResolvedValue({ ok: true, json: () => Promise.resolve(digest) })
  vi.stubGlobal('fetch', fetch)
  renderDigest()
  await screen.findByText(/日报加载失败/)
  fireEvent.click(screen.getByRole('button', { name: '重试' }))
  await screen.findByText('日报导语')
})

test('viewpoint links reject unsafe URLs', async () => {
  const unsafe = {
    ...event,
    articles: [
      { ...event.articles[0]!, url: 'javascript:alert(1)' },
      event.articles[1]!,
    ],
  }
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValue({
        ok: true,
        json: () =>
          Promise.resolve({
            ...digest,
            payload: { ...digest.payload, events: [unsafe] },
          }),
      }),
  )
  renderDigest()
  await screen.findByText('日报导语')
  expect(screen.getByText('甲的观点').closest('a')).toBeNull()
  expect(document.querySelector('a[href^="javascript:"]')).toBeNull()
})


test('historical digest defaults to latest saved snapshot without a daily promise', async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(digest) })
  vi.stubGlobal('fetch', fetch)
  renderDigest('/digest')
  await screen.findByText('日报导语')
  expect(fetch).toHaveBeenCalledWith('/api/digest/latest')
  expect(screen.getByRole('heading', { name: '历史日报' })).toBeTruthy()
  expect(screen.queryByRole('button', { name: '今天' })).toBeNull()
})
