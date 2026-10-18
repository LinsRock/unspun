// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import App from '../App'
import { BudgetStatus } from './CostRuntime'
import type { CostSummary } from './costsApi'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const unknown = { status: 'unknown' as const, denominator_count: 1, value_usd: null, known_plus_holds_scenario_usd: '0.17' }
const budget: CostSummary['budget'] = { period: 'current_month', limit: '13.5', spent: '7', enforcement: { enabled: true, scope: 'production', monthly_limit_usd: '13.5', unresolved_calls: 1, reserved_usd: '0.17', incident: null, accounting: { period: 'utc_month', known_spend_usd: '7', historical_carry_usd: '1.5', unresolved_holds_usd: '0.17', occupancy_usd: '8.67' }, unit_costs: { per_100_candidates: unknown, per_admitted_item: { ...unknown, status: 'unmeasured', denominator_count: 0 }, per_new_guide: unknown } } }

test('budget occupancy includes carry and holds while unknown unit costs stay unknown', () => {
  render(<BudgetStatus budget={budget} />)
  expect(screen.getByText('8.67')).toBeTruthy()
  expect(screen.getByText(/历史差额 \$1.5/)).toBeTruthy()
  expect(screen.getByText(/未结请求 1 笔/)).toBeTruthy()
  expect(screen.getByText(/每百个尝试候选：费用未知/)).toBeTruthy()
  expect(screen.getByText(/每条准入结果：未测/)).toBeTruthy()
})

test('missing accounting anchors never fall back to a zero or known-only occupancy', () => {
  render(<BudgetStatus budget={{ ...budget, enforcement: { ...budget.enforcement!, accounting: { ...budget.enforcement!.accounting!, historical_carry_usd: null, occupancy_usd: null } } }} />)
  expect(screen.getAllByText('待核对').length).toBeGreaterThan(0)
  expect(screen.queryByText('8.67')).toBeNull()
})

test('unknown physical requests retain holds and link to actual content records', async () => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.stubGlobal('matchMedia', () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} }))
  const requested: string[] = []
  vi.stubGlobal('fetch', vi.fn((input: string) => {
    const url = String(input); requested.push(url)
    const data = url.includes('/api/admin/range') ? { range: { start: '2026-10-01T00:00:00Z', end: '2026-11-01T00:00:00Z' } }
      : url.includes('/api/admin/costs/requests?') ? { page: 1, page_size: 25, total: 1, items: [{ id: 'synthetic-unknown', status: 'usage_unknown', purpose: 'summary', model: 'synthetic-model', reserved_usd: '0.17', provider_generation_id: null, error: 'synthetic timeout', started_at: '2026-10-18T00:00:00Z', article_id: 42, task_id: 58, stage: 'card', phase: 'generate' }] }
      : url.includes('/api/admin/costs?') ? { calls: { count: 0, cost_usd: '0', prompt_tokens: 0, completion_tokens: 0 }, filtered_calls: { count: 0, cost_usd: '0' }, fixed: { confirmed_usd: '0', expected_usd: '0', confirmed_by_currency: {}, expected_by_currency: {}, unconverted_currencies: [] }, total_confirmed_usd: '0', models: [], purposes: [], budget }
      : url.includes('/api/admin/r1/contents/42') ? { id: 42, title: 'Synthetic unknown-cost detail', url: 'https://example.org/synthetic', current_material_id: null, materials: [], observations: [], derivations: [], calls: [] }
      : url.includes('/api/admin/r1/') ? { items: [] }
      : { items: [], total: 0 }
    return Promise.resolve({ ok: true, json: () => Promise.resolve(data) })
  }))
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter initialEntries={['/admin/costs?tab=requests']}><App /></MemoryRouter></QueryClientProvider>)
  expect(await screen.findByText('费用未知', {}, { timeout: 5000 })).toBeTruthy()
  expect(screen.getByText('保留预留 $0.17')).toBeTruthy()
  fireEvent.click(screen.getByRole('link', { name: '内容 #42' }))
  expect(await screen.findByText('Synthetic unknown-cost detail', {}, { timeout: 5000 })).toBeTruthy()
  expect(requested.some(url => url === '/api/admin/r1/contents/42')).toBe(true)
})
