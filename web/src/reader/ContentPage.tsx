import { useEffect, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getDetail, ReaderError, request } from './api'
import type { GuideState, InterestTarget } from './api'
import { useReader } from './profile'
import { GENRES, guideMessage, publication, SCOPES, TIME_LABELS } from './presentation'
import { safeHref } from '../links'
import ClaimList from './ClaimList'
import { LoadingStatus, ReaderSkeleton } from './LoadingState'
import './reader.css'

export default function ContentPage() {
  const id = Number(useParams().id); const location = useLocation(); const client = useQueryClient(); const profile = useReader()
  const [guideError, setGuideError] = useState('')
  const query = useQuery({ queryKey: ['r1-content', id], enabled: Number.isSafeInteger(id) && id > 0, queryFn: ({ signal }) => getDetail(id, signal), retry: false, refetchInterval: query => ['pending', 'generating', 'review_pending'].includes(query.state.data?.guide.status ?? '') ? 5000 : query.state.data?.guide.status === 'budget_deferred' ? 60_000 : false })
  const guide = useMutation({ retry: false, mutationFn: () => request<GuideState>(`/api/contents/${id}/guide`, { method: 'POST' }), onSuccess: () => { void client.invalidateQueries({ queryKey: ['r1-content', id] }) }, onError: () => setGuideError('暂未确认导读请求结果，请刷新状态后核对。重复请求不会生成第二份任务。') })
  useEffect(() => { window.scrollTo(0, 0) }, [id])
  const item = query.data
  const state = location.state as { returnTo?: string } | null
  const returnTo = state?.returnTo?.startsWith('/reading?') ? state.returnTo : '/reading'
  async function follow(target: InterestTarget) { await profile.change('/api/interests', 'PUT', { target }) }
  if (query.isPending && query.fetchStatus !== 'idle') return <div className="r1-reader r1-detail"><Link className="r1-back" to={returnTo}>← 返回阅读列表</Link><ReaderSkeleton layout="detail" label="正在加载来源材料" /></div>
  if (!item) return <section className="r1-reader r1-empty"><h1>{query.error instanceof ReaderError && query.error.status === 404 ? '这条内容尚无可发布的当前版本' : '暂时无法打开内容'}</h1><p>材料更新、审核状态或发布范围可能已变化。</p><Link to={returnTo}>返回阅读列表</Link></section>
  const short = ['preview', 'feed_lead', 'question_background', 'media_description'].includes(item.material_scope)
  return <article className="r1-reader r1-detail">
    <Link className="r1-back" to={returnTo}>← 返回阅读列表</Link>
    {item.preview && <p className="r1-notice">隔离技术预览 · 尚未正式发布</p>}
    <header className="r1-detail-header"><p className="r1-eyebrow">{GENRES[item.card.genre] ?? '内容'} / {item.source_name}</p><h1>{item.title}</h1><p>{publication(item.metadata)}</p><p>{item.metadata.publisher ? `发布方：${item.metadata.publisher}` : '发布方尚未核实'}</p><div className="r1-byline">{item.metadata.authors.map((author, index) => <span key={index}>{author.role === 'reporter' ? '记者' : author.role === 'editor' ? '编辑' : '署名'}：{author.name} <button disabled={profile.saving || !profile.online || !profile.data || !(author.platform ?? item.metadata.platform)} onClick={() => void follow({ kind: 'author', value: author.name, platform: author.platform ?? item.metadata.platform ?? undefined, author_id: author.platform_id })}>关注署名</button></span>)}</div></header>
    <div className="r1-source-actions"><a href={safeHref(item.url)} target="_blank" rel="noopener noreferrer">打开原文 ↗</a><button disabled={profile.saving || !profile.online || !profile.data} onClick={() => void follow({ kind: 'source', value: item.source_id })}>关注这个来源</button></div>
    {profile.message && <p role="status" className="r1-notice">{profile.message}</p>}
    <p className="r1-scope-banner">{SCOPES[item.material_scope] ?? '材料范围待核对'}{short ? '。以下只呈现实际取得的材料。' : '。不将未取得的部分称为全文。'}</p>
    {item.material_scope === 'question_background' && <p className="r1-method">这是问题线索，尚未取得回答，不代表社区结论。</p>}
    {item.material_scope === 'media_description' && <p className="r1-method">仅整理公开简介；未观看或收听，不提供观后结论、转录或时间点。</p>}
    {item.requested_alias_id && <p className="r1-method">此入口指向同一内容的规范版本，重复出处仍保留在来源记录中。</p>}
    <section className="r1-keypoints" aria-label="已审核要点"><h2>已审核要点</h2><ClaimList claims={item.card.claims} /></section>
    <section className="r1-source-body" aria-label="来源材料"><div className="r1-section-heading"><h2>{short ? '已取得的材料' : '站内阅读'}</h2><span>来源材料 · 非 AI 扩写</span></div>{item.material.paragraphs.map((paragraph, index) => paragraph.kind === 'heading' ? <h3 key={index}>{paragraph.text}</h3> : paragraph.kind === 'quote' ? <blockquote key={index}>{paragraph.text}</blockquote> : <p key={index}>{paragraph.text}</p>)}</section>
    <section className="r1-guide" aria-label="AI 导读"><div className="r1-section-heading"><h2>AI 导读</h2><span>与来源原文分开呈现</span></div>{item.guide.status === 'ready' && item.guide.payload ? item.guide.payload.sections.map((section, index) => <section key={index}><h3>{section.heading}</h3><ul className="r1-claims">{section.claims.map((claim, index) => <li key={index}>{claim.text}<details><summary>核对原文依据</summary><blockquote>{claim.quote}</blockquote></details></li>)}</ul></section>) : ['pending', 'generating', 'review_pending'].includes(item.guide.status) ? <div className="r1-guide-progress"><LoadingStatus>{guideMessage(item.guide.status, item.guide.reason)}</LoadingStatus></div> : <p role="status">{guideMessage(item.guide.status, item.guide.reason)}</p>}{item.guide.requestable && <button disabled={guide.isPending || !profile.online} aria-busy={guide.isPending} onClick={() => { setGuideError(''); guide.mutate() }}>{guide.isPending ? <LoadingStatus>正在提交请求</LoadingStatus> : '按需生成导读'}</button>}{guideError && <p role="alert">{guideError}</p>}</section>
    <details className="r1-provenance"><summary>来源、日期与材料范围</summary><p>原始标题：{item.original_title}</p>{item.metadata.times.map((time, index) => <p key={index}>{TIME_LABELS[time.kind] ?? time.kind}：{time.precision === 'date' ? `${time.on}（仅日期）` : time.at ? new Date(time.at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) : '未知'}{time.basis ? ` · 依据 ${time.basis}` : ''}</p>)}<p>材料获取：{new Date(item.material.retrieved_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}。此时间不代替原始发布。</p><p>范围：{SCOPES[item.material_scope]}{item.card.model_input_truncated ? '；AI 整理只使用了材料的前一部分。' : ''}</p>{item.metadata.original_url && <p><a href={safeHref(item.metadata.original_url)} target="_blank" rel="noopener noreferrer">{item.material_scope === 'editorial_edition' ? '原回答入口（未取得正文）' : '来源注明的原始入口'} ↗</a></p>}{item.metadata.media_url && <p><a href={safeHref(item.metadata.media_url)} target="_blank" rel="noopener noreferrer">原始媒体入口 ↗</a></p>}</details>
  </article>
}
