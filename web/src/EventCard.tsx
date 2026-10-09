import { useState } from 'react'

import type { EventOut } from './api'

// Article URLs come from scraped external feeds; only allow http(s) into href.
function safeHref(url: string): string | undefined {
  try {
    const parsed = new URL(url)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? url : undefined
  } catch {
    return undefined
  }
}

function ScoreBar({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex items-center gap-2 text-xs text-gray-500">
      <span className="w-16 shrink-0">{label}</span>
      <div className="h-1.5 flex-1 rounded bg-gray-100">
        <div
          className="h-1.5 rounded bg-blue-400"
          style={{ width: `${Math.min(100, Math.max(0, value))}%` }}
        />
      </div>
      <span className="w-8 text-right tabular-nums">{Math.round(value)}</span>
    </div>
  )
}

export default function EventCard({ event }: { event: EventOut }) {
  const [showBreakdown, setShowBreakdown] = useState(false)
  const breakdown = event.score_breakdown
  const reason = breakdown?.importance?.reason
  return (
    <article className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <h2 className="text-base font-semibold leading-snug">{event.title ?? '未命名事件'}</h2>
        {event.score_final != null && (
          <button
            type="button"
            onClick={() => setShowBreakdown((v) => !v)}
            className="shrink-0 rounded-full bg-blue-50 px-2.5 py-0.5 text-sm font-semibold tabular-nums text-blue-700"
            title="查看分数构成"
          >
            {Math.round(event.score_final)}
          </button>
        )}
      </div>
      {event.summary_zh && (
        <p className="mt-2 text-sm leading-relaxed text-gray-700">{event.summary_zh}</p>
      )}
      {reason && <p className="mt-2 text-xs text-gray-500">评分理由：{reason}</p>}
      {showBreakdown && breakdown && (
        <div className="mt-3 space-y-1 rounded-lg bg-gray-50 p-3">
          {breakdown.objective && (
            <>
              <ScoreBar label="客观信号" value={breakdown.objective.score} />
              <ScoreBar label="报道广度" value={breakdown.objective.breadth} />
              <ScoreBar label="增长速度" value={breakdown.objective.growth} />
              <ScoreBar label="来源质量" value={breakdown.objective.source_quality} />
            </>
          )}
          {breakdown.importance && (
            <ScoreBar label="重要性" value={breakdown.importance.score} />
          )}
        </div>
      )}
      <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1">
        {event.articles.map((a) => (
          <li key={a.id} className="max-w-full">
            <a
              href={safeHref(a.url)}
              target="_blank"
              rel="noreferrer"
              className="inline-flex max-w-full items-baseline gap-1 text-xs text-blue-600 hover:underline"
            >
              <span className="shrink-0 font-medium text-gray-400">{a.source_name}</span>
              <span className="truncate">{a.title_zh ?? a.title}</span>
            </a>
          </li>
        ))}
      </ul>
    </article>
  )
}
