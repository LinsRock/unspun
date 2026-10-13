// @vitest-environment jsdom
import { afterEach, expect, test, vi } from 'vitest'

import { money, writeExpense } from './costsApi'

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

test('accounting writes are blocked offline before a request is sent', async () => {
  vi.spyOn(window.navigator, 'onLine', 'get').mockReturnValue(false)
  const fetch = vi.fn()
  vi.stubGlobal('fetch', fetch)
  await expect(writeExpense('expenses', 'POST', { amount: '1' })).rejects.toThrow('离线时无法提交账务')
  expect(fetch).not.toHaveBeenCalled()
})

test('tiny nonzero costs remain visible', () => {
  expect(money('0.00000001')).not.toBe('0')
})
