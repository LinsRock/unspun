import { useQuery } from '@tanstack/react-query'

import { fetchEvents } from './api'
import EventCard from './EventCard'

const REFRESH_INTERVAL_MS = 5 * 60 * 1000

export default function App() {
  const { data, error, isPending, dataUpdatedAt } = useQuery({
    queryKey: ['events'],
    queryFn: fetchEvents,
    refetchInterval: REFRESH_INTERVAL_MS,
  })

  return (
    <main className="mx-auto min-h-screen max-w-2xl px-4 py-6">
      <header className="mb-4 flex items-baseline justify-between">
        <h1 className="text-2xl font-bold">Unspun</h1>
        <span className="text-xs text-gray-400">
          实时事件流
          {dataUpdatedAt > 0 && ` · 更新于 ${new Date(dataUpdatedAt).toLocaleTimeString()}`}
        </span>
      </header>
      {isPending && <p className="text-sm text-gray-500">加载中…</p>}
      {error != null && <p className="text-sm text-red-600">加载失败，请稍后重试</p>}
      {data && data.events.length === 0 && (
        <p className="text-sm text-gray-500">暂无事件，等流水线跑完第一轮再来看看</p>
      )}
      {data && (
        <div className="space-y-3">
          {data.events.map((e) => (
            <EventCard key={e.id} event={e} />
          ))}
        </div>
      )}
    </main>
  )
}
