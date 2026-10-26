// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import App from './App'

vi.mock('./FeedPage', () => ({ default: () => <h1>实时事件流</h1> }))
vi.mock('./DigestPage', () => ({ default: () => <h1>每日日报</h1> }))
vi.mock('./reader/HybridPage', () => ({ default: () => <h1>跟上变化，发现好内容</h1> }))
vi.mock('./reader/ContentPage', () => ({ default: () => <h1>独立内容详情</h1> }))

function Location() {
  const location = useLocation()
  return <output aria-label="当前位置">{location.pathname + location.search + location.hash}</output>
}
function setup(path: string, home: 'events' | 'discover' = 'discover', hybrid = true) {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ home, hybrid, topic_preferences: false, engineering_preview: false })))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><App /><Location /></MemoryRouter></QueryClientProvider>)
}
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

it('opens the accepted discovery page using formal capabilities', async () => {
  setup('/')
  await screen.findByRole('heading', { name: '跟上变化，发现好内容' })
  expect(screen.getByLabelText('当前位置').textContent).toBe('/discover')
})

it.each([
  ['/?sort=hot&range=all#saved', '实时事件流'],
  ['/?range=24h', '实时事件流'],
  ['/?unread_only=true', '实时事件流'],
  ['/?sort=invalid&range=invalid', '实时事件流'],
  ['/events?sort=important&range=all', '实时事件流'],
  ['/digest?date=2026-10-18', '每日日报'],
  ['/reading/9192', '独立内容详情'],
])('preserves the historical URL %s through enablement', async (path, heading) => {
  setup(path)
  await screen.findByRole('heading', { name: heading })
  expect(screen.getByLabelText('当前位置').textContent).toBe(path)
})

it.each([true, false])('restores the event home with hybrid=%s without rewriting URLs', async hybrid => {
  setup('/', 'events', hybrid)
  await screen.findByRole('heading', { name: '实时事件流' })
  expect(screen.getByLabelText('当前位置').textContent).toBe('/')
})
