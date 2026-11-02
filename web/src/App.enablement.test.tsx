// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { onlineManager, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import App from './App'

vi.mock('./reader/HybridPage', () => ({ default: () => <h1>跟上变化，发现好内容</h1> }))
vi.mock('./reader/ReadingPage', () => ({ default: () => <h1>独立阅读</h1> }))
vi.mock('./reader/ContentPage', () => ({ default: () => <h1>独立内容详情</h1> }))

function Location() {
  const location = useLocation()
  return <output aria-label="当前位置">{location.pathname + location.search + location.hash}</output>
}
function setup(path: string, home: 'reading' | 'discover' = 'discover', hybrid = true) {
  const fetch = vi.fn(async (_url: string, _options?: RequestInit) => Response.json({ home, hybrid, topic_preferences: false, engineering_preview: false }))
  vi.stubGlobal('fetch', fetch)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><App /><Location /></MemoryRouter></QueryClientProvider>)
  return fetch
}
afterEach(() => { cleanup(); onlineManager.setOnline(true); vi.unstubAllGlobals() })

it('opens the accepted discovery page using formal capabilities', async () => {
  setup('/')
  await screen.findByRole('heading', { name: '跟上变化，发现好内容' })
  expect(screen.getByLabelText('当前位置').textContent).toBe('/discover')
  expect(screen.queryByRole('link', { name: '历史阅读' })).toBeNull()
})

it.each([
  '/?sort=hot&range=all#saved', '/?unread_only=true',
  '/history', '/events?sort=important&range=all', '/digest?date=2026-10-18',
])('retires %s without requesting historical content', async path => {
  const fetch = setup(path)
  await screen.findByRole('heading', { name: '跟上变化，发现好内容' })
  expect(screen.getByLabelText('当前位置').textContent).toBe('/discover')
  expect(fetch.mock.calls.every(call => !/\/api\/(events|digest|feed-preferences)/.test(String(call[0])))).toBe(true)
})

it.each([true, false])('falls back to current independent reading with hybrid=%s', async hybrid => {
  setup('/', 'reading', hybrid)
  await screen.findByRole('heading', { name: '独立阅读' })
  expect(screen.getByLabelText('当前位置').textContent).toBe('/reading')
})

it('keeps current content details directly accessible', async () => {
  setup('/reading/9192')
  await screen.findByRole('heading', { name: '独立内容详情' })
  expect(screen.getByLabelText('当前位置').textContent).toBe('/reading/9192')
})

it('opens the current reading shell on an offline cold start', async () => {
  onlineManager.setOnline(false)
  const fetch = setup('/digest?date=latest')
  await screen.findByRole('heading', { name: '独立阅读' })
  expect(screen.getByLabelText('当前位置').textContent).toBe('/reading')
  expect(fetch).not.toHaveBeenCalled()
})
