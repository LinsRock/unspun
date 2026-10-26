import { useEffect, useRef } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getTopic } from './api'
import { useReader } from './profile'
import { DOMAINS, publication, SCOPES } from './presentation'
import { ReaderSkeleton } from './LoadingState'
import ReaderNotice from './ReaderNotice'
import TargetActions from './TargetActions'
import TopicClaims from './TopicClaims'
import { topicTime } from './presentation'
import { readingPositions, readingReturn } from './navigation'
import { safeHref } from '../links'
import './reader.css'
import './topics.css'

const RELATIONS: Record<string, string> = { report: '相关报道', reprint: '转载', opinion: '观点', explanation: '解释', background: '背景', evidence: '依据' }
export default function TopicPage() {
  const id = useParams().id ?? ''; const location = useLocation(); const profile = useReader()
  const query = useQuery({ queryKey: ['r2-topic', id], queryFn: ({ signal }) => getTopic(id, signal), retry: false, staleTime: 0 })
  const positionKey = `topic:${id}:${query.data?.version}`
  const restored = useRef('')
  useEffect(() => {
    if (!query.data || query.error || query.isFetching || restored.current === positionKey) return
    const frame = requestAnimationFrame(() => { restored.current = positionKey; window.scrollTo(0, readingPositions.get(positionKey) ?? 0) })
    return () => cancelAnimationFrame(frame)
  }, [positionKey, query.data, query.error, query.isFetching])
  const remember = () => readingPositions.set(positionKey, window.scrollY)
  const state = location.state as { returnTo?: string } | null
  const returnTo = readingReturn(state?.returnTo)
  const back = <Link className="r1-back" to={returnTo}>← 返回阅读列表</Link>
  if (query.isPending) return <div className="r1-reader r1-detail">{back}<ReaderSkeleton layout="detail" label="正在加载话题" /></div>
  if (query.error || !query.data) return <section className="r1-reader r1-detail">{back}<h1>话题暂不可读</h1><ReaderNotice error={query.error} retry={() => void query.refetch()} /><p>当前材料或发布状态可能已变化。已有关注仍可在“我的关注”中取消。</p><Link to="/interests">管理我的关注</Link></section>
  const item = query.data
  const names = Object.fromEntries(item.related.map(content => [content.id, `${content.source_name} · ${content.title}`]))
  return <article className="r1-reader r1-detail r2-topic-detail">{back}
    {item.engineering_preview && <p className="r1-notice">工程预览 · 真实材料上的人工整理示例，未经过真实生成和审核质量验收；不代表生产发布。</p>}
    <header className="r1-detail-header"><p className="r1-eyebrow">话题 / {item.domains.map(d => DOMAINS[d] ?? d).join(' · ')}</p><h1>{item.title}</h1><p>从概况了解材料，再沿着出处深入阅读。</p><TargetActions target={{ type: 'topic', id }} title={item.title} profile={profile} /></header>
    {profile.message && <p className="r1-notice" role="status">{profile.message}</p>}
    {profile.error && <ReaderNotice error={profile.error} retry={() => void profile.refetch()} />}
    {!profile.online && <p role="status" className="r1-notice">当前离线，关注和反馈暂不能保存。</p>}
    <nav className="r2-section-nav" aria-label="话题章节"><a href="#overview">概况</a><a href="#guide">导读</a><a href="#progress">实质进展</a><a href="#context">背景与观点</a><a href="#related">相关内容</a></nav>
    <section id="overview" className="r1-keypoints"><h2>话题概况</h2>{item.overview.length ? <TopicClaims claims={item.overview} names={names} returnTo={location.pathname} topicReturnTo={returnTo} onNavigate={remember} /> : <p>现有材料不足以形成概况，可直接阅读下方相关内容。</p>}</section>
    <section id="guide" className="r1-guide"><h2>AI 导读{item.engineering_preview ? ' · 工程示例' : ''}</h2>{item.guide.length ? <TopicClaims claims={item.guide} names={names} returnTo={location.pathname} topicReturnTo={returnTo} onNavigate={remember} /> : <p>尚无可用导读，原材料仍可阅读。</p>}</section>
    <section id="progress" className="r2-topic-section"><h2>实质进展</h2><p className="r1-method">发生与报道时间分别保留；新增来源、转载或导读更新不视为进展。</p>{!item.progress.length && <p>现有材料尚不能支持实质进展。</p>}{item.progress.map((progress, i) => <div key={progress.progress_key ?? i} className="r2-progress"><h3>{progress.classification === 'discussion_focus' ? '讨论焦点变化' : '实质进展'}</h3><p className="r1-method">{topicTime(progress.occurred, 'occurred')} · {topicTime(progress.reported, 'reported')}</p>{(progress.occurred.basis || progress.reported.basis) && <details><summary>时间依据</summary><p>{progress.occurred.basis}</p><p>{progress.reported.basis}</p></details>}<TopicClaims claims={[progress]} names={names} returnTo={location.pathname} topicReturnTo={returnTo} onNavigate={remember} /></div>)}</section>
    <section id="context" className="r2-topic-section"><h2>背景与观点</h2>{!item.context.length && <p>暂无单独整理的背景或观点；相关内容保留各自的阅读价值。</p>}{item.context.map((entry, i) => <div key={i}><h3>{entry.classification === 'opinion' ? '作者观点' : '背景材料'}</h3><TopicClaims claims={[entry]} names={names} returnTo={location.pathname} topicReturnTo={returnTo} onNavigate={remember} /></div>)}</section>
    <section id="related" className="r2-topic-section"><h2>相关内容与原文</h2>{item.related.map(content => <article className="r2-related" key={content.id}><p className="r1-method">{RELATIONS[content.relation] ?? '相关材料'} · {content.source_name} · {publication(content.metadata)}</p><h3><Link to={`/reading/${content.id}`} state={{ returnTo: location.pathname, topicReturnTo: returnTo }} onClick={remember}>{content.title}</Link></h3><p>{SCOPES[content.material_scope] ?? '范围待核对'}{content.card.model_input_truncated ? '；整理只使用了材料前一部分。' : ''}</p><a href={safeHref(content.url)} target="_blank" rel="noopener noreferrer">打开原文 ↗</a></article>)}</section>
  </article>
}
