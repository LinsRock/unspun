import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Empty, Select } from 'antd'
import { ArrowRightOutlined } from '@ant-design/icons'
import { Link, useLocation } from 'react-router-dom'
import { useState } from 'react'

import type { AdminRange } from './adminFilters'
import { rangeSearch } from './adminFilters'
import { money } from './costsApi'
import MetricCard from './MetricCard'
import OverviewDayDetail from './OverviewDayDetail'
import { getOverview, type OverviewGranularity } from './overviewApi'
import TrendChart from './TrendChart'
import { AttentionQueue, PipelineBacklog, SourceHealth } from './OverviewOperations'

const colors = ['var(--chart-primary)', 'var(--chart-secondary)', '#b79562', 'var(--chart-muted)', '#8f82a7', '#ba7770']
const processSeries = [
  { key: 'pending', label: '待处理', color: '#b9c0bd' },
  { key: 'failed', label: '失败', color: '#bc5748' },
  { key: 'summarized', label: '已摘要', color: '#b79562' },
  { key: 'embedded', label: '已嵌入', color: '#778da2' },
  { key: 'clustered', label: '已聚类', color: 'var(--chart-primary)' },
]
export default function OverviewPage({ range }: { range: AdminRange }) {
  const location = useLocation()
  const [selectedDay, setSelectedDay] = useState<{ kind: 'articles' | 'calls'; day: string } | null>(null)
  const [granularity, setGranularity] = useState<OverviewGranularity>('auto')
  const rangeDays = (Date.parse(range.end) - Date.parse(range.start)) / 86_400_000
  const granularityOptions = rangeDays <= 14 ? ['auto', 'hour', 'day'] as const : ['auto', 'day', 'month'] as const
  const query = useQuery({ queryKey: ['admin', 'overview', range.start, range.end, granularity], queryFn: ({ signal }) => getOverview(range, granularity, signal), retry: false })
  function target(pathname: string, params: Record<string, string> = {}) {
    const search = rangeSearch(new URLSearchParams(location.search), range)
    for (const key of [...search.keys()]) if (!['period', 'start', 'end'].includes(key)) search.delete(key)
    for (const [key, value] of Object.entries(params)) search.set(key, value)
    return { pathname, search: search.toString() }
  }
  if (query.isPending) return <div className="admin-loading" role="status">正在加载总览…</div>
  if (query.isError) return <Alert type="error" showIcon title="总览加载失败" description="请检查网络后重试。" action={<Button onClick={() => void query.refetch()}>重试</Button>} />
  const data = query.data
  const cost = data.period.cost
  const purposes = data.purposes.map(item => ({ name: item.name, value: Number(item.cost_usd) })).filter(item => item.value > 0).sort((a, b) => b.value - a.value)
  const purposeTotal = purposes.reduce((sum, item) => sum + item.value, 0)
  const run = data.recent_run
  return <div className="admin-overview">
    <div className="admin-overview-metrics">
      <MetricCard label="新入库文章" value={`${data.period.articles.toLocaleString()} 篇`} note="所选期间 · 按入库时间" to={target('/admin/content', { tab: 'articles' })} />
      <MetricCard label="新建事件" value={`${data.period.new_events.toLocaleString()} 个`} note="所选期间 · 按系统创建时间" to={target('/admin/content', { tab: 'events', time_status: 'discovered' })} />
      <MetricCard label="期间已确认成本" value={cost.total_confirmed_usd === null ? '未换算' : `$${money(cost.total_confirmed_usd)}`} note="USD · 调用与固定费用分摊" to={target('/admin/costs')} />
      <MetricCard label="抓取失败" value={`${data.period.fetch_errors.toLocaleString()} 次`} note="所选期间 · 查看来源" to={target('/admin/sources', { sort: 'failure_rate' })} />
    </div>
    {cost.fixed.unconverted_currencies.length > 0 && <Alert type="warning" showIcon title={`缺少汇率：${cost.fixed.unconverted_currencies.join('、')}；USD 总额不完整。`} />}
    <AttentionQueue data={data} target={target} />
    <div className="admin-section-heading admin-trend-controls"><div><h2>采集与产出</h2><span className="admin-note">所选期间 · 点击图中数据查看明细</span></div><Select aria-label="趋势粒度" value={granularity} onChange={value => setGranularity(value as OverviewGranularity)} options={granularityOptions.map(value => ({ value, label: ({ auto: '自动粒度', hour: '按小时', day: '按天', month: '按月' })[value] }))} /></div>
    <div className="admin-overview-primary">
      <TrendChart title="文章入库趋势" total={`${data.period.articles} 篇`} data={data.article_trend.map(item => ({ day: item.day, articles: item.articles }))} series={[{ key: 'articles', label: '文章', color: 'var(--accent)' }]} variant="area" onSelectDay={day => setSelectedDay({ kind: 'articles', day })} />
      <SourceHealth data={data} target={target} />
    </div>
    <PipelineBacklog data={data} target={target} />
    <div className="admin-overview-lower">
      <section className="admin-panel"><div className="admin-section-heading"><h2>调用费用分布 <small>不含固定费用</small></h2><Link to={target('/admin/costs')}>费用分析 <ArrowRightOutlined /></Link></div><div className="admin-section-total">${money(cost.calls.cost_usd)}<small>USD · {cost.calls.count.toLocaleString()} 次调用</small></div>
        {purposes.length ? <div className="admin-horizontal-bars">{purposes.map((item, index) => <Link to={target('/admin/costs', { tab: 'calls', purpose: item.name })} key={item.name}><span>{item.name}<b>${money(item.value)}<small>{(item.value / purposeTotal * 100).toFixed(1)}%</small></b></span><div><i style={{ width: `${item.value / purposeTotal * 100}%`, background: colors[index % colors.length] }} /></div></Link>)}</div> : <Empty description="所选期间没有调用费用" />}
      </section>
      <section className="admin-panel"><div className="admin-section-heading"><h2>最近运行</h2><Link to={target('/admin/runs')}>运行历史 <ArrowRightOutlined /></Link></div>
        {run ? <><div className="admin-run-summary"><strong>#{run.id}</strong><span className="admin-scope">运行状态{run.status ?? '未记录'}</span></div><p className="admin-note">{new Date(run.run_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })} · 耗时{run.duration_seconds === null ? '未记录' : `${run.duration_seconds} 秒`}</p><div className="admin-run-output">{[{ label: '已摘要', value: run.summarized }, { label: '已聚类', value: run.clustered }, { label: '已评分', value: run.scored }].map(item => <div key={item.label}><strong>{item.value}</strong><span>{item.label}</span></div>)}</div></> : <Empty description="最近运行未记录" />}
        {data.exceptions.sources.length > 0 && <div className="admin-recent-errors"><small>当前来源异常</small>{data.exceptions.sources.slice(0, 3).map(item => <Link key={item.source_id} to={target('/admin/sources', { source_detail: item.source_id })}><i className="admin-dot error" /><strong>{item.name}</strong><span title={item.last_error ?? undefined}>{item.last_error || '错误详情未记录'}</span><ArrowRightOutlined /></Link>)}{data.exceptions.source_error_total > 3 && <Link to={target('/admin/sources', { health: 'error' })}>查看全部 {data.exceptions.source_error_total} 个异常信息源</Link>}</div>}
        <p className="admin-footnote">最近记录不代表实时管线健康；未采集字段保持未记录。</p>
      </section>
    </div>
    <details className="admin-analysis-details"><summary>进一步分析 · 处理状态与费用趋势</summary><div className="admin-overview-lower"><TrendChart title="文章处理状态趋势" total={`${data.period.articles} 篇`} data={data.processing_trend ?? []} series={processSeries} note="按文章入库时间分组，显示当前处理状态；历史阶段完成时间尚未记录。" /><TrendChart title="调用费用趋势" total={`$${money(cost.calls.cost_usd)}`} data={(data.call_purpose_trend ?? []).map(item => Object.fromEntries(Object.entries(item).map(([key, value]) => [key, key === 'day' ? value : Number(value)])) as { day: string; [key: string]: string | number })} series={data.purposes.map((item, index) => ({ key: item.name, label: item.name, color: colors[index % colors.length]! }))} format="money" onSelectDay={day => setSelectedDay({ kind: 'calls', day })} /></div></details>
    {selectedDay && <OverviewDayDetail key={`${selectedDay.kind}-${selectedDay.day}`} range={range} day={selectedDay.day} granularity={data.granularity ?? 'day'} kind={selectedDay.kind} onClose={() => setSelectedDay(null)} articleTarget={id => target('/admin/content', { tab: 'articles', article_detail: String(id) })} />}
  </div>
}
