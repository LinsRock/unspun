import { useQuery } from '@tanstack/react-query'
import { Button, Empty, Table, Tabs } from 'antd'
import { useSearchParams } from 'react-router-dom'

import { fetchAdmin, type ConfigurationResult } from './adminApi'

export default function ConfigurationPage() {
  const [search, setSearch] = useSearchParams()
  const tab = ['sources', 'pipeline', 'audit'].includes(search.get('tab') ?? '') ? search.get('tab')! : 'pipeline'
  const query = useQuery({ queryKey: ['admin', 'configuration'], queryFn: ({ signal }) => fetchAdmin<ConfigurationResult>('configuration', undefined, signal), retry: false })
  const config = query.data
  return <div className="admin-panel">
    <Tabs activeKey={tab} onChange={value => { const next = new URLSearchParams(search); next.set('tab', value); setSearch(next) }} items={[
      { key: 'sources', label: '信息源配置' }, { key: 'pipeline', label: '管线与预算' }, { key: 'audit', label: '变更与操作记录' },
    ]} />
    <p className="admin-footnote admin-config-notice">当前配置只读；历史配置与审计记录尚未接入。</p>
    {query.isPending && <p role="status">正在加载配置…</p>}
    {query.isError && <div role="alert">配置加载失败。<Button onClick={() => void query.refetch()}>重试</Button></div>}
    {config && tab === 'sources' && <Table rowKey="id" dataSource={config.sources} scroll={{ x: 600 }} pagination={{ pageSize: 20 }} locale={{ emptyText: <Empty description="当前没有配置信息源" /> }} columns={[
      { title: '来源', dataIndex: 'name' }, { title: 'ID', dataIndex: 'id' }, { title: '语言 / 地区', render: (_, row: ConfigurationResult['sources'][number]) => `${row.lang} / ${row.region}` }, { title: '权重', dataIndex: 'weight' }, { title: '超时', dataIndex: 'timeout_seconds', render: (value: number | null) => value === null ? '默认值' : `${value} 秒` },
    ]} />}
    {config && tab === 'pipeline' && <div className="admin-config-grid">
      <section><div className="admin-section-heading"><h2>运行节奏</h2><span className="admin-scope">当前部署</span></div><dl>{[
        ['抓取间隔', `${config.pipeline.fetch_interval_minutes} 分钟`], ['摘要批次', config.pipeline.summary_batch_limit], ['Embedding 批次', config.pipeline.embed_batch_limit], ['评分批次', config.pipeline.score_batch_limit], ['日报调度', `${config.pipeline.digest_hour}:00 · ${config.pipeline.digest_timezone}`],
      ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl><p className="admin-footnote">调度配置不代表历史实际执行时间。</p></section>
      <section><div className="admin-section-heading"><h2>模型路由</h2><span className="admin-scope">OpenRouter</span></div><dl>{[
        ['文章摘要', config.pipeline.summary_model], ['重要性评分', config.pipeline.importance_model], ['观点生成', config.pipeline.viewpoint_model], ['日报生成', config.pipeline.digest_model], ['向量嵌入', config.pipeline.embedding_model],
      ].map(([label, value]) => <div key={label}><dt>{label}</dt><dd><code>{value}</code></dd></div>)}</dl></section>
      <section><div className="admin-section-heading"><h2>预算与失败约束</h2><span className="admin-scope">保护机制</span></div><dl><div><dt>审核限额</dt><dd>${config.pipeline.grounding_budget_24h_usd} / 滚动 24 小时</dd></div><div><dt>摘要失败上限</dt><dd>{config.pipeline.max_summary_failures} 次</dd></div><div><dt>模型凭证</dt><dd><span className={`admin-credential ${config.credentials.openrouter_configured ? '' : 'missing'}`}><i className="admin-dot" />{config.credentials.openrouter_configured ? '已配置' : '未配置'}</span></dd></div></dl><p className="admin-footnote">长期配置通过仓库评审与部署生效；凭证仅展示配置状态。</p></section>
    </div>}
    {config && tab === 'audit' && <Empty description="历史操作记录未记录；配置变更与任务审计将在 M3-C 接入。" />}
  </div>
}
