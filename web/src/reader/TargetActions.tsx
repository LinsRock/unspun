import { useState } from 'react'
import { DislikeFilled, DislikeOutlined, LikeFilled, LikeOutlined } from '@ant-design/icons'
import type { Feedback, Target } from './api'
import type { useReader } from './profile'

export default function TargetActions({ target, title, profile, unavailable = false }: { target: Target; title: string; profile: ReturnType<typeof useReader>; unavailable?: boolean }) {
  const [pending, setPending] = useState('')
  const preference = target.type === 'topic' ? profile.data?.topic_preferences?.find(p => p.target.id === target.id) : undefined
  const selected = target.type === 'topic' ? preference?.feedback : profile.data?.feedback.find(p => p.content_id === target.id)?.value
  const disabled = profile.saving || !!pending || !profile.online || !profile.data || !!profile.error
  async function feedback(value: Feedback) {
    setPending(value)
    try {
      const remove = selected === value
      await profile.change(profile.topics ? '/api/target-feedback' : '/api/feedback', remove ? 'DELETE' : 'PUT', { ...(profile.topics ? { target } : { content_id: target.id }), ...(!remove ? { value } : {}) })
    } finally { setPending('') }
  }
  async function follow() {
    setPending('follow')
    try { await profile.change('/api/topic-follows', preference?.followed ? 'DELETE' : 'PUT', { target }) } finally { setPending('') }
  }
  return <div className="r1-feedback r2-actions" role="group" aria-label={`${title}的偏好`}>
    {target.type === 'topic' && profile.topics && <button className="r2-follow-button" disabled={disabled || unavailable && !preference?.followed} aria-pressed={!!preference?.followed} aria-busy={pending === 'follow'} onClick={() => void follow()}>{pending === 'follow' ? '保存中…' : preference?.followed ? '已关注 · 取消' : '关注话题'}</button>}
    {(target.type === 'content' || profile.topics) && (['interested', 'not_interested'] as const).map(value => {
      const active = selected === value
      const Icon = value === 'interested' ? active ? LikeFilled : LikeOutlined : active ? DislikeFilled : DislikeOutlined
      const label = `${active ? '撤销' : ''}${value === 'interested' ? '感兴趣' : '不感兴趣'}`
      return <button key={value} disabled={disabled || unavailable && !active} aria-label={pending === value ? '正在保存反馈' : label} title={label} aria-pressed={active} aria-busy={pending === value} onClick={() => void feedback(value)}>{pending === value ? <span className="r1-spinner" aria-hidden="true" /> : <Icon aria-hidden="true" />}</button>
    })}
  </div>
}
