import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Descriptions, Drawer, Empty, Spin, Table, Typography } from 'antd'
import { Link } from 'react-router-dom'

import type { AdminRange } from './adminFilters'
import { sharedRangeSearch } from './adminFilters'
import { displayTime, getHistoryDetail, safeExternalUrl, type SourceDetailData } from './adminHistoryApi'

interface Props { id: string | null; range: AdminRange; search: URLSearchParams; onClose: () => void }

export default function SourceDetail({ id, range, search, onClose }: Props) {
  const query = useQuery({
    queryKey: ['admin', 'source', id, range.start, range.end],
    queryFn: ({ signal }) => getHistoryDetail<SourceDetailData>('sources', id!, range, signal),
    enabled: Boolean(id), retry: false,
  })
  const source = query.data
  const contentSearch = new URLSearchParams(sharedRangeSearch(search))
  if (id) contentSearch.set('source_id', id)
  const url = source?.config && safeExternalUrl(source.config.url)
  return <Drawer className="admin-detail-drawer" open={Boolean(id)} onClose={onClose} title={source?.name || id || '信息源详情'} size={Math.min(620, typeof window === 'undefined' ? 620 : window.innerWidth)}>
    {query.isPending && <Spin />}
    {query.isError && <Alert type="error" showIcon title="无法加载来源详情" action={<Button size="small" onClick={() => void query.refetch()}>重试</Button>} />}
    {source && <div className="admin-detail-stack">
      {!source.configured && <Alert type="info" showIcon title="此来源已不在当前配置中；历史名称和属性未记录。" />}
      <Descriptions bordered size="small" column={1} items={[
        { key: 'id', label: '来源 ID', children: source.id },
        { key: 'status', label: '期间抓取', children: `${source.successful_fetches} 次成功 · ${source.failed_fetches} 次失败 · ${source.new_articles} 篇新文章` },
        { key: 'health', label: '当前抓取状态', children: source.health === 'error' ? '最近一次失败' : source.health === 'ok' ? '最近一次成功' : '从未抓取' },
        { key: 'last', label: '最近成功', children: displayTime(source.last_success_at) },
        { key: 'error', label: '最近错误', children: source.last_error ? `${displayTime(source.last_error_at)} · ${source.last_error}` : '未记录' },
        ...(source.config ? [
          { key: 'url', label: '当前地址', children: url ? <a href={url} target="_blank" rel="noopener noreferrer">{source.config.url}</a> : source.config.url },
          { key: 'weight', label: '当前权重', children: source.config.weight },
          { key: 'timeout', label: '当前超时', children: source.config.timeout_seconds ? `${source.config.timeout_seconds} 秒` : '默认配置' },
        ] : []),
      ]} />
      <Typography.Title level={5}>期间最近 100 条抓取记录</Typography.Title>
      <Table rowKey="id" size="small" dataSource={source.fetches} pagination={false} columns={[
        { title: '时间', dataIndex: 'run_at', render: displayTime },
        { title: '结果', dataIndex: 'status', render: (status: string, row) => status === 'ok' ? `成功 · ${row.new_articles} 篇新文章` : `失败 · ${row.error || '未记录错误'}` },
      ]} />
      <Typography.Title level={5}>期间最近 100 篇文章</Typography.Title>
      {source.articles.length ? <Table rowKey="id" size="small" dataSource={source.articles} pagination={false} columns={[
        { title: '文章', dataIndex: 'title' },
        { title: '入库', dataIndex: 'fetched_at', render: displayTime },
      ]} /> : <Empty description="期间无新文章" />}
      <Link to={{ pathname: '/admin/content', search: contentSearch.toString() }} onClick={onClose}>查看此来源在所选期间的文章 →</Link>
    </div>}
  </Drawer>
}
