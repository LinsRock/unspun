import { afterEach, expect, test, vi } from 'vitest'

import { adjacentDate, isCalendarDate, todayInBeijing } from './digestDates'

afterEach(() => vi.restoreAllMocks())

test('today switches at Beijing midnight instead of UTC midnight', () => {
  vi.spyOn(Date, 'now').mockReturnValue(Date.parse('2026-10-09T15:59:59Z'))
  expect(todayInBeijing()).toBe('2026-10-09')
  vi.mocked(Date.now).mockReturnValue(Date.parse('2026-10-09T16:00:00Z'))
  expect(todayInBeijing()).toBe('2026-10-10')
})

test('date navigation handles month and leap year boundaries', () => {
  expect(adjacentDate('2026-01-01', -1)).toBe('2025-12-31')
  expect(adjacentDate('2024-03-01', -1)).toBe('2024-02-29')
})

test('calendar dates reject impossible dates and alternative formats', () => {
  expect(isCalendarDate('2026-02-30')).toBe(false)
  expect(isCalendarDate('2026-10-10T00:00:00Z')).toBe(false)
  expect(isCalendarDate('2024-02-29')).toBe(true)
})
