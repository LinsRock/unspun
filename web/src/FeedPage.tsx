import { useCallback, useEffect } from 'react'
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query'
import type { InfiniteData } from '@tanstack/react-query'
import { useFeedPreferences } from './feedPreferences'

import { FeedChangedError, fetchEvents } from './api'
import type { EventsResponse, FeedRange, FeedSort } from './api'
import EventCard from './EventCard'

const SORTS: { value: FeedSort; label: string; explanation: string }[] = [
  { value: 'newest', label: '最新事件', explanation: '按最早原文报道时间排列；新增转载不会刷新事件时间。' },
  { value: 'hot', label: '当前热度', explanation: '按近期媒体报道活动排列；媒体数不代表独立事实证据。' },
  { value: 'important', label: '重要优先', explanation: '近期紧急公共影响优先，其余按综合分排列；卡片数字仍是综合分。' },
]
const RANGES: { value: FeedRange; label: string }[] = [
  { value: 'today', label: '北京时间今天' }, { value: '24h', label: '最近 24 小时' },
  { value: '7d', label: '最近 7 天' }, { value: 'all', label: '全部' },
]
function beijingTime(value: string): string {
  return new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
}
export default function FeedPage() {
  const preferences = useFeedPreferences()
  const { sort, range } = preferences.choice
  const { invalid, reload } = preferences
  const client = useQueryClient()
  const key = ['events', sort, range]
  const query = useInfiniteQuery({
    queryKey: key,
    gcTime: 0,
    enabled: preferences.ready,
    refetchOnWindowFocus: false,
    queryFn: ({ pageParam, signal }) => fetchEvents(sort, range, pageParam, signal),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    retry: (count, error) => !(error instanceof FeedChangedError) && count < 2,
  })
  const seen = new Set<number>()
  const events = query.data?.pages.flatMap((page) => page.events).filter((event) => {
    if (seen.has(event.id)) return false
    seen.add(event.id); return true
  })
  const first = query.data?.pages[0]
  const restart = useCallback(async () => {
    const currentKey = ['events', sort, range]
    await client.cancelQueries({ queryKey: currentKey, exact: true })
    client.setQueryData<InfiniteData<EventsResponse>>(currentKey, (data) => data && ({ ...data, pages: data.pages.slice(0, 1), pageParams: data.pageParams.slice(0, 1) }))
    await client.refetchQueries({ queryKey: currentKey, exact: true, type: 'active' })
  }, [client, sort, range])
  useEffect(() => {
    const timer = window.setInterval(() => { void restart() }, 5 * 60 * 1000)
    return () => window.clearInterval(timer)
  }, [restart])
  useEffect(() => {
    const refresh = () => { if (document.visibilityState === 'visible') { void reload(); void restart() } }
    window.addEventListener('focus', refresh)
    document.addEventListener('visibilitychange', refresh)
    return () => { window.removeEventListener('focus', refresh); document.removeEventListener('visibilitychange', refresh) }
  }, [reload, restart])
  function change(field: 'sort' | 'range', value: string) { void preferences.change(field, value) }
  return (
    <div>
      {import.meta.env.VITE_READING_PREVIEW === 'true' && <p className="mb-5 rounded-ctl border border-line bg-accent-soft px-4 py-3 text-xs leading-relaxed text-ink-2">本地交互预览 · 下列“演示”内容均为模拟，不是真实新闻。另保留 40 个生产历史样本在后台；因缺少完整审核凭证，不作为已发布内容。预览时钟固定于 10 月 14 日。</p>}
      {import.meta.env.VITE_M3B_PREVIEW === 'true' && <p className="mb-4 rounded-ctl border border-line bg-amber-soft p-3 text-xs text-ink-2">本地验收预览 · 固定于 2026-10-14 13:53（北京时间）。包含40个真实事件快照及明确标记的模拟案例；不连接生产或付费处理。</p>}
      <div className="feed-heading">
        <div><h1>实时事件流</h1><p>看清发生了什么，再沿着证据深入。</p></div>
        <button type="button" onClick={() => { void reload(); void restart() }} disabled={query.isFetching}>{query.isFetching ? '刷新中…' : '刷新'}</button>
      </div>
      <div className="feed-controls">
        <div role="group" aria-label="事件排序" className="flex rounded-ctl bg-bg-sunk p-1">
          {SORTS.map((s) => <button key={s.value} type="button" disabled={!preferences.ready || preferences.saving || !preferences.online} aria-pressed={sort === s.value} onClick={() => change('sort', s.value)} className={`rounded-ctl px-3 py-2 text-sm ${sort === s.value ? 'bg-surface font-semibold text-accent-ink shadow-card' : 'text-ink-3 hover:text-ink'}`}>{s.label}</button>)}
        </div>
        <select disabled={!preferences.ready || preferences.saving || !preferences.online} aria-label="时间范围" value={range} onChange={(e) => change('range', e.target.value)} className="max-w-full rounded-ctl border border-line bg-surface px-3 py-2 text-sm text-ink">
          {RANGES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
        </select>
      </div>
      {preferences.message && <p role="status" className="mb-3 text-sm text-amber">{preferences.message}</p>}
      {!preferences.online && <p role="status" className="mb-3 text-sm text-amber">网络不可用，偏好暂不能保存；不会离线排队。</p>}
      <details className="feed-method">
        <summary>{SORTS.find((s) => s.value === sort)!.label} · {RANGES.find((r) => r.value === range)!.label} <span className="ml-2">查看阅读规则</span></summary>
        <p>{SORTS.find((s) => s.value === sort)!.explanation}</p>
        <p>只展示已审核的中文内容；信息有限但有实质事实的材料作为快讯。仅有标题或审核未完成的材料保留在后台。</p>
        <p>{first?.window_end && `报道窗口：${first.window_start ? beijingTime(first.window_start) : '不限起始时间'} — ${beijingTime(first.window_end)}（北京时间）`}{range === 'all' && sort === 'hot' && ' · 热度仅看最近 24 小时'}</p>
        <p>日期不明确的报道仅在“全部”中显示；仅日期的材料按保守时间范围筛选。新报道不自动代表新进展。</p>
      </details>
      {invalid && <p role="status" className="mb-4 text-xs text-amber">筛选参数无效，已恢复默认选择。</p>}
      {query.isPending && <p role="status" className="text-sm text-ink-3">加载中…</p>}
      {query.error != null && <div role="alert" className="mb-3 text-sm text-hot">{query.error instanceof FeedChangedError ? '事件数据已变化，请刷新并从第一页继续。' : '加载失败，请稍后重试'} <button type="button" onClick={() => void (query.error instanceof FeedChangedError ? restart() : query.refetch())} className="ml-2 text-accent-ink underline">重试</button></div>}
      {events?.length === 0 && !query.error && <div className="feed-empty"><h2>这个范围内，暂无可发布的事件</h2><p>有依据、中文完整的内容审核通过后会出现在这里。</p><button type="button" onClick={() => change('range', 'all')} className="text-accent-ink underline">查看全部</button><a href="/admin/content" className="ml-5 text-xs text-ink-3 underline">查看后台内容状态</a></div>}
      {events && <div className={events.length ? "feed-results" : undefined}>{events.map((event, index) => <div key={event.id}>{range === 'all' && event.earliest_reported_precision === 'unknown' && events[index - 1]?.earliest_reported_precision !== 'unknown' && <h2 className="mb-3 mt-4 text-sm font-semibold text-ink-3">报道时间未知</h2>}<EventCard event={event} sort={sort} /></div>)}</div>}
      {query.hasNextPage && <button type="button" disabled={query.isFetching || query.error instanceof FeedChangedError} onClick={() => void query.fetchNextPage()} className="mt-5 w-full rounded-ctl border border-line bg-surface py-3 text-sm text-accent-ink disabled:opacity-50">{query.isFetchingNextPage ? '加载中…' : '加载更多'}</button>}
    </div>
  )
}
