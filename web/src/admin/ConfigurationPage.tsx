import { useQuery } from '@tanstack/react-query'
import { Button, Descriptions, Empty, Table, Tabs } from 'antd'
import { useSearchParams } from 'react-router-dom'

import { fetchAdmin, type ConfigurationResult } from './adminApi'

export default function ConfigurationPage() {
  const [search, setSearch] = useSearchParams()
  const tab = ['sources', 'pipeline', 'audit'].includes(search.get('tab') ?? '') ? search.get('tab')! : 'pipeline'
  const query = useQuery({ queryKey: ['admin', 'configuration'], queryFn: ({ signal }) => fetchAdmin<ConfigurationResult>('configuration', undefined, signal), retry: false })
  const config = query.data
  return <div className="admin-panel">
    <p className="admin-note">当前部署配置只读。历史配置版本与操作审计尚未记录。</p>
    <Tabs activeKey={tab} onChange={value => { const next = new URLSearchParams(search); next.set('tab', value); setSearch(next) }} items={[
      { key: 'sources', label: '信息源配置' }, { key: 'pipeline', label: '管线与预算' }, { key: 'audit', label: '变更与操作记录' },
    ]} />
    {query.isPending && <p role="status">正在加载配置…</p>}
    {query.isError && <div role="alert">配置加载失败。<Button onClick={() => void query.refetch()}>重试</Button></div>}
    {config && tab === 'sources' && <Table rowKey="id" dataSource={config.sources} scroll={{ x: 600 }} pagination={{ pageSize: 20 }} locale={{ emptyText: <Empty description="当前没有配置信息源" /> }} columns={[
      { title: '来源', dataIndex: 'name' }, { title: 'ID', dataIndex: 'id' }, { title: '语言 / 地区', render: (_, row: ConfigurationResult['sources'][number]) => `${row.lang} / ${row.region}` }, { title: '权重', dataIndex: 'weight' }, { title: '超时', dataIndex: 'timeout_seconds', render: (value: number | null) => value === null ? '默认值' : `${value} 秒` },
    ]} />}
    {config && tab === 'pipeline' && <Descriptions bordered size="small" column={1} items={[
      { key: 'interval', label: '抓取间隔', children: `${config.pipeline.fetch_interval_minutes} 分钟` },
      { key: 'summary', label: '摘要批次', children: config.pipeline.summary_batch_limit },
      { key: 'embedding', label: 'Embedding 批次', children: config.pipeline.embed_batch_limit },
      { key: 'score', label: '评分批次', children: config.pipeline.score_batch_limit },
      { key: 'failures', label: '摘要失败上限', children: config.pipeline.max_summary_failures },
      { key: 'digest', label: '日报配置时间', children: `${config.pipeline.digest_hour}:00 · ${config.pipeline.digest_timezone}（历史实际执行时间未记录）` },
      { key: 'budget', label: '审核限额', children: `$${config.pipeline.grounding_budget_24h_usd} / 滚动 24 小时` },
      { key: 'models', label: '摘要 / 评分 / 观点模型', children: `${config.pipeline.summary_model} / ${config.pipeline.importance_model} / ${config.pipeline.viewpoint_model}` },
      { key: 'credential', label: '模型凭证', children: config.credentials.openrouter_configured ? '已配置' : '未配置' },
    ]} />}
    {config && tab === 'audit' && <Empty description="历史操作记录未记录；配置变更与任务审计将在 M3-C 接入。" />}
  </div>
}
