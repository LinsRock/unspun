import { useState } from 'react'

import type { ArticleOut, EventOut, FeedSort, ViewpointOut } from './api'
import { safeHref } from './links'
import SectionHeading from './SectionHeading'
import EvidenceQuote from './EvidenceQuote'
import { relationLabel } from './relationLabels'
import { contentQualityLabel, readingReasonLabel } from './contentQualityLabel'

function ScoreBar({
  label,
  value,
  sub = false,
}: {
  label: string
  value: number
  sub?: boolean
}) {
  return (
    <div
      className={`flex items-center gap-2 text-[11.5px] text-ink-3 ${sub ? 'pl-3 opacity-80' : ''}`}
    >
      <span className="w-14 shrink-0">{label}</span>
      <div className="h-[5px] flex-1 overflow-hidden rounded-[3px] bg-line">
        <div
          className={`h-full rounded-[3px] ${sub ? 'bg-ink-4' : 'bg-accent'}`}
          style={{ width: `${Math.min(100, Math.max(0, value))}%` }}
        />
      </div>
      <span className="w-[26px] shrink-0 text-right font-mono tabular-nums">
        {Math.round(value)}
      </span>
    </div>
  )
}

// Claims joined with their source articles; claims whose article_id is not in
// this event are dropped so a statement can never point at a foreign source
// (the API filters these too — this is the second layer, like safeHref).
function resolveClaims(viewpoint: ViewpointOut, articles: ArticleOut[]) {
  const byId = new Map(articles.map((a) => [a.id, a]))
  return viewpoint.claims.flatMap((claim, index) => {
    const article = byId.get(claim.article_id)
    return article ? [{ claim, article, index }] : []
  })
}

type ResolvedClaim = ReturnType<typeof resolveClaims>[number]

function ClaimLink({ article }: { article: ArticleOut }) {
  const href = safeHref(article.url)
  const label = `↗ ${article.title_zh ?? article.title}`
  if (href == null) {
    return (
      <span className="mt-2 block truncate text-[11.5px] text-ink-4">
        {label}
      </span>
    )
  }
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="mt-2 block truncate text-[11.5px] text-accent-ink hover:underline"
    >
      {label}
    </a>
  )
}

