import { Link } from 'react-router-dom'
import type { TopicClaim } from './api'

const VOICES: Record<string, string> = { reported: '报道转述', author: '作者观点', question: '问题', description: '内容简介' }

export default function TopicClaims({ claims, names = {}, returnTo, topicReturnTo, onNavigate }: { claims: TopicClaim[]; names?: Record<number, string>; returnTo: string; topicReturnTo?: string; onNavigate?: () => void }) {
  return <div className="r2-claims">{claims.map((claim, index) => <div className="r2-claim" key={index}>
    <p>{claim.text}</p><p className="r1-method">{claim.attribution}</p>
    {claim.limitations.length > 0 && <ul className="r2-limits">{claim.limitations.map((limit, i) => <li key={i}>{limit}</li>)}</ul>}
    <details className="r1-explanation"><summary>核对出处与原文依据 · {claim.evidence.length} 处</summary>{claim.evidence.map((ref, i) => <div key={i}><Link to={`/reading/${ref.article_id}`} state={{ returnTo, topicReturnTo }} onClick={onNavigate}>{names[ref.article_id] ?? `来源内容 #${ref.article_id}`}</Link><span className="r1-method"> · {VOICES[ref.voice] ?? '原材料'} · 段落 {ref.paragraph + 1}</span><blockquote>{ref.quote}</blockquote></div>)}</details>
  </div>)}</div>
}
