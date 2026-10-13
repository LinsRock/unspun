// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'

import App from '../App'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

test('source history shows real outcomes and keeps range when drilling into articles', async () => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
  const requests: string[] = []
  vi.stubGlobal('fetch', vi.fn((input: string) => {
    requests.push(input)
    const data = input.includes('/api/admin/sources?') ? {
      range: { start: '2026-10-01T00:00:00Z', end: '2026-10-02T00:00:00Z', timezone: 'Asia/Shanghai', end_exclusive: true },
      as_of: '2026-10-12T08:00:00Z', page: 1, page_size: 25, total: 2,
      items: [
        { id: 'bbc-world', name: 'BBC World', lang: 'en', region: 'eu', kind: 'public', configured: true, enabled: true, health: 'ok', period_latest_status: 'ok', new_articles: 0, successful_fetches: 1, failed_fetches: 0, success_rate: 1, last_success_at: '2026-10-01T08:00:00Z', last_error_at: null, last_error: null },
        { id: 'retired', name: null, lang: null, region: null, kind: null, configured: false, enabled: false, health: 'error', new_articles: 0, successful_fetches: 0, failed_fetches: 1, success_rate: 0, last_success_at: null, last_error_at: '2026-10-01T09:00:00Z', last_error: 'timeout' },
      ],
    } : { range: { start: '2026-10-01T00:00:00Z', end: '2026-10-02T00:00:00Z', timezone: 'Asia/Shanghai', end_exclusive: true }, as_of: '2026-10-12T08:00:00Z', page: 1, page_size: 25, sort: 'newest' }
    return Promise.resolve({ ok: true, json: () => Promise.resolve(data) })
  }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/admin/sources?period=custom&start=2026-10-01T00%3A00%3A00Z&end=2026-10-02T00%3A00%3A00Z']}><App /></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByText('BBC World', {}, { timeout: 5000 })).toBeTruthy()
  expect(screen.getByText('retired')).toBeTruthy()
  expect(screen.getByText('成功但无新文章')).toBeTruthy()
  expect(screen.getByRole('columnheader', { name: '当前抓取状态' })).toBeTruthy()
  fireEvent.mouseDown(screen.getByRole('combobox', { name: '来源语言' }))
  fireEvent.click(await screen.findByText('英文'))
  expect(await screen.findByText('BBC World')).toBeTruthy()
  expect(requests.some(url => url.includes('/api/admin/sources?') && url.includes('lang=en'))).toBe(true)
  fireEvent.click(screen.getByRole('link', { name: /查看 BBC World 的文章/ }))
  expect(await screen.findByRole('heading', { name: '文章与事件' })).toBeTruthy()
  expect(requests.some(url => url.includes('/api/admin/sources?') && url.includes('start=2026-10-01'))).toBe(true)
}, 10_000)
