// @vitest-environment jsdom
import 'fake-indexeddb/auto'
import { onlineManager } from '@tanstack/react-query'
import {
  PersistQueryClientProvider,
  persistQueryClientSave,
  persistQueryClientRestore,
} from '@tanstack/react-query-persist-client'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { clear, get, set } from 'idb-keyval'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import App from './App'
import {
  createDigestPersister,
  createQueryClient,
  digestPersistenceOptions,
  DIGEST_CACHE_KEY,
} from './queryPersistence'

const digest = {
  report_date: '2026-10-10',
  kind: 'daily',
  generated_at: '2026-10-10T00:00:00Z',
  payload: {
    intro: '持久化日报导语',
    window_start: '2026-10-09T00:00:00Z',
    window_end: '2026-10-10T00:00:00Z',
    timezone: 'Asia/Shanghai',
    events: [],
  },
}

afterEach(async () => {
  cleanup()
  onlineManager.setOnline(true)
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  await clear()
})

function options() {
  return { ...digestPersistenceOptions, persister: createDigestPersister() }
}

test('restores a digest into a new client using IndexedDB, excludes other queries and empty digests', async () => {
  const first = createQueryClient()
  first.setQueryData(['digest', digest.report_date], digest)
  first.setQueryData(['digest', '2026-10-09'], null)
  first.setQueryData(['events'], { events: [] })
  await persistQueryClientSave({ queryClient: first, ...options() })
  const second = createQueryClient()
  await persistQueryClientRestore({ queryClient: second, ...options() })
  expect(second.getQueryData(['digest', digest.report_date])).toEqual(digest)
  expect(second.getQueryData(['digest', '2026-10-09'])).toBeUndefined()
  expect(second.getQueryData(['events'])).toBeUndefined()
  first.clear()
  second.clear()
})

test.each(['expired', 'version'])('discards %s caches', async (reason) => {
  const first = createQueryClient()
  first.setQueryData(['digest', digest.report_date], digest)
  await persistQueryClientSave({ queryClient: first, ...options() })
  const stored = await createDigestPersister().restoreClient()
  if (!stored) throw new Error('Expected saved cache')
  if (reason === 'expired')
    stored.timestamp = Date.now() - digestPersistenceOptions.maxAge - 1
  else stored.buster = 'old-schema'
  await createDigestPersister().persistClient(stored)
  const second = createQueryClient()
  await persistQueryClientRestore({ queryClient: second, ...options() })
  expect(second.getQueryData(['digest', digest.report_date])).toBeUndefined()
  expect(await get(DIGEST_CACHE_KEY)).toBeUndefined()
  first.clear()
  second.clear()
})

test('failed background refresh keeps the existing snapshot in persisted storage', async () => {
  const first = createQueryClient()
  first.setQueryData(['digest', digest.report_date], digest)
  await expect(
    first.fetchQuery({
      queryKey: ['digest', digest.report_date],
      queryFn: () => Promise.reject(new Error('network')),
      retry: false,
    }),
  ).rejects.toThrow('network')
  await persistQueryClientSave({ queryClient: first, ...options() })
  const second = createQueryClient()
  await persistQueryClientRestore({ queryClient: second, ...options() })
  expect(second.getQueryData(['digest', digest.report_date])).toEqual(digest)
  first.clear()
  second.clear()
})

test('storage failures do not prevent online use', async () => {
  vi.spyOn(IDBDatabase.prototype, 'transaction').mockImplementation(() => {
    throw new Error('storage unavailable')
  })
  vi.spyOn(console, 'warn').mockImplementation(() => {})
  const persister = createDigestPersister()
  await expect(persister.restoreClient()).resolves.toBeUndefined()
  await expect(
    persister.persistClient({
      timestamp: Date.now(),
      buster: '',
      clientState: { queries: [], mutations: [] },
    }),
  ).resolves.toBeUndefined()
  await expect(persister.removeClient()).resolves.toBeUndefined()
  expect(console.warn).toHaveBeenCalledTimes(3)
})

test('provider restores the snapshot before querying and renders after an offline restart', async () => {
  const first = createQueryClient()
  first.setQueryData(['digest', digest.report_date], digest)
  await persistQueryClientSave({ queryClient: first, ...options() })
  first.clear()
  onlineManager.setOnline(false)
  const fetch = vi.fn().mockRejectedValue(new Error('offline'))
  vi.stubGlobal('fetch', fetch)
  const second = createQueryClient()
  render(
    <PersistQueryClientProvider client={second} persistOptions={options()}>
      <MemoryRouter initialEntries={['/digest?date=2026-10-10']}>
        <App />
      </MemoryRouter>
    </PersistQueryClientProvider>,
  )
  await screen.findByText('持久化日报导语')
  expect(screen.getByText(/离线阅读/)).toBeTruthy()
  expect(fetch).not.toHaveBeenCalled()
  cleanup()
  second.clear()
})

test('latest digest also populates its report date for default offline navigation', async () => {
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValue({ ok: true, json: () => Promise.resolve(digest) }),
  )
  const client = createQueryClient()
  render(
    <PersistQueryClientProvider client={client} persistOptions={options()}>
      <MemoryRouter initialEntries={['/digest?date=latest']}>
        <App />
      </MemoryRouter>
    </PersistQueryClientProvider>,
  )
  await screen.findByText('持久化日报导语')
  await waitFor(() =>
    expect(client.getQueryData(['digest', digest.report_date])).toEqual(digest),
  )
  cleanup()
  client.clear()
})

test('offline uncached date explains how to make a digest available, then recovers online', async () => {
  onlineManager.setOnline(false)
  vi.stubGlobal(
    'fetch',
    vi
      .fn()
      .mockResolvedValue({ ok: true, json: () => Promise.resolve(digest) }),
  )
  const client = createQueryClient()
  render(
    <PersistQueryClientProvider client={client} persistOptions={options()}>
      <MemoryRouter initialEntries={['/digest?date=2026-10-10']}>
        <App />
      </MemoryRouter>
    </PersistQueryClientProvider>,
  )
  await screen.findByText(/此日期没有离线日报/)
  expect(screen.queryByText('日报加载中…')).toBeNull()
  onlineManager.setOnline(true)
  await screen.findByText('持久化日报导语')
  cleanup()
  client.clear()
})

test('removes malformed persisted state and still opens the page online', async () => {
  await set(DIGEST_CACHE_KEY, { corrupted: true })
  const client = createQueryClient()
  await persistQueryClientRestore({ queryClient: client, ...options() })
  expect(await get(DIGEST_CACHE_KEY)).toBeUndefined()
  client.clear()
})
