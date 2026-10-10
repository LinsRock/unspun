import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { fetchEvents } from './api'
import EventCard from './EventCard'
import ReportPanel from './ReportPanel'
import ThemeToggle from './ThemeToggle'

const REFRESH_INTERVAL_MS = 5 * 60 * 1000

export default function App() {
  const [showReport, setShowReport] = useState(false)
  const { data, error, isPending, dataUpdatedAt } = useQuery({
    queryKey: ['events'],
    queryFn: fetchEvents,
    refetchInterval: REFRESH_INTERVAL_MS,
  })

  return (
    <main className="mx-auto min-h-screen max-w-[760px] px-4 py-6 sm:px-5">
      <header className="flex items-center justify-between gap-3">
        <div className="flex items-baseline gap-2">
          <span className="text-[17px] font-bold tracking-[0.02em]">
            <span className="text-accent">U</span>nspun
          </span>
          <span className="text-[11px] text-ink-4">个人情报站</span>
        </div>
        <ThemeToggle />
      </header>
      <div className="mt-5 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h1 className="text-xl font-bold tracking-[0.01em]">实时事件流</h1>
        <span className="font-mono text-xs tabular-nums text-ink-4">
          {dataUpdatedAt > 0 &&
            `更新于 ${new Date(dataUpdatedAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })} · `}
          每 {REFRESH_INTERVAL_MS / 60_000} 分钟
        </span>
      </div>
      <div className="mb-4 mt-3.5 flex flex-wrap gap-1.5">
        <button
          type="button"
          onClick={() => setShowReport((v) => !v)}
          aria-pressed={showReport}
          className={`rounded-full border px-3 py-1 text-[12.5px] transition-colors ${
            showReport
              ? 'border-ink bg-ink font-semibold text-bg'
              : 'border-line bg-surface-2 text-ink-3 hover:bg-bg-sunk'
          }`}
        >
          运行报告
        </button>
      </div>
      {showReport && <ReportPanel />}
      {isPending && <p className="text-sm text-ink-3">加载中…</p>}
      {error != null && <p className="text-sm text-hot">加载失败，请稍后重试</p>}
      {data && data.events.length === 0 && (
        <p className="text-sm text-ink-3">暂无事件，等流水线跑完第一轮再来看看</p>
      )}
      {data && (
        <div className="flex flex-col gap-2.5">
          {data.events.map((e) => (
            <EventCard key={e.id} event={e} />
          ))}
        </div>
      )}
    </main>
  )
}
