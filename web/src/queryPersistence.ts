import { QueryClient } from '@tanstack/react-query'
import type {
  PersistedClient,
  Persister,
} from '@tanstack/react-query-persist-client'
import { del, get, set } from 'idb-keyval'

export const DIGEST_CACHE_KEY = 'unspun-digests'
const RETENTION_MS = 7 * 24 * 60 * 60 * 1000

export const digestPersistenceOptions = {
  maxAge: RETENTION_MS,
  buster: 'digest-v1',
  dehydrateOptions: {
    shouldDehydrateQuery: (query: {
      queryKey: readonly unknown[]
      state: { data: unknown }
    }) => query.queryKey[0] === 'digest' && query.state.data != null,
    shouldDehydrateMutation: () => false,
  },
}

export function createQueryClient() {
  const client = new QueryClient()
  client.setQueryDefaults(['digest'], { gcTime: RETENTION_MS })
  return client
}

export function createDigestPersister(): Persister {
  return {
    async persistClient(client) {
      try {
        await set(DIGEST_CACHE_KEY, client)
      } catch (error) {
        console.warn('Unable to persist offline digests', error)
      }
    },
    async restoreClient() {
      try {
        const saved = await get<PersistedClient>(DIGEST_CACHE_KEY)
        if (
          saved &&
          (typeof saved.timestamp !== 'number' ||
            typeof saved.buster !== 'string' ||
            !Array.isArray(saved.clientState?.queries) ||
            !Array.isArray(saved.clientState?.mutations))
        ) {
          await del(DIGEST_CACHE_KEY)
          return undefined
        }
        return saved
      } catch (error) {
        console.warn('Unable to restore offline digests', error)
        return undefined
      }
    },
    async removeClient() {
      try {
        await del(DIGEST_CACHE_KEY)
      } catch (error) {
        console.warn('Unable to remove offline digests', error)
      }
    },
  }
}
