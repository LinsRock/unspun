import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getTopic } from './api'
import type { ReaderState } from './api'
import type { useReader } from './profile'
import TargetActions from './TargetActions'

export default function FollowedTopic({ preference, profile }: { preference: NonNullable<ReaderState['topic_preferences']>[number]; profile: ReturnType<typeof useReader> }) {
  const { id } = preference.target
  const query = useQuery({ queryKey: ['r2-topic', id], queryFn: ({ signal }) => getTopic(id, signal), retry: false, staleTime: 0 })
  const title = !query.error && query.data ? query.data.title : `话题 ${id.slice(0, 8)}`
  return <article className="r2-followed"><Link to={`/topics/${id}`} state={{ returnTo: '/interests' }}>{title}</Link>
    <p className="r1-method">{query.isPending ? '正在读取话题…' : query.error ? '暂时无法读取当前话题。已保存的关注与反馈仍可撤销。' : preference.followed ? '已关注此话题' : '已保存话题反馈'}{query.data?.engineering_preview && ' · 工程预览示例'}</p>
    <TargetActions target={{ type: 'topic', id }} title={title} profile={profile} unavailable={!!query.error || query.isPending} />
  </article>
}
