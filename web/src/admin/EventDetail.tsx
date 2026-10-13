import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Descriptions, Drawer, Empty, Spin, Table, Typography } from 'antd'

import type { AdminRange } from './adminFilters'
import { displayTime, getHistoryDetail, type EventDetailData } from './adminHistoryApi'

interface Props { id: number | null; range: AdminRange; onClose: () => void; onArticle: (id: number) => void }

export default function EventDetail({ id, range, onClose, onArticle }: Props) {
  const query = useQuery({
    queryKey: ['admin', 'event', id],
    queryFn: ({ signal }) => getHistoryDetail<EventDetailData>('events', id!, range, signal),
    enabled: id !== null, retry: false,
  })
  const event = query.data
  return <Drawer open={id !== null} onClose={onClose} title={event?.title || `事件 #${id}`} size={Math.min(720, typeof window === 'undefined' ? 720 : window.innerWidth)}>
    {query.isPending && <Spin />}
    {query.isError && <Alert type="error" showIcon title="无法加载事件详情" action={<Button size="small" onClick={() => void query.refetch()}>重试</Button>} />}
    {event && <div className="admin-detail-stack">
      <Descriptions bordered size="small" column={1} items={[
        { key: 'earliest', label: '最早有效报道', children: displayTime(event.earliest_published_at) },
        { key: 'latest', label: '最新有效报道', children: displayTime(event.latest_published_at) },
        { key: 'counts', label: '文章 / 独立来源', children: `${event.article_count} / ${event.source_count}` },
        { key: 'score', label: '综合分', children: event.score_final ?? '未评分' },
        { key: 'scored', label: '评分时间', children: displayTime(event.scored_at) },
      ]} />
      {!event.earliest_published_at && <Alert type="info" showIcon title="关联文章缺少有效报道时间；系统发现时间不当作报道时间。" />}
      <Typography.Title level={5}>事件摘要</Typography.Title><Typography.Paragraph>{event.summary_zh || '未记录'}</Typography.Paragraph>
      <Typography.Title level={5}>分数组成与理由</Typography.Title>
      {event.score_breakdown ? <pre className="admin-json-detail">{JSON.stringify(event.score_breakdown, null, 2)}</pre> : <Typography.Text type="secondary">未记录</Typography.Text>}
      <Typography.Title level={5}>来源报道时间线</Typography.Title>
      {event.articles.length ? <Table rowKey="id" size="small" pagination={false} dataSource={event.articles} scroll={{ x: 530 }} columns={[
        { title: '报道时间', dataIndex: 'published_at', render: displayTime, width: 160 },
        { title: '文章与来源', key: 'article', render: (_: unknown, article: EventDetailData['articles'][number]) => <><Button type="link" size="small" onClick={() => onArticle(article.id)}>{article.title}</Button><small>{article.source_name || article.source_id}</small></> },
      ]} /> : <Empty description="没有关联文章" />}
      <Typography.Title level={5}>观点与证据</Typography.Title>
      {event.viewpoint?.payload.claims?.length ? event.viewpoint.payload.claims.map((claim, index) => <blockquote className="admin-evidence" key={`${claim.article_id}-${index}`}><strong>{claim.claim}</strong><p>{claim.evidence_quote || '原文证据未记录'}</p></blockquote>) : <Typography.Text type="secondary">未记录</Typography.Text>}
      <Typography.Text type="secondary">实质进展与逐阶段处理记录尚未记录；这里展示的是来源报道时间线。</Typography.Text>
    </div>}
  </Drawer>
}
