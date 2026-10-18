import { useEffect, useRef, useState } from 'react'
import { useIsMutating, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ReaderError, request } from './api'
import type { ReaderState } from './api'

export function useReader() {
  const client = useQueryClient()
  const profile = useQuery({ queryKey: ['r1-reader'], queryFn: ({ signal }) => request<ReaderState>('/api/reader-preferences', { signal }), retry: false, staleTime: 0 })
  const [online, setOnline] = useState(navigator.onLine)
  const [message, setMessage] = useState('')
  const lock = useRef(false)
  const mutation = useMutation({ mutationKey: ['r1-reader-write'], retry: false, mutationFn: ({ path, method, body }: { path: string; method: string; body: object }) => request<ReaderState>(path, { method, body: JSON.stringify(body) }) })
  const saving = useIsMutating({ mutationKey: ['r1-reader-write'] }) > 0
  useEffect(() => {
    const update = () => setOnline(navigator.onLine)
    window.addEventListener('online', update); window.addEventListener('offline', update)
    return () => { window.removeEventListener('online', update); window.removeEventListener('offline', update) }
  }, [])
  async function change(path: string, method: string, body: object, options: { announceSuccess?: boolean } = {}): Promise<boolean> {
    if (lock.current || saving || !profile.data || !navigator.onLine) return false
    lock.current = true; setMessage('')
    try {
      const state = await mutation.mutateAsync({ path, method, body: { ...body, version: profile.data.version, mutation_id: crypto.randomUUID() } })
      client.setQueryData(['r1-reader'], state)
      await client.invalidateQueries({ queryKey: ['r1-feed'] })
      if (options.announceSuccess !== false) setMessage('已保存，可随时撤销。')
      return true
    } catch (error) {
      if (error instanceof ReaderError && error.status === 409) {
        if (error.current) client.setQueryData(['r1-reader'], error.current)
        else await profile.refetch()
        setMessage('另一台设备已更新设置，已载入当前状态。请核对后重新操作。')
      } else {
        setMessage('未能确认保存结果，已重新读取服务器状态。请联网后核对；不会离线排队。')
        await profile.refetch()
      }
      return false
    } finally { lock.current = false }
  }
  return { ...profile, change, saving, online, message }
}
