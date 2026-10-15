import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { fetchPreferences, savePreferences, StateConflict } from './api'
import type { FeedPreferences } from './api'

export const DEFAULT_PREFERENCES: FeedPreferences = { sort: 'newest', range: '7d', unread_only: false, version: 0 }
const STORAGE_KEY = 'unspun.feed-preferences.v1'
export function validPreferences(value: unknown): value is FeedPreferences {
  if (!value || typeof value !== 'object') return false
  const p = value as FeedPreferences
  return ['newest', 'hot', 'important'].includes(p.sort) && ['today', '24h', '7d', 'all'].includes(p.range) && typeof p.unread_only === 'boolean' && Number.isSafeInteger(p.version) && p.version >= 0
}
function remember(p: FeedPreferences) { try { localStorage.setItem(STORAGE_KEY, JSON.stringify(p)) } catch { /* Storage can be unavailable. */ } }
function fallback(): FeedPreferences {
  try { const p: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null'); if (validPreferences(p)) return p } catch { /* Ignore invalid local state. */ }
  return DEFAULT_PREFERENCES
}
export function useFeedPreferences() {
  const [search, setSearch] = useSearchParams()
  const [stored, setStored] = useState<FeedPreferences | null>(null)
  const [message, setMessage] = useState('')
  const [saving, setSaving] = useState(false)
  const writing = useRef(false)
  const generation = useRef(0)
  const [online, setOnline] = useState(navigator.onLine)
  const load = useCallback(async () => {
    if (writing.current) return
    const requestGeneration = ++generation.current
    try {
      const p = await fetchPreferences()
      if (requestGeneration !== generation.current) return
      if (!validPreferences(p)) throw new Error('Invalid preferences')
      setStored(p); remember(p); setMessage('')
    } catch { if (requestGeneration !== generation.current) return; setStored((p) => p ?? fallback()); setMessage('偏好同步失败，暂用本机上次成功同步的选择。可点击刷新重试。') }
  }, [])
  useEffect(() => { void Promise.resolve().then(load) }, [load])
  useEffect(() => {
    const connected = () => { setOnline(true); void load() }
    const disconnected = () => setOnline(false)
    window.addEventListener('online', connected); window.addEventListener('offline', disconnected)
    return () => { window.removeEventListener('online', connected); window.removeEventListener('offline', disconnected) }
  }, [load])
  let invalid = false
  const choice = { ...(stored ?? DEFAULT_PREFERENCES) }
  if (search.has('sort')) {
    const value = search.get('sort')!
    if (['newest', 'hot', 'important'].includes(value)) choice.sort = value as FeedPreferences['sort']
    else { choice.sort = 'newest'; invalid = true }
  }
  if (search.has('range')) {
    const value = search.get('range')!
    if (['today', '24h', '7d', 'all'].includes(value)) choice.range = value as FeedPreferences['range']
    else { choice.range = '7d'; invalid = true }
  }
  if (search.has('unread_only')) {
    const value = search.get('unread_only')
    if (value === 'true' || value === 'false') choice.unread_only = value === 'true'
    else { choice.unread_only = false; invalid = true }
  }
  async function change(field: 'sort' | 'range' | 'unread_only', value: string | boolean) {
    if (!stored || !online || writing.current) return
    const next = { ...choice, [field]: value }
    const url = new URLSearchParams(search)
    url.set('sort', next.sort); url.set('range', next.range); url.set('unread_only', String(next.unread_only))
    setSearch(url)
    generation.current++; writing.current = true; setSaving(true)
    try {
      const saved = await savePreferences({ ...next, version: stored.version })
      setStored(saved); remember(saved); setMessage('')
    } catch (error) {
      if (error instanceof StateConflict && validPreferences(error.current)) {
        setStored(error.current); remember(error.current)
        setMessage('偏好已在其他设备更新，请重试。当前选择尚未保存。')
      } else setMessage('偏好保存失败，当前选择尚未同步。请重试。')
    } finally { writing.current = false; setSaving(false) }
  }
  return { choice, ready: stored !== null, invalid, message, online, saving, change, reload: load }
}
