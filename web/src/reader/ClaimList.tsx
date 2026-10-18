import type { Claim } from './api'

const ATTRIBUTIONS = [
  { prefix: '文中称：', voice: 'reported', label: '原文陈述' },
  { prefix: '文中观点：', voice: 'author', label: '作者观点' },
  { prefix: '作者评价：', voice: 'author', label: '作者评价' },
  { prefix: '文中分析：', voice: 'author', label: '原文分析' },
  { prefix: '文中解释：', voice: 'author', label: '原文解释' },
  { prefix: '简介中提到：', voice: 'description', label: '简介内容' },
  { prefix: '问题背景中提到：', voice: 'question', label: '问题背景' },
]

export default function ClaimList({ claims, label }: { claims: Claim[]; label?: string }) {
  // Only share an exact, uniform attribution. Mixed voices stay verbatim.
  const attribution = claims.length ? ATTRIBUTIONS.find(({ prefix, voice }) =>
    claims.every(claim => claim.voice === voice && claim.text.startsWith(prefix) && claim.text.length > prefix.length),
  ) : undefined
  const heading = [label, attribution?.label].filter(Boolean).join(' · ')
  return <>
    {heading && <p className="r1-summary-label">{heading}</p>}
    <ul className="r1-claims">{claims.map((claim, index) => <li key={index}>{attribution ? claim.text.slice(attribution.prefix.length) : claim.text}</li>)}</ul>
  </>
}
