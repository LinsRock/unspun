import { useState } from 'react'

import type { EventOut } from './api'

// How many source chips a collapsed card shows (see DESIGN.md: event card).
const COLLAPSED_SOURCES = 2

// Article URLs come from scraped external feeds; only allow http(s) into href.
function safeHref(url: string): string | undefined {
  try {
    const parsed = new URL(url)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? url : undefined
  } catch {
    return undefined
  }
}

// Score tiers (DESIGN.md): >= 80 hot, 65-79 amber, below neutral. Tier on the
// rounded value so the badge color always matches the number shown.
function scoreTierClasses(rounded: number): string {
  if (rounded >= 80) return 'bg-hot-soft text-hot'
  if (rounded >= 65) return 'bg-amber-soft text-amber'
  return 'bg-bg-sunk text-ink-3'
}

function relativeTime(iso: string): string | null {
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return null
  const minutes = Math.max(0, Math.round((Date.now() - t) / 60_000))
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  return `${Math.floor(hours / 24)} 天前`
}

const SCORE_BADGE =
  'min-w-10 shrink-0 rounded-ctl px-2 py-0.5 text-center font-mono text-sm font-bold tabular-nums'

function ScoreBar({ label, value, sub = false }: { label: string; value: number; sub?: boolean }) {
  return (
    <div className={`flex items-center gap-2 text-[11.5px] text-ink-3 ${sub ? 'pl-3 opacity-80' : ''}`}>
      <span className="w-14 shrink-0">{label}</span>
      <div className="h-[5px] flex-1 overflow-hidden rounded-[3px] bg-line">
        <div
          className={`h-full rounded-[3px] ${sub ? 'bg-ink-4' : 'bg-accent'}`}
          style={{ width: `${Math.min(100, Math.max(0, value))}%` }}
        />
      </div>
      <span className="w-[26px] shrink-0 text-right font-mono tabular-nums">{Math.round(value)}</span>
    </div>
  )
}

function SourceChip({ article }: { article: EventOut['articles'][number] }) {
  return (
    <a
      href={safeHref(article.url)}
      target="_blank"
      rel="noreferrer"
      className="inline-flex max-w-full items-baseline gap-[5px] text-xs hover:underline"
    >
      <span className="shrink-0 font-semibold text-ink-4">{article.source_name}</span>
      <span className="truncate text-accent-ink">{article.title_zh ?? article.title}</span>
    </a>
  )
}

export default function EventCard({ event }: { event: EventOut }) {
  const [showBreakdown, setShowBreakdown] = useState(false)
  const [showAllSources, setShowAllSources] = useState(false)
  const breakdown = event.score_breakdown
  const reason = breakdown?.importance?.reason
  const rounded = event.score_final != null ? Math.round(event.score_final) : null
  const updated = relativeTime(event.changed_at)
  const articles = showAllSources ? event.articles : event.articles.slice(0, COLLAPSED_SOURCES)
  const hiddenCount = event.articles.length - COLLAPSED_SOURCES

  return (
    <article className="rounded-card border border-line bg-surface px-4 py-3.5 shadow-card transition-colors hover:border-line-strong">
      <div className="flex items-start gap-2.5">
        <h2 className="min-w-0 flex-1 text-[15px] font-[650] leading-normal tracking-[0.01em]">
          {event.title ?? '未命名事件'}
        </h2>
        {rounded != null &&
          (breakdown ? (
            <button
              type="button"
              onClick={() => setShowBreakdown((v) => !v)}
              title="查看分数构成"
              aria-expanded={showBreakdown}
              className={`${SCORE_BADGE} ${scoreTierClasses(rounded)}`}
            >
              {rounded}
            </button>
          ) : (
            <span className={`${SCORE_BADGE} ${scoreTierClasses(rounded)}`}>{rounded}</span>
          ))}
      </div>
      <div className="mt-[7px] font-mono text-[11.5px] tabular-nums text-ink-4">
        {event.articles.length} 源{updated != null && ` · 更新于 ${updated}`}
      </div>
      {event.summary_zh && (
        <p className="mt-2 text-[13.5px] leading-[1.7] text-ink-2">{event.summary_zh}</p>
      )}
      {showBreakdown && breakdown && (
        <div className="mt-2.5 flex flex-col gap-[5px] rounded-ctl bg-bg-sunk px-3 py-2.5">
          {breakdown.importance && <ScoreBar label="重要性" value={breakdown.importance.score} />}
          {breakdown.objective && (
            <>
              <ScoreBar label="客观信号" value={breakdown.objective.score} />
              <ScoreBar sub label="报道广度" value={breakdown.objective.breadth} />
              <ScoreBar sub label="增长速度" value={breakdown.objective.growth} />
              <ScoreBar sub label="来源质量" value={breakdown.objective.source_quality} />
            </>
          )}
          {reason && (
            <p className="mt-1.5 text-xs text-ink-3">
              <b className="font-semibold text-ink-2">评分理由</b> {reason}
            </p>
          )}
        </div>
      )}
      <ul className="mt-2.5 flex flex-wrap gap-x-3.5 gap-y-1">
        {articles.map((a) => (
          <li key={a.id} className="max-w-full">
            <SourceChip article={a} />
          </li>
        ))}
      </ul>
      {!showAllSources && hiddenCount > 0 && (
        <div className="mt-[9px] flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setShowAllSources(true)}
            className="flex min-w-[170px] flex-1 items-center justify-between gap-2 rounded-ctl bg-bg-sunk px-3 py-1.5 text-[12.5px] text-ink-3 hover:text-ink-2"
          >
            <span>另有 {hiddenCount} 篇来源报道</span>
            <span>›</span>
          </button>
        </div>
      )}
    </article>
  )
}
