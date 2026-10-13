import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Drawer, Empty, Table } from 'antd'
import { useState } from 'react'
import { Link, type To } from 'react-router-dom'

import type { AdminRange } from './adminFilters'
import { getHistoryPage, type ArticleRow } from './adminHistoryApi'
import { costParams, getCost, money, type CallRow, type Paged } from './costsApi'

function clippedBucketRange(range: AdminRange, bucket: string, granularity: 'hour' | 'day' | 'month'): AdminRange {
  const start = granularity === 'month'
    ? Date.parse(`${bucket}-01T00:00:00+08:00`)
    : granularity === 'hour'
      ? Date.parse(`${bucket.replace(' ', 'T')}:00+08:00`)
      : Date.parse(`${bucket}T00:00:00+08:00`)
  const nextMonth = new Date(start + 36 * 86_400_000)
  const end = granularity === 'month'
    ? Date.parse(`${nextMonth.toISOString().slice(0, 7)}-01T00:00:00+08:00`)
    : start + (granularity === 'hour' ? 3_600_000 : 86_400_000)
  return { period: 'custom', start: new Date(Math.max(start, Date.parse(range.start))).toISOString(), end: new Date(Math.min(end, Date.parse(range.end))).toISOString() }
}

export default function OverviewDayDetail({ range, day, granularity, kind, onClose, articleTarget }: { range: AdminRange; day: string; granularity: 'hour' | 'day' | 'month'; kind: 'articles' | 'calls'; onClose: () => void; articleTarget: (id: number) => To }) {
  const [page, setPage] = useState(1)
  const detailRange = clippedBucketRange(range, day, granularity)
  const articles = useQuery({ queryKey: ['admin', 'overview-day-articles', detailRange.start, detailRange.end, page], queryFn: ({ signal }) => getHistoryPage<ArticleRow>('articles', detailRange, { page }, signal), enabled: kind === 'articles', retry: false })
  const calls = useQuery({ queryKey: ['admin', 'overview-day-calls', detailRange.start, detailRange.end, page], queryFn: ({ signal }) => getCost<Paged<CallRow>>('costs/calls', costParams(detailRange, { page }), signal), enabled: kind === 'calls', retry: false })
  const active = kind === 'articles' ? articles : calls
  return <Drawer title={`${day} · ${kind === 'articles' ? '入库文章' : '模型调用'}明细`} open onClose={onClose} size={Math.min(680, window.innerWidth)}>
    <p className="admin-note">北京时间该时段与全局所选期间的交集；关闭后保持总览范围。</p>
    {active.isError && <Alert type="error" title="明细加载失败" action={<Button onClick={() => void active.refetch()}>重试</Button>} />}
    {kind === 'articles' ? <Table rowKey="id" loading={articles.isPending} dataSource={articles.data?.items ?? []} locale={{ emptyText: <Empty description="此时段没有文章" /> }} pagination={{ current: page, pageSize: 25, total: articles.data?.total ?? 0, showSizeChanger: false, onChange: setPage }} columns={[
      { title: '文章', dataIndex: 'title', render: (title: string, row: ArticleRow) => <Link to={articleTarget(row.id)}>{title}</Link> },
      { title: '来源', dataIndex: 'source_name', render: (value: string | null, row: ArticleRow) => value || row.source_id },
    ]} /> : <Table rowKey="id" loading={calls.isPending} dataSource={calls.data?.items ?? []} locale={{ emptyText: <Empty description="此时段没有调用" /> }} pagination={{ current: page, pageSize: 25, total: calls.data?.total ?? 0, showSizeChanger: false, onChange: setPage }} columns={[
      { title: '用途', dataIndex: 'purpose' }, { title: '模型', dataIndex: 'model' }, { title: '费用 USD', dataIndex: 'cost_usd', render: money },
    ]} />}
  </Drawer>
}
