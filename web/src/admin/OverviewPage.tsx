import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Empty, Select } from 'antd'
import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import { Link, useLocation } from 'react-router-dom'
import { useState } from 'react'

import type { AdminRange } from './adminFilters'
import { rangeSearch } from './adminFilters'
import { money } from './costsApi'
import MetricCard from './MetricCard'
import OverviewDayDetail from './OverviewDayDetail'
import { getOverview, type OverviewGranularity } from './overviewApi'
import TrendChart from './TrendChart'

const pieColors = ['#4c78a8', '#e69f00', '#009e73', '#cc79a7', '#56b4e9', '#d55e00']
const processSeries = [
  { key: 'pending', label: '待处理', color: '#9aa0a6' },
  { key: 'failed', label: '失败', color: '#d55e00' },
  { key: 'summarized', label: '已摘要', color: '#e69f00' },
  { key: 'embedded', label: '已嵌入', color: '#56b4e9' },
  { key: 'clustered', label: '已聚类', color: '#009e73' },
]

export default function OverviewPage({ range }: { range: AdminRange }) {
  const location = useLocation()
  const [selectedDay, setSelectedDay] = useState<{ kind: 'articles' | 'calls'; day: string } | null>(null)
  const [granularity, setGranularity] = useState<OverviewGranularity>('auto')
  const rangeDays = (Date.parse(range.end) - Date.parse(range.start)) / 86_400_000
  const granularityOptions = rangeDays <= 14
    ? ['auto', 'hour', 'day'] as const
    : ['auto', 'day', 'month'] as const
  const query = useQuery({ queryKey: ['admin', 'overview', range.start, range.end, granularity], queryFn: ({ signal }) => getOverview(range, granularity, signal), retry: false })
  function target(pathname: string, params: Record<string, string> = {}) {
    const search = rangeSearch(new URLSearchParams(location.search), range)
    for (const key of [...search.keys()]) if (!['period', 'start', 'end'].includes(key)) search.delete(key)
    for (const [key, value] of Object.entries(params)) search.set(key, value)
    return { pathname, search: search.toString() }
  }

  if (query.isPending) return <p role="status">正在加载总览…</p>
  if (query.isError) return <Alert type="error" showIcon title="总览加载失败" description="请检查网络后重试。" action={<Button onClick={() => void query.refetch()}>重试</Button>} />

  const data = query.data
  const cost = data.period.cost
  const purposes = data.purposes.map(item => ({ name: item.name, value: Number(item.cost_usd) })).filter(item => item.value > 0)
  const purposeTotal = purposes.reduce((sum, item) => sum + item.value, 0)
  return <div className="admin-overview">
    <p className="admin-note">所选期间的产出与费用；来源健康和待处理量是当前状态，不随日期变化。新事件按系统创建时间统计。</p>
    <div className="admin-overview-metrics">
      <MetricCard label="新入库文章" value={`${data.period.articles} 篇`} to={target('/admin/content', { tab: 'articles' })} />
      <MetricCard label="新建事件" value={`${data.period.new_events} 个`} note="按系统创建时间" to={target('/admin/content', { tab: 'events', time_status: 'discovered' })} />
      <MetricCard label="期间已确认成本" value={cost.total_confirmed_usd === null ? '未换算' : `${money(cost.total_confirmed_usd)} USD`} note="调用 + 固定费用分摊" to={target('/admin/costs')} />
    </div>
    {cost.fixed.unconverted_currencies.length > 0 && <Alert type="warning" title={`缺少汇率：${cost.fixed.unconverted_currencies.join('、')}；USD 总额不完整。`} />}
    <div className="admin-overview-current admin-panel">
      <h2>当前状态 <small>实时查询</small></h2>
      <div className="admin-overview-status">
        <Link to={target('/admin/sources', { health: 'error' })}>异常信息源 <strong>{data.current.source_health.error}</strong></Link>
        <Link to={target('/admin/sources', { health: 'no_runs' })}>从未抓取 <strong>{data.current.source_health.no_runs}</strong></Link>
        <Link to={target('/admin/runs', { tab: 'backlog' })}>待摘要 <strong>{data.current.backlog.pending_summaries}</strong></Link>
        <Link to={target('/admin/runs', { tab: 'backlog', stage: 'abandoned_summary' })}>摘要失败上限 <strong>{data.current.backlog.abandoned_summaries}</strong></Link>
        <Link to={target('/admin/runs', { tab: 'backlog', stage: 'pending_embedding' })}>待 Embedding <strong>{data.current.backlog.pending_embeddings}</strong></Link>
        <Link to={target('/admin/runs', { tab: 'backlog', stage: 'pending_score' })}>待评分 <strong>{data.current.backlog.pending_scores}</strong></Link>
      </div>
    </div>
    <section className="admin-panel admin-trend-controls"><label htmlFor="overview-granularity">趋势粒度</label><Select id="overview-granularity" aria-label="趋势粒度" value={granularity} onChange={value => setGranularity(value as OverviewGranularity)} options={granularityOptions.map(value => ({ value, label: ({ auto: '自动', hour: '按小时', day: '按天', month: '按月' })[value] }))} /></section>
    <div className="admin-overview-trends">
      <TrendChart title="文章入库趋势" total={`${data.period.articles} 篇`} data={data.article_trend.map(item => ({ day: item.day, articles: item.articles }))} series={[{ key: 'articles', label: '文章', color: 'var(--accent)' }]} onSelectDay={day => setSelectedDay({ kind: 'articles', day })} />
      <TrendChart title="调用费用趋势" total={`${money(cost.calls.cost_usd)} USD`} data={data.call_purpose_trend ?? []} series={data.purposes.map((item, index) => ({ key: item.name, label: item.name, color: pieColors[index % pieColors.length] ?? pieColors[0]! }))} format="money" onSelectDay={day => setSelectedDay({ kind: 'calls', day })} />
      <TrendChart title="文章处理状态趋势" total={`${data.period.articles} 篇`} data={data.processing_trend ?? []} series={processSeries} note="按文章入库时间分组，显示当前处理状态；历史阶段完成时间尚未记录。" />
    </div>
    <div className="admin-overview-lower">
      <section className="admin-panel"><h2>调用用途 <small>不含固定费用</small></h2>
        {purposes.length ? <><div className="admin-pie" role="img" aria-label="调用用途占比图，详细数值见下表"><ResponsiveContainer width="100%" height="100%"><PieChart accessibilityLayer><Pie data={purposes} dataKey="value" nameKey="name" innerRadius={52} outerRadius={78}>{purposes.map((item, index) => <Cell key={item.name} fill={pieColors[index % pieColors.length]} />)}</Pie><Tooltip formatter={value => `${money(String(value))} USD`} /><Legend /></PieChart></ResponsiveContainer></div><table className="admin-purpose-table"><caption>调用用途费用数据</caption><thead><tr><th scope="col">用途</th><th scope="col">费用 USD</th><th scope="col">占比</th></tr></thead><tbody>{purposes.map(item => <tr key={item.name}><th scope="row"><Link to={target('/admin/costs', { tab: 'calls', purpose: item.name })}>{item.name}</Link></th><td>{money(item.value)}</td><td>{(item.value / purposeTotal * 100).toFixed(1)}%</td></tr>)}</tbody></table></> : <Empty description="所选期间没有调用费用" />}
        <p className="admin-note">固定费用单列。<Link to={target('/admin/costs')}>查看全部费用与账目</Link></p>
      </section>
      <section className="admin-panel"><h2>异常与最近运行</h2>
        <p>所选期间抓取失败 <Link to={target('/admin/sources', { sort: 'failure_rate' })}>{data.period.fetch_errors} 次</Link> · AI 运行 <Link to={target('/admin/runs')}>{data.period.runs} 轮</Link></p>
        {data.exceptions.source_error_total > 0 ? <ul className="admin-exceptions">{data.exceptions.sources.map(item => <li key={item.source_id}><Link to={target('/admin/sources', { source_detail: item.source_id })}>{item.name}</Link><span>{item.last_error || '错误详情未记录'}</span></li>)}</ul> : <p>当前没有抓取失败的信息源。</p>}
        {data.exceptions.source_error_total > data.exceptions.sources.length && <Link to={target('/admin/sources', { health: 'error' })}>查看全部 {data.exceptions.source_error_total} 个异常信息源</Link>}
        {data.recent_run ? <p>最近运行 <Link to={target('/admin/runs')}>#{data.recent_run.id}</Link> · {new Date(data.recent_run.run_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })} · 运行状态{data.recent_run.status ?? '未记录'} · 耗时{data.recent_run.duration_seconds === null ? '未记录' : `${data.recent_run.duration_seconds} 秒`}</p> : <p>最近运行：未记录</p>}
        <p className="admin-note">最近运行记录不代表管线当前健康；阶段状态和结束时间若未采集，仍显示未记录。</p>
      </section>
    </div>
    {selectedDay && <OverviewDayDetail key={`${selectedDay.kind}-${selectedDay.day}`} range={range} day={selectedDay.day} granularity={data.granularity ?? 'day'} kind={selectedDay.kind} onClose={() => setSelectedDay(null)} articleTarget={id => target('/admin/content', { tab: 'articles', article_detail: String(id) })} />}
  </div>
}
