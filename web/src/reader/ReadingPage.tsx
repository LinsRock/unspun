import { useEffect, useLayoutEffect, useRef } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query'
import { getFeed, ReaderError } from './api'
import type { ContentItem, Feedback, Sort } from './api'
import { useReader } from './profile'
import { DOMAINS, GENRES, publication, SCOPES } from './presentation'
import { safeHref } from '../links'
import './reader.css'

const positions = new Map<string, number>()
export default function ReadingPage() {
  const profile = useReader(); const client = useQueryClient(); const location = useLocation()
  const [params, setParams] = useSearchParams()
  const sort: Sort = params.get('sort') === 'latest' ? 'latest' : params.get('sort') === 'recommended' ? 'recommended' : profile.data?.sort ?? 'recommended'
  const query = useInfiniteQuery({ queryKey: ['r1-feed', sort, profile.data?.version], enabled: !!profile.data, queryFn: ({ pageParam, signal }) => getFeed(sort, pageParam, signal), initialPageParam: undefined as string | undefined, getNextPageParam: page => page.next_cursor ?? undefined, retry: false, refetchOnWindowFocus: false, staleTime: 60_000 })
  const restored = useRef(false)
  useEffect(() => {
    if (!query.data || restored.current) return
    const frame = requestAnimationFrame(() => {
      restored.current = true
      window.scrollTo(0, positions.get(sort) ?? 0)
    })
    return () => cancelAnimationFrame(frame)
  }, [query.data, sort])
  useLayoutEffect(() => () => {
    if (restored.current) positions.set(sort, window.scrollY)
  }, [sort])
  const rememberPosition = () => { positions.set(sort, window.scrollY) }
  const seen = new Set<number>(); const items = query.data?.pages.flatMap(p => p.items).filter(item => !seen.has(item.id) && !!seen.add(item.id)) ?? []
  async function changeSort(next: Sort) { setParams({ sort: next }); restored.current = false; await profile.change('/api/reader-preferences', 'PUT', { sort: next }) }
  async function feedback(item: ContentItem, value: Feedback) {
    const current = profile.data?.feedback.find(f => f.content_id === item.id)?.value
    await profile.change('/api/feedback', current === value ? 'DELETE' : 'PUT', { content_id: item.id, ...(current === value ? {} : { value }) })
  }
  const refresh = () => { void profile.refetch(); void client.resetQueries({ queryKey: ['r1-feed'] }) }
  return <div className="r1-reader">
    <div className="feed-heading"><div><p className="r1-eyebrow">READING / 发现</p><h1>值得停下来读一读</h1><p>从具体内容出发，沿着来源继续深入。</p></div><button onClick={refresh} disabled={query.isFetching}>刷新</button></div>
    {query.data?.pages[0]?.preview && <p className="r1-notice" role="status">隔离技术预览 · 来源仍在观察，尚未正式发布。</p>}
    <div className="feed-controls"><div role="group" aria-label="阅读排序" className="r1-segment">{(['recommended', 'latest'] as const).map(value => <button key={value} aria-pressed={sort === value} disabled={profile.saving || !profile.data || !profile.online} onClick={() => void changeSort(value)}>{value === 'recommended' ? '推荐' : '最新'}</button>)}</div><Link to="/interests" onClick={rememberPosition}>我的关注 <span aria-hidden="true">↗</span></Link></div>
    <p className="r1-method">{sort === 'recommended' ? '根据已审核内容、当前价值和你的明确偏好排列；未设置关注也可浏览。' : '按有依据的原始发布时间排列，未知时间列后；抓取和导读更新不会顶到最新。'}</p>
    {profile.message && <p role="status" className="r1-notice">{profile.message}</p>}
    {!profile.online && <p role="status" className="r1-notice">网络不可用，反馈和关注暂不能保存；不会离线排队。</p>}
    {(profile.error || query.error) && <div role="alert" className="r1-notice"><p>{query.error instanceof ReaderError && query.error.status === 409 ? '内容或偏好已变化，请重新加载这份列表。' : '暂时无法读取内容，请检查登录和网络后重试。'}</p><button onClick={refresh}>重新加载</button></div>}
    {(profile.isPending || query.isPending) && !profile.error && <p role="status">正在读取内容…</p>}
    {!query.isPending && !query.error && !items.length && <section className="r1-empty"><span aria-hidden="true">◌</span><h2>暂时没有可发布的内容</h2><p>材料和卡片完成审核、来源获准发布后，会出现在这里。</p><p>关注设置可以先保存，阅读不会自动隐藏内容。</p><Link to="/interests">设置我的关注</Link></section>}
    <div className="r1-content-list">{items.map(item => {
      const selected = profile.data?.feedback.find(f => f.content_id === item.id)?.value
      return <article className="r1-content-card" key={item.id}>
        <div className="r1-overline"><span>{GENRES[item.card.genre] ?? '内容'}</span><span>{item.source_name}</span><time>{publication(item.metadata)}</time></div>
        <h2><Link to={`/reading/${item.id}`} onClick={rememberPosition} state={{ returnTo: location.pathname + location.search }}>{item.title}</Link></h2>
        <p className="r1-scope">{SCOPES[item.material_scope] ?? '材料范围待核对'}{item.metadata.publisher && item.metadata.publisher !== item.source_name ? ` · 发布方 ${item.metadata.publisher}` : ''}</p>
        <ul className="r1-claims">{item.card.claims.map((claim, index) => <li key={index}>{claim.text}</li>)}</ul>
        <div className="r1-card-footer"><div className="r1-tags">{item.card.domains.map(domain => <span key={domain}>{DOMAINS[domain] ?? domain}</span>)}</div><div className="r1-feedback" role="group" aria-label={`${item.title}的反馈`}><button disabled={profile.saving || !profile.online} aria-pressed={selected === 'interested'} onClick={() => void feedback(item, 'interested')}>感兴趣{selected === 'interested' ? ' · 撤销' : ''}</button><button disabled={profile.saving || !profile.online} aria-pressed={selected === 'not_interested'} onClick={() => void feedback(item, 'not_interested')}>不感兴趣{selected === 'not_interested' ? ' · 撤销' : ''}</button></div></div>
        <details className="r1-explanation"><summary>为什么看到这条</summary><p>阅读价值 {item.ranking.reading_value ?? 0} · 当前价值 {(item.ranking.current_value ?? 0).toFixed(2)} · 关注匹配 {item.ranking.interest ?? 0} · 明确反馈 {item.ranking.feedback ?? 0} · 相似反馈 {item.ranking.similar_feedback ?? 0} · 多样性 {item.ranking.diversity ?? 0}</p><p>阅读价值是系统的技术判断，与你的主观评分分开。一次“不感兴趣”不会屏蔽整个领域。</p><a href={safeHref(item.url)} target="_blank" rel="noopener noreferrer">查看原始来源 ↗</a></details>
      </article>
    })}</div>
    {query.hasNextPage && <button className="r1-more" disabled={query.isFetching || !!query.error} onClick={() => void query.fetchNextPage()}>{query.isFetchingNextPage ? '读取中…' : '继续阅读'}</button>}
  </div>
}
