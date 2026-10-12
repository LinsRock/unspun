// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'

import App from '../App'

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class {
    observe() {}
    unobserve() {}
    disconnect() {}
  })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function renderAdmin(path: string, failFirst = false) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: () =>
      Promise.resolve({
        range: {
          start: '2026-10-11T16:00:00Z',
          end: '2026-10-12T08:00:00Z',
          timezone: 'Asia/Shanghai',
          end_exclusive: true,
        },
        as_of: '2026-10-12T08:00:00Z',
        page: 1,
        page_size: 25,
        sort: 'newest',
      }),
  })
  if (failFirst) fetchMock.mockRejectedValueOnce(new Error('offline'))
  vi.stubGlobal(
    'fetch',
    fetchMock,
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

test('admin workspace has six entries and honest pending states', async () => {
  renderAdmin('/admin/sources')
  expect(await screen.findByRole('navigation', { name: '后台导航' }, { timeout: 5000 })).toBeTruthy()
  for (const name of ['总览', '信息源', '文章与事件', '运行与任务', '费用', '配置与操作记录']) {
    expect(screen.getByRole('link', { name })).toBeTruthy()
  }
  expect(screen.getByRole('heading', { name: '信息源' })).toBeTruthy()
  expect(await screen.findByText(/历史查询将在 A2 接入/)).toBeTruthy()
})

test('legacy report path keeps an entry to admin overview', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503 }))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/report']}><App /></MemoryRouter>
    </QueryClientProvider>,
  )
  expect(screen.getByRole('heading', { name: '运行报告' })).toBeTruthy()
  fireEvent.click(screen.getByRole('link', { name: '进入管理后台' }))
  expect(await screen.findByRole('heading', { name: '总览' })).toBeTruthy()
})

test('admin query failure is visible and retryable', async () => {
  renderAdmin('/admin/costs', true)
  expect(await screen.findByText(/无法获取查询时间/)).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: /重\s*试/ }))
  expect(await screen.findByText(/查询截止/)).toBeTruthy()
})

test('custom URL range survives refresh and cross-page navigation without page filters', async () => {
  renderAdmin('/admin/sources?period=custom&start=2026-10-01T00%3A00%3A00Z&end=2026-10-02T00%3A00%3A00Z&source=bbc')
  await screen.findByRole('navigation', { name: '后台导航' }, { timeout: 5000 })
  const costs = screen.getByRole('link', { name: '费用' })
  expect(costs.getAttribute('href')).toContain('period=custom')
  expect(costs.getAttribute('href')).toContain('start=2026-10-01T00%3A00%3A00Z')
  expect(costs.getAttribute('href')).not.toContain('source=bbc')
  fireEvent.click(costs)
  expect(await screen.findByRole('heading', { name: '费用' })).toBeTruthy()
})
