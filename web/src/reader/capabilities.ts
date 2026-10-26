import { useQuery } from '@tanstack/react-query'
import { request } from './api'
import type { Capabilities } from './api'

export function useCapabilities() {
  return useQuery({ queryKey: ['reading-capabilities'], queryFn: ({ signal }) => request<Capabilities>('/api/reading-capabilities', { signal }), retry: false, staleTime: 60_000 })
}
