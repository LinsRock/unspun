// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import HistoryExport from './HistoryExport'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })

test('oversized export explains how to narrow the query', async () => {
  const request = vi.fn((_input: string) => Promise.resolve({ ok: false, status: 422 }))
  vi.stubGlobal('fetch', request)
  render(<HistoryExport resource="articles" range={{ period: 'custom', start: '2026-10-01T00:00:00Z', end: '2026-10-02T00:00:00Z' }} filters={{ source_id: 'bbc-world' }} />)
  fireEvent.click(screen.getByRole('button', { name: '导出 CSV' }))
  expect(await screen.findByText(/超过 5000 条，请缩小时间范围/)).toBeTruthy()
  expect(request.mock.calls[0]?.[0]).toContain('/api/admin/articles/export.csv?')
  expect(request.mock.calls[0]?.[0]).toContain('source_id=bbc-world')
})
