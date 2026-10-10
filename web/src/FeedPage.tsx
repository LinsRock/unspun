import { useQuery } from '@tanstack/react-query'

import { fetchEvents } from './api'
import EventCard from './EventCard'

const REFRESH_INTERVAL_MS = 5 * 60 * 1000

export default function FeedPage() {
  const { data, error, isPending, dataUpdatedAt, refetch } = useQuery({
    queryKey: ['events'],
    queryFn: fetchEvents,
    refetchInterval: REFRESH_INTERVAL_MS,
  })
  return (
    <div className="mx-auto max-w-[760px]">
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h1 className="text-xl font-bold tracking-[0.01em]">实时事件流</h1>
        <span className="font-mono text-xs tabular-nums text-ink-4">
          {dataUpdatedAt > 0 &&
            `更新于 ${new Date(dataUpdatedAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })} · `}
          每 {REFRESH_INTERVAL_MS / 60_000} 分钟
        </span>
      </div>
      {isPending && (
        <p role="status" className="text-sm text-ink-3">
          加载中…
        </p>
      )}
      {error != null && (
        <div role="alert" className="mb-3 text-sm text-hot">
          加载失败，请稍后重试{' '}
          <button
            type="button"
            onClick={() => void refetch()}
            className="ml-2 text-accent-ink underline"
          >
            重试
          </button>
        </div>
      )}
      {data && data.events.length === 0 && (
        <p className="text-sm text-ink-3">
          暂无事件，等流水线跑完第一轮再来看看
        </p>
      )}
      {data && (
        <div className="flex flex-col gap-2.5">
          {data.events.map((event) => (
            <EventCard key={event.id} event={event} />
          ))}
        </div>
      )}
    </div>
  )
}
