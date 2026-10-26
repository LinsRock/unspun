import { useEffect, useLayoutEffect, useRef } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query'
import { getHybridFeed } from './api'
import type { ReaderState, Sort } from './api'
import { useReader } from './profile'
import { DOMAINS, GENRES, SCOPES, SOURCE_NAMES } from './presentation'
import ClaimList from './ClaimList'
import { LoadingStatus, ReaderSkeleton } from './LoadingState'
import ReaderNotice from './ReaderNotice'
import TargetActions from './TargetActions'
import TopicClaims from './TopicClaims'
import { topicTime } from './presentation'
import { readingPositions } from './navigation'
import { safeHref } from '../links'
import './reader.css'
import './topics.css'

export default function HybridPage() {
  const profile = useReader(); const client = useQueryClient(); const location = useLocation()
  const [params, setParams] = useSearchParams()
  const sort: Sort = params.get('sort') === 'latest' ? 'latest' : params.get('sort') === 'recommended' ? 'recommended' : profile.data?.sort ?? 'recommended'
  const query = useInfiniteQuery({ queryKey: ['r2-feed', sort, profile.data?.version], enabled: !!profile.data && !profile.error, queryFn: ({ pageParam, signal }) => getHybridFeed(sort, pageParam, signal), initialPageParam: undefined as string | undefined, getNextPageParam: page => page.next_cursor ?? undefined, retry: false, refetchOnWindowFocus: false, staleTime: 60_000 })
  const key = `${sort}:${profile.data?.version}:${query.data?.pages[0]?.snapshot}`
  const restored = useRef('')
  useEffect(() => {
    if (!query.data || query.error || query.isFetching || restored.current === key) return
    const frame = requestAnimationFrame(() => { restored.current = key; window.scrollTo(0, readingPositions.get(key) ?? 0) })
    return () => cancelAnimationFrame(frame)
  }, [query.data, query.error, query.isFetching, key])
  useLayoutEffect(() => () => { if (restored.current === key) readingPositions.set(key, window.scrollY) }, [key])
  const remember = () => readingPositions.set(key, window.scrollY)
  const returnTo = location.pathname + location.search
  const seen = new Set<string>()
  const items = query.error || profile.error ? [] : query.data?.pages.flatMap(p => p.items).filter(item => { const id = `${item.type}:${item.id}`; if (seen.has(id)) return false; seen.add(id); return true }) ?? []
  async function changeSort(next: Sort) {
    if (next === sort) return
    remember()
    const saved = await profile.change('/api/reader-preferences', 'PUT', { sort: next }, { announceSuccess: false })
    const current = client.getQueryData<ReaderState>(['r1-reader'])
    setParams({ sort: saved ? next : current?.sort ?? sort })
  }
  const refresh = () => { readingPositions.delete(key); restored.current = ''; void profile.refetch(); void client.resetQueries({ queryKey: ['r2-feed'] }) }
  return <div className="r1-reader">
    <div className="feed-heading"><div><p className="r1-eyebrow">DISCOVER / 发现</p><h1>跟上变化，发现好内容</h1><p>一起看话题的进展，也为值得读的文章留个位置。</p></div><button disabled={query.isFetching} onClick={refresh} aria-busy={query.isFetching}>{query.isFetching ? <LoadingStatus>刷新中</LoadingStatus> : '刷新'}</button></div>
    {query.data?.pages[0]?.engineering_preview && <p className="r1-notice" role="status">工程预览 · 复用已有真实文章；话题及整理示例未经真实模型质量验收，不代表生产发布。</p>}
    <div className="feed-controls"><div className="r1-segment" role="group" aria-label="混合阅读排序">{(['recommended', 'latest'] as const).map(value => <button key={value} aria-pressed={sort === value} disabled={profile.saving || !profile.data || !!profile.error || !profile.online} onClick={() => void changeSort(value)}>{value === 'recommended' ? '推荐' : '最新'}</button>)}</div><Link to="/interests" onClick={remember}>我的关注 ↗</Link></div>
    <p className="r1-method">{sort === 'recommended' ? '结合内容价值与明确偏好；尚未设置关注也可以浏览。' : '按内容原发或话题实质进展的有据时间排列；未知列后，转载和导读更新不会置顶。'}</p>
    {profile.message && <p className="r1-notice" role="status">{profile.message}</p>}
    {!profile.online && <p className="r1-notice" role="status">网络不可用，关注和反馈暂不能保存；不会离线排队。</p>}
    {(profile.error || query.error) && <ReaderNotice error={profile.error || query.error} retry={refresh} />}
    {(profile.isPending || query.isPending) && !profile.error && !query.error && <ReaderSkeleton />}
    {!profile.isPending && !query.isPending && !profile.error && !query.error && !items.length && <section className="r1-empty"><h2>暂时没有可公开的话题或内容</h2><p>已有阅读入口和关注设置仍可使用。</p><Link to="/reading">浏览独立内容</Link></section>}
    <div className="r1-content-list" aria-busy={query.isFetching}>{items.map(item => <article key={`${item.type}:${item.id}`} className={`r1-content-card ${item.type === 'topic' ? 'r2-topic-card' : ''} ${item.presentation === 'reference' ? 'r2-reference' : ''}`}>
      <div className="r1-overline"><span>{item.type === 'topic' ? '话题' : GENRES[item.content?.card?.genre ?? ''] ?? '内容'}</span><span>{item.content?.source_name ?? [...new Set(item.topic?.material_scope.map(m => SOURCE_NAMES[m.source_id] ?? m.source_id))].join('、')}</span><time>{topicTime(item.time)}</time></div>
      <h2><Link to={item.type === 'topic' ? `/topics/${item.id}` : `/reading/${item.id}`} state={{ returnTo }} onClick={remember}>{item.title}</Link></h2>
      {item.topic?.engineering_preview && <p className="r2-preview-label">工程话题与整理示例 · 未经真实模型验收</p>}
      {item.type === 'topic' ? <TopicClaims claims={item.topic?.overview.slice(0, 1) ?? []} returnTo={returnTo} onNavigate={remember} /> : item.presentation === 'reference' ? <p className="r1-method">重复概况已在本页话题中收起，独立原文仍可阅读。{item.reference_to.map(id => <Link key={id} to={`/topics/${id}`} state={{ returnTo }} onClick={remember}>查看相关话题 ↗ </Link>)}</p> : item.content?.card && <><p className="r1-scope">{SCOPES[item.content.material_scope] ?? '材料范围待核对'}</p><ClaimList claims={item.content.card.claims} label="AI 要点" /></>}
      <div className="r1-card-footer"><div className="r1-tags">{item.content?.card?.domains.map(domain => <span key={domain}>{DOMAINS[domain] ?? domain}</span>)}</div><TargetActions target={item.type === 'topic' ? { type: 'topic', id: item.id } : { type: 'content', id: Number(item.id) }} title={item.title} profile={profile} /></div>
      <details className="r1-explanation"><summary>为什么看到这条</summary><p>{sort === 'latest' ? '本页按有据时间排序，偏好不会覆盖时间顺序。' : item.type === 'topic' ? '话题进入可读候选，结合你的明确偏好排列。' : '内容的阅读价值、当前价值与明确偏好共同参与推荐。'}</p><p>{item.ranking.followed ? '你已关注此话题。' : ''}{(item.ranking.interest ?? 0) > 0 ? '与你保存的关注匹配。' : ''}{item.ranking.feedback_value === 'interested' ? '你对此话题表达过感兴趣。' : item.ranking.feedback_value === 'not_interested' ? '你的不感兴趣反馈会降低推荐权重，仍保留阅读入口。' : ''}</p><p>关注匹配 {item.ranking.interest ?? 0} · 话题关注 {item.ranking.follow_boost ?? 0} · 反馈 {item.ranking.feedback ?? 0} · 多样性 {item.ranking.diversity ?? 0}</p><p>{item.ranking.important ? '有材料支持的重要性信号。' : '暂无已核验的重要性信号。'}{item.ranking.public_attention ? '有直接公共关注观测。' : '暂无直接公共关注观测。'}</p>{item.content && <a href={safeHref(item.content.url)} target="_blank" rel="noopener noreferrer">打开原文 ↗</a>}</details>
    </article>)}</div>
    {query.hasNextPage && !query.error && <button className="r1-more" disabled={query.isFetching} aria-busy={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>{query.isFetchingNextPage ? <LoadingStatus>加载更多</LoadingStatus> : '继续阅读'}</button>}
  </div>
}
