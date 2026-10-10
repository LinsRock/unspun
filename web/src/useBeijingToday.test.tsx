// @vitest-environment jsdom
import { act, cleanup, renderHook } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'

import { useBeijingToday } from './useBeijingToday'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

test('the default date advances across Beijing midnight without a query update', () => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-10-09T15:59:30Z'))
  const { result } = renderHook(useBeijingToday)
  expect(result.current).toBe('2026-10-09')
  act(() => vi.advanceTimersByTime(60_000))
  expect(result.current).toBe('2026-10-10')
})

test('restoring a suspended page refreshes the date immediately', () => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date('2026-10-09T15:00:00Z'))
  const { result } = renderHook(useBeijingToday)
  vi.setSystemTime(new Date('2026-10-10T00:00:00Z'))
  act(() => window.dispatchEvent(new Event('focus')))
  expect(result.current).toBe('2026-10-10')
})
