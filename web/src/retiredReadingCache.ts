import { del } from 'idb-keyval'

export async function clearRetiredReadingCache() {
  try { localStorage.removeItem('unspun.feed-preferences.v2') } catch { /* Storage may be unavailable. */ }
  try {
    await del('unspun-digests')
  } catch (error) {
    // A later app start retries cleanup without blocking current reading.
    console.warn('Unable to remove retired reading cache', error)
  }
}
