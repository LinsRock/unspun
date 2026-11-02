// @vitest-environment jsdom
import 'fake-indexeddb/auto'
import { clear, get, set } from 'idb-keyval'
import { afterEach, expect, test, vi } from 'vitest'
import { clearRetiredReadingCache } from './retiredReadingCache'

afterEach(async () => { vi.restoreAllMocks(); localStorage.clear(); await clear() })

test('removes only retired reading keys and is idempotent', async () => {
  await set('unspun-digests', { buster: 'digest-v1', clientState: { queries: ['old snapshot'] } })
  await set('other-data', { keep: true })
  localStorage.setItem('unspun.feed-preferences.v2', 'old preferences')
  localStorage.setItem('unspun-theme', 'dark')
  await clearRetiredReadingCache()
  await clearRetiredReadingCache()
  expect(await get('unspun-digests')).toBeUndefined()
  expect(await get('other-data')).toEqual({ keep: true })
  expect(localStorage.getItem('unspun.feed-preferences.v2')).toBeNull()
  expect(localStorage.getItem('unspun-theme')).toBe('dark')
})

test('storage errors do not block current reading and a later attempt retries', async () => {
  await set('unspun-digests', 'old snapshot')
  const transaction = vi.spyOn(IDBDatabase.prototype, 'transaction').mockImplementationOnce(() => { throw new Error('storage unavailable') })
  const warning = vi.spyOn(console, 'warn').mockImplementation(() => {})
  await expect(clearRetiredReadingCache()).resolves.toBeUndefined()
  expect(warning).toHaveBeenCalledOnce()
  transaction.mockRestore()
  expect(await get('unspun-digests')).toBe('old snapshot')
  await clearRetiredReadingCache()
  expect(await get('unspun-digests')).toBeUndefined()
})
