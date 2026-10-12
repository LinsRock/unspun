import { expect, test } from 'vitest'

import { parseRange, presetRange, rangeSearch } from './adminFilters'

const now = new Date('2026-10-11T17:30:00.000Z')

test('Beijing today starts on the previous UTC date', () => {
  const range = presetRange('today', now)
  expect(range.start).toBe('2026-10-11T16:00:00.000Z')
  expect(range.end).toBe(now.toISOString())
})

test('week begins Monday and a rolling day is exactly 24 hours', () => {
  expect(presetRange('week', now).start).toBe('2026-10-11T16:00:00.000Z')
  expect(presetRange('last24h', now).start).toBe(
    '2026-10-10T17:30:00.000Z',
  )
})

test('URL round trip keeps a custom range and unrelated page filters', () => {
  const original = new URLSearchParams('source=bbc&page=3')
  const range = {
    period: 'custom' as const,
    start: '2026-10-01T16:00:00.000Z',
    end: '2026-10-03T16:00:00.000Z',
  }
  const search = rangeSearch(original, range)
  expect(search.get('source')).toBe('bbc')
  expect(search.get('page')).toBe('3')
  expect(parseRange(search, now)).toEqual(range)
})

test('invalid or timezone-free URL range falls back to today', () => {
  for (const search of [
    '?start=2026-10-12T00:00:00&end=2026-10-13T00:00:00',
    '?start=2026-10-13T00:00:00Z&end=2026-10-12T00:00:00Z',
  ]) {
    expect(parseRange(new URLSearchParams(search), now)).toEqual(
      presetRange('today', now),
    )
  }
})

test('stale preset URL preserves its dates and becomes custom', () => {
  const search = new URLSearchParams({
    period: 'today',
    start: '2026-01-01T00:00:00.000Z',
    end: '2026-01-02T00:00:00.000Z',
  })
  expect(parseRange(search, now)).toEqual({
    period: 'custom',
    start: '2026-01-01T00:00:00.000Z',
    end: '2026-01-02T00:00:00.000Z',
  })
})

test('yesterday URL opened a day later keeps the original day', () => {
  const selected = presetRange('yesterday', now)
  const search = rangeSearch(new URLSearchParams(), selected)
  expect(parseRange(search, new Date('2026-10-12T17:30:00.000Z'))).toEqual({
    ...selected,
    period: 'custom',
  })
})