function ViewpointSection({
  viewpoint,
  claims,
}: {
  viewpoint: ViewpointOut
  claims: ResolvedClaim[]
}) {
  const indexToName = new Map(
    claims.map((c) => [c.index, c.article.source_name]),
  )
  const disagreements = viewpoint.disagreements
    .map((d) => ({
      point: d.point,
      kind: d.kind,
      refs: d.claim_indexes.flatMap((i) => indexToName.get(i) ?? []),
    }))
    .filter((d) => d.refs.length >= 2)
  return (
    <div className="mt-3">
      <SectionHeading>各源说法 · {claims.length}</SectionHeading>
      <div className="mt-2.5 grid gap-2.5 [grid-template-columns:repeat(auto-fit,minmax(240px,1fr))]">
        {claims.map(({ claim, article }) => (
          <div
            key={claim.article_id}
            className="min-w-0 rounded-card border border-line px-3.5 py-3"
          >
            <div className="border-b border-line pb-2 text-[13px] font-bold">
              {article.source_name}
            </div>
            <p className="mt-2 text-[13px] leading-[1.7] text-ink-2">
              {claim.claim}
            </p>
            <EvidenceQuote
              quote={claim.evidence_quote}
              limited={article.content_quality === 'limited'}
            />
            <ClaimLink article={article} />
          </div>
        ))}
      </div>
      {disagreements.length > 0 && (
        <div className="mt-4">
          <SectionHeading>报道差异 · {disagreements.length}</SectionHeading>
          <ul>
            {disagreements.map((d, i) => (
              // Points can repeat verbatim; position is the stable identity.
              // eslint-disable-next-line react/no-array-index-key
              <li
                key={i}
                className="flex gap-2.5 border-b border-line py-2.5 last:border-b-0"
              >
                <span className="shrink-0 pt-0.5 font-mono text-xs font-bold text-hot">
                  {String(i + 1).padStart(2, '0')}
                </span>
                <div className="min-w-0">
                  <p className="mb-1 text-[11.5px] font-semibold text-ink-3">
                    {relationLabel(d.kind)}
                  </p>
                  <p className="text-[13.5px] leading-relaxed text-ink-2">
                    {d.point}
                  </p>
                  <div className="mt-0.5 text-[11.5px] text-ink-4">
                    {d.refs.join(' · ')}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

    </div>
  )
}

function reportTime(event: EventOut): string {
  if (event.earliest_reported_precision === 'date' && event.earliest_reported_date) return `${event.earliest_reported_date}（仅日期）`
  if (!event.earliest_reported_at) return '报道时间未知'
  return new Date(event.earliest_reported_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
}

export default function EventCard({ event, sort = 'newest' }: { event: EventOut; sort?: FeedSort }) {
  const [showEvidence, setShowEvidence] = useState(false)
  const [showBreakdown, setShowBreakdown] = useState(false)
  const [showViewpoint, setShowViewpoint] = useState(false)
  const [showMore, setShowMore] = useState(false)
  const facts = event.facts ?? []
  const visibleFacts = showMore ? facts : facts.slice(0, 2)
  const byId = new Map(event.articles.map((article) => [article.id, article]))
  const sourceNames = [...new Set(event.articles.filter((article) => !event.evidence_article_ids?.length || event.evidence_article_ids.includes(article.id)).map((article) => article.source_name))]
  const kind = ({ brief: '快讯', report: '报道摘要', aggregation: '多篇综合', lead: '消息线索' } as Record<string, string>)[event.content_kind ?? ''] ?? '事件'
  const breakdown = event.score_breakdown
  const viewpoint = event.viewpoint
  const claims = viewpoint ? resolveClaims(viewpoint, event.articles) : []
  const hasViewpoint = claims.length >= 2 && viewpoint?.status !== 'review_limited'
  const legacySummary = !facts.length && event.summary_zh !== event.title ? event.summary_zh : null

  return <article className="reading-event" aria-labelledby={`event-${event.id}`}>
    <div className="event-overline">
      <span className="event-kind">{kind}</span>
      <span>{event.earliest_reported_precision === 'unknown' || !event.earliest_reported_precision ? '报道时间未知' : `最早报道 ${reportTime(event)}`}</span>
      {sort === 'important' && event.public_impact_boosted && <span className="text-hot">紧急公共影响</span>}
    </div>
    <h2 id={`event-${event.id}`} className="event-headline">{event.title ?? '待整理事件'}</h2>
    {facts.length > 0 && <ul className="event-facts">{visibleFacts.map((fact, index) => <li key={`${fact.article_id}-${index}`}><span>{fact.text}</span><button type="button" onClick={() => setShowEvidence(true)} aria-label={`查看第 ${index + 1} 条信息依据`} className="fact-reference">[{index + 1}]</button></li>)}</ul>}
    {legacySummary && <p className="event-legacy-summary">{legacySummary}</p>}
    {facts.length > 2 && <button type="button" className="event-more" aria-expanded={showMore} onClick={() => setShowMore(!showMore)}>{showMore ? '收起细节' : `展开另外 ${facts.length - 2} 条信息`}</button>}
    <div className="event-footer">
      <button type="button" className="event-evidence-trigger" aria-expanded={showEvidence} onClick={() => setShowEvidence(!showEvidence)}>
        <span className="event-source-mark" aria-hidden="true">↗</span>
        <span>{sourceNames.slice(0, 2).join(' · ') || '来源材料'}{sourceNames.length > 2 ? ` 等 ${sourceNames.length} 个来源` : ''}</span>
        <span className="event-source-count">查看依据 · {event.articles.length} 篇</span>
      </button>
      <div className="event-actions">
        {hasViewpoint && <button type="button" aria-expanded={showViewpoint} onClick={() => setShowViewpoint(!showViewpoint)}>观点对比</button>}
        {breakdown && <button type="button" aria-expanded={showBreakdown} onClick={() => setShowBreakdown(!showBreakdown)}>关注依据</button>}
      </div>
    </div>
    {sort === 'hot' && event.heat != null && <p className="event-footnote">窗口内 {event.active_publishers ?? 0} 家媒体有报道活动；不代表独立验证。</p>}
    {showBreakdown && breakdown && <section className="event-expanded" aria-label="关注依据">
      <h3>为何进入关注范围</h3>
      <p className="event-footnote">以下是排序参考，不代表事实已获独立验证。</p>
      {breakdown.importance?.reason && <p className="mt-2 text-sm text-ink-2">{breakdown.importance.reason}</p>}
      <div className="mt-4 grid gap-2">
        {breakdown.importance && <ScoreBar label="重要性" value={breakdown.importance.score} />}
        {breakdown.objective && <><ScoreBar label="来源质量" value={breakdown.objective.source_quality} /><ScoreBar label="报道广度" value={breakdown.objective.breadth} /><ScoreBar label="增长速度" value={breakdown.objective.growth} /></>}
      </div>
      <p className="event-footnote">综合分 {event.score_final == null ? '尚未评分' : Math.round(event.score_final)} · 摘要质量由发布审核单独判断</p>
    </section>}
    {showEvidence && <section className="event-expanded" aria-label="事件依据">
      <h3>信息从哪里来</h3>
      <p className="event-footnote">原文摘录保留原语言；报道篇数不等于独立证据数。</p>
      {facts.map((fact, index) => <div className="event-citation" key={`${fact.article_id}-${index}`}><span className="citation-number">{String(index + 1).padStart(2, '0')}</span><div><p>{fact.text}</p><blockquote lang="und">{fact.quote}</blockquote><a href={safeHref(byId.get(fact.article_id)?.url ?? '')} target="_blank" rel="noreferrer">{byId.get(fact.article_id)?.source_name ?? '原始材料'} ↗</a></div></div>)}
      <h4 className="mt-5 text-xs font-semibold text-ink-3">来源材料 · {event.articles.length} 篇</h4>
      <ul className="event-materials">{event.articles.map((article) => <li key={article.id}>
        <a href={safeHref(article.url)} target="_blank" rel="noreferrer"><strong>{article.source_name}</strong><span>{article.title_zh ?? article.title} ↗</span></a>
        {article.content_basis && <p>{({ original: '材料来自原文正文', feed_summary: '材料来自 RSS 导语', unknown: '正文来源未确认' } as Record<string, string>)[article.content_basis]}</p>}
        {article.reading_status === 'ready' && event.evidence_article_ids && !event.evidence_article_ids.includes(article.id) && <p>同组相关材料，尚未确认共同事实，未纳入上述摘要。</p>}
        {article.reading_status === 'withheld' ? <p>{readingReasonLabel(article.reading_reason)}；未用于上述摘要。</p> : contentQualityLabel(article.content_quality) && <p>{contentQualityLabel(article.content_quality)}</p>}
      </li>)}</ul>
      {((event.missing_time_count ?? 0) + (event.invalid_time_count ?? 0) > 0) && <p className="event-footnote">部分来源报道时间缺失或异常。</p>}
    </section>}
    {viewpoint?.status === 'review_limited' && showEvidence && <p className="event-footnote">观点对比审核因预算延期；当前摘要独立通过发布审核。</p>}
    {showViewpoint && hasViewpoint && viewpoint && <ViewpointSection viewpoint={viewpoint} claims={claims} />}
  </article>
}
