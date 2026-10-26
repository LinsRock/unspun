import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import type { InterestTarget } from './api'
import { useReader } from './profile'
import { DOMAINS, PLATFORM_NAMES, resourceValue, SOURCE_NAMES } from './presentation'
import { ReaderSkeleton } from './LoadingState'
import FollowedTopic from './FollowedTopic'
import TargetActions from './TargetActions'
import ReaderNotice from './ReaderNotice'
import './reader.css'
import './topics.css'

const KIND_LABELS: Record<string, string> = { domain: '领域', term: '主题词', source: '来源', author: '作者／署名' }
export default function InterestsPage() {
  const profile = useReader()
  const [kind, setKind] = useState<'term' | 'source' | 'author'>('term'); const [value, setValue] = useState(''); const [platform, setPlatform] = useState('')
  const unavailable = !profile.data || profile.saving || !profile.online || !!profile.error
  async function add(event: FormEvent) {
    event.preventDefault()
    if (!value.trim() || kind === 'author' && !platform.trim()) return
    const target: InterestTarget = { kind, value: kind === 'source' ? resourceValue(value.trim(), SOURCE_NAMES) : value.trim(), ...(kind === 'author' ? { platform: resourceValue(platform.trim(), PLATFORM_NAMES) } : {}) }
    if (await profile.change('/api/interests', 'PUT', { target })) setValue('')
  }
  async function domain(value: string) {
    const current = profile.data?.interests.find(i => i.target.kind === 'domain' && i.target.value === value)
    await profile.change('/api/interests', current ? 'DELETE' : 'PUT', { target: { kind: 'domain', value } })
  }
  if (profile.isPending) return <div className="r1-reader"><div className="feed-heading"><h1>我的关注</h1><Link to={profile.topics ? "/discover" : "/reading"}>返回阅读</Link></div>{!profile.online && <p role="status" className="r1-notice">当前离线，无法读取关注设置，请联网后重试。</p>}<ReaderSkeleton layout="interests" label="正在加载关注设置" /></div>
  return <div className="r1-reader"><div className="feed-heading"><div><p className="r1-eyebrow">YOUR INTERESTS</p><h1>我的关注</h1><p>从已有内容中优先发现感兴趣的方向，随时调整。</p></div><Link to={profile.topics ? "/discover" : "/reading"}>返回阅读</Link></div>
    {profile.message && <p role="status" className="r1-notice">{profile.message}</p>}
    {!profile.online && <p role="status" className="r1-notice">当前离线，无法保存；不会把操作排队到下次联网。</p>}
    {profile.error && <ReaderNotice error={profile.error} retry={() => void profile.refetch()} />}
    {profile.topics && <section className="r1-interest-section"><h2>话题关注与反馈</h2><p>关注、感兴趣和不感兴趣分别保存，随时修改或撤销。主题词不会自动成为话题订阅。</p>{!profile.data?.topic_preferences?.length && <p>尚未保存话题偏好。<Link to="/discover">去发现话题</Link></p>}{profile.data?.topic_preferences?.map(preference => <FollowedTopic key={preference.target.id} preference={preference} profile={profile} />)}</section>}
    <section className="r1-interest-section"><h2>关注领域</h2><p>不选择也有默认推荐；单次“不感兴趣”不会屏蔽整个领域。</p><div className="r1-domain-grid">{Object.entries(DOMAINS).map(([key, label]) => <button key={key} aria-pressed={!!profile.data?.interests.some(i => i.target.kind === 'domain' && i.target.value === key)} disabled={unavailable} onClick={() => void domain(key)}>{label}<span aria-hidden="true"> {profile.data?.interests.some(i => i.target.kind === 'domain' && i.target.value === key) ? '✓' : '+'}</span></button>)}</div></section>
    <section className="r1-interest-section"><h2>添加更具体的关注</h2><form onSubmit={event => void add(event)} className="r1-interest-form"><label>关注类型<select value={kind} onChange={event => setKind(event.target.value as typeof kind)}><option value="term">主题词</option><option value="source">来源</option><option value="author">作者／署名</option></select></label><label>{kind === 'term' ? '主题词' : kind === 'source' ? '来源名称' : '作者／署名'}<input value={value} onChange={event => setValue(event.target.value)} maxLength={kind === 'term' ? 60 : 200} list={kind === 'source' ? 'r1-source-names' : undefined} required placeholder={kind === 'term' ? '例如 人工智能、城市生活' : kind === 'source' ? '选择来源或输入未接入的来源' : ''} /></label>{kind === 'author' && <label>所属平台<input value={platform} onChange={event => setPlatform(event.target.value)} maxLength={80} required placeholder="例如 知乎、豆瓣" /></label>}<button disabled={unavailable || !value.trim() || kind === 'author' && !platform.trim()}>保存关注</button><datalist id="r1-source-names">{Object.entries(SOURCE_NAMES).map(([id, name]) => <option key={id} value={name} />)}</datalist></form><p className="r1-method">关注从实际已取得的材料中匹配。保存未知来源或署名不代表已接通采集，也不会自动取得某位作者的全部文章。</p></section>
    <section className="r1-interest-section"><h2>已关注 <span>{profile.data?.interests.length ?? 0}</span></h2>{profile.data?.interests.length === 0 && <p>还没有关注。可以先浏览，再逐渐留下偏好。</p>}<ul className="r1-saved-interests">{profile.data?.interests.map(interest => <li key={interest.resource_key}><div><small>{KIND_LABELS[interest.target.kind]}</small><strong>{interest.target.kind === 'domain' ? DOMAINS[interest.target.value] : interest.target.kind === 'source' ? SOURCE_NAMES[interest.target.value] ?? interest.label : interest.label}</strong><p>{interest.target.kind === 'author' ? `${PLATFORM_NAMES[interest.target.platform ?? ''] ?? interest.target.platform} · ${interest.support.matching === 'platform_id' ? '按已核实的平台 ID 匹配' : '按现有署名匹配，身份未独立核实'}；未接通专属作者采集` : interest.target.kind === 'source' ? interest.support.collection === 'enabled_r1_path' ? '来源路径已配置启用；实际成功状态见来源记录' : '采集未开放／未接入；只保存偏好' : '用于现有已审核内容的推荐匹配'}</p></div><button disabled={unavailable} onClick={() => void profile.change('/api/interests', 'DELETE', { target: interest.target })}>取消关注</button></li>)}</ul></section>
    <section className="r1-interest-section"><h2>内容反馈</h2><p>已保存 {profile.data?.feedback.length ?? 0} 条。阅读本身不会自动隐藏内容，也不会记成喜欢。</p>{profile.data?.feedback.map(feedback => <div className="r1-feedback-record" key={feedback.content_id}><Link to={`/reading/${feedback.content_id}`}>查看内容 #{feedback.content_id}</Link><span>{feedback.value === 'interested' ? '感兴趣' : '不感兴趣'}</span><TargetActions target={{ type: 'content', id: feedback.content_id }} title={`内容 #${feedback.content_id}`} profile={profile} /><button disabled={unavailable} onClick={() => void profile.change('/api/feedback', 'DELETE', { content_id: feedback.content_id })}>撤销反馈</button></div>)}</section>
  </div>
}
