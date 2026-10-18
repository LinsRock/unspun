// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'

import App from '../App'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

test('cost page separates the full period total from filtered calls', async () => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
  const requested: string[] = []
  vi.stubGlobal('fetch', vi.fn((input: string) => {
    requested.push(String(input))
    const data = String(input).includes('/api/admin/range') ? { range: { start: '2026-10-01T00:00:00Z', end: '2026-10-02T00:00:00Z' }, as_of: '2026-10-02T00:00:00Z' } : String(input).includes('/api/admin/costs/calls?') ? { page: 1, page_size: 25, total: 1, items: [{ id: 1, created_at: '2026-10-18T00:00:00Z', purpose: 'summary', model: 'synthetic-model', prompt_tokens: 10, completion_tokens: 2, cost_usd: '1', association: 'recorded', article_id: 42, task_id: 58, stage: 'guide', phase: 'review' }] } : {
      calls: { count: 2, prompt_tokens: 12, completion_tokens: 3, cost_usd: '2' }, filtered_calls: { count: 1, prompt_tokens: 10, completion_tokens: 2, cost_usd: '1' },
      fixed: { confirmed_by_currency: { USD: '10' }, expected_by_currency: {}, spend_by_currency: {}, confirmed_usd: '10', expected_usd: '0', spend_usd: '0', unconverted_currencies: [] },
      total_confirmed_usd: '12', trend: [], purposes: [], models: [], budget: { period: 'current_month', limit: '50', spent: '5' },
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve(data) })
  }))
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter initialEntries={['/admin/costs?period=custom&start=2026-10-01T00%3A00%3A00Z&end=2026-10-02T00%3A00%3A00Z&tab=calls&model=a']}><App /></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByText('当前筛选：1 次调用，合计 1 USD。筛选仅影响明细，不改变上方总额。', {}, { timeout: 5000 })).toBeTruthy()
  expect(screen.getByText('12')).toBeTruthy()
  expect(screen.getByRole('link', { name: '内容 #42' }).getAttribute('href')).toBe('/admin/content?r1_content=42')
  expect(screen.getByText('任务 #58')).toBeTruthy()
  expect(requested.some(url => url.includes('/api/admin/costs?') && url.includes('model=a'))).toBe(true)
})
