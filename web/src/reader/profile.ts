import { useEffect, useRef, useState } from 'react'
import { useIsMutating, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { mutationId, ReaderError, request } from './api'
import type { ReaderState } from './api'
import { useCapabilities } from './capabilities'

export function useReader() {
  const client = useQueryClient()
  const capabilities = useCapabilities()
  const topics = capabilities.data?.topic_preferences === true
  const profile = useQuery({ queryKey: ['r1-reader'], enabled: !capabilities.isPending, queryFn: ({ signal }) => request<ReaderState>(topics ? '/api/topic-preferences' : '/api/reader-preferences', { signal }), retry: false, staleTime: 0 })
  const [online, setOnline] = useState(navigator.onLine)
  const [message, setMessage] = useState('')
  const lock = useRef(false)
  const mutation = useMutation({ mutationKey: ['r1-reader-write'], retry: false, mutationFn: async ({ path, method, body }: { path: string; method: string; body: object }) => {
    const state = await request<ReaderState>(path, { method, body: JSON.stringify(body) })
    return topics && !state.topic_preferences ? request<ReaderState>('/api/topic-preferences') : state
  } })
  const saving = useIsMutating({ mutationKey: ['r1-reader-write'] }) > 0
  useEffect(() => {
    const update = () => setOnline(navigator.onLine)
    window.addEventListener('online', update); window.addEventListener('offline', update)
    return () => { window.removeEventListener('online', update); window.removeEventListener('offline', update) }
  }, [])
  async function change(path: string, method: string, body: object, options: { announceSuccess?: boolean } = {}): Promise<boolean> {
    if (lock.current || saving || profile.error || !profile.data || !navigator.onLine) return false
    lock.current = true; setMessage('')
    try {
      await client.cancelQueries({ queryKey: ['r1-reader'] })
      const state = await mutation.mutateAsync({ path, method, body: { ...body, version: profile.data.version, mutation_id: mutationId() } })
      client.setQueryData(['r1-reader'], state)
      await client.invalidateQueries({ queryKey: ['r1-feed'] })
      await client.invalidateQueries({ queryKey: ['r2-feed'], refetchType: 'none' })
      if (options.announceSuccess !== false) setMessage('已保存，可随时撤销。')
      return true
    } catch (error) {
      if (error instanceof ReaderError && error.status === 409) {
        if (error.current && (!topics || error.current.topic_preferences)) client.setQueryData(['r1-reader'], error.current)
        else if ((await profile.refetch()).error) {
          setMessage('设置发生冲突，但当前状态读取失败。请重新加载后核对，不会自动重试操作。')
          return false
        }
        setMessage('另一台设备已更新设置，已载入当前状态。请核对后重新操作。')
      } else {
        const result = await profile.refetch()
        setMessage(result.error ? '未能确认保存结果，当前状态也暂时无法读取。请联网后重新加载核对；不会离线排队。' : '未能确认保存结果，已重新读取服务器状态。请核对后重新操作；不会离线排队。')
      }
      return false
    } finally { lock.current = false }
  }
  return { ...profile, change, saving, online, message, topics }
}
