import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'

import { fetchDigest } from './api'
import { adjacentDate, digestTime, isCalendarDate } from './digestDates'
import DigestItem from './DigestItem'
import { useBeijingToday } from './useBeijingToday'

const CONTROL =
  'min-h-10 rounded-ctl border border-line bg-surface px-3 text-xs text-ink-3 hover:border-line-strong disabled:cursor-not-allowed disabled:opacity-40'

export default function DigestPage() {
  const [params, setParams] = useSearchParams()
  const today = useBeijingToday()
  const selected = params.get('date') ?? today
  const latest = selected === 'latest'
  const valid = latest || (isCalendarDate(selected) && selected <= today)
  const { data, error, isPending, refetch } = useQuery({
    queryKey: ['digest', selected],
    queryFn: () => fetchDigest(selected),
    enabled: valid,
    retry: false,
    refetchInterval: latest || selected === today ? 5 * 60 * 1000 : false,
  })
  const displayed = latest
    ? (data?.report_date ?? today)
    : valid
      ? selected
      : today
  function chooseDate(date: string) {
    setParams({ date })
  }
  return (
    <div className="mx-auto max-w-[760px]">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h1 className="text-xl font-bold tracking-[0.01em]">每日日报</h1>
        <span className="text-xs text-ink-4">北京时间 08:00 生成</span>
      </div>
      <div className="mt-5 flex flex-wrap items-center gap-2">
        <button
          type="button"
          aria-label="前一天"
          disabled={!valid || (latest && !data)}
          onClick={() => chooseDate(adjacentDate(displayed, -1))}
          className={CONTROL}
        >
          ‹
        </button>
        <input
          type="date"
          aria-label="日报日期"
          value={displayed}
          max={today}
          onChange={(event) => {
            if (event.target.value) chooseDate(event.target.value)
          }}
          className="min-h-10 min-w-0 max-w-full rounded-ctl border border-line bg-surface px-2 font-mono text-sm tabular-nums text-ink"
        />
        <button
          type="button"
          aria-label="后一天"
          disabled={!valid || displayed >= today || (latest && !data)}
          onClick={() => chooseDate(adjacentDate(displayed, 1))}
          className={CONTROL}
        >
          ›
        </button>
        <button type="button" onClick={() => setParams({})} className={CONTROL}>
          今天
        </button>
        <button
          type="button"
          onClick={() => chooseDate('latest')}
          className={`${CONTROL} ${latest ? 'border-accent bg-accent-soft text-accent-ink' : ''}`}
        >
          最新一期
        </button>
      </div>
      <p className="mb-4 mt-2 text-[11.5px] text-ink-4">
        {latest ? '最新已生成日报' : `${displayed} · 日报快照`} · 过去 24
        小时热度排行
      </p>
      {!valid && (
        <p
          role="alert"
          className="rounded-card border border-line bg-surface p-4 text-sm text-hot"
        >
          日期无效，请选择今天或更早的有效日期。
        </p>
      )}
      {valid && isPending && (
        <p role="status" className="text-sm text-ink-3">
          日报加载中…
        </p>
      )}
      {valid && error != null && (
        <div
          role="alert"
          className="rounded-card border border-line bg-surface p-4"
        >
          <p className="text-sm text-hot">日报加载失败，请检查网络后重试。</p>
          <button
            type="button"
            onClick={() => void refetch()}
            className="mt-3 text-sm text-accent-ink underline"
          >
            重试
          </button>
        </div>
      )}
      {valid && data === null && (
        <div className="rounded-card border border-line bg-surface p-5">
          <h2 className="text-sm font-semibold">
            {latest ? '还没有已生成的日报' : '这一天的日报尚未生成'}
          </h2>
          <p className="mt-2 text-[13px] text-ink-3">
            可以选择其他日期，或查看最新一期已生成的日报。
          </p>
        </div>
      )}
      {valid && data && (
        <>
          <div className="rounded-card border border-line border-l-[3px] border-l-accent bg-surface px-4 py-3.5 shadow-card">
            <p className="text-sm leading-[1.85] text-ink-2">
              {data.payload.intro}
            </p>
            <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 font-mono text-[11px] tabular-nums text-ink-4">
              <span>
                生成于 {digestTime(data.generated_at, data.payload.timezone)}
              </span>
              <span>入选 {data.payload.events.length} 个事件</span>
            </div>
            <div className="mt-1 font-mono text-[11px] tabular-nums text-ink-4">
              {digestTime(data.payload.window_start, data.payload.timezone)} —{' '}
              {digestTime(data.payload.window_end, data.payload.timezone)}
            </div>
          </div>
          {data.payload.events.length === 0 ? (
            <p className="mt-5 text-sm text-ink-3">
              过去 24 小时暂无入选事件。
            </p>
          ) : (
            <div className="mt-2">
              {data.payload.events.map((event, index) => (
                <DigestItem key={event.id} event={event} rank={index + 1} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
