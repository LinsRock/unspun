import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Empty, Input, Pagination, Select, Table, Tag, Typography } from 'antd'
import { Link, useSearchParams } from 'react-router-dom'

import type { AdminRange } from './adminFilters'
import { sharedRangeSearch } from './adminFilters'
import { displayTime, getHistoryPage, type HistoryPage, type SourceRow } from './adminHistoryApi'
import HistoryExport from './HistoryExport'
import FilterContext from './FilterContext'
import SourceDetail from './SourceDetail'

interface Props { range: AdminRange }
interface SourcePageData extends HistoryPage<SourceRow> {
  summary?: { configured_total: number; enabled_total: number; successful_sources: number; productive_sources: number; failed_sources: number }
}

const sorts = [
  { value: 'health', label: '异常优先' },
  { value: 'articles', label: '文章产出' },
  { value: 'failure_rate', label: '失败率' },
  { value: 'last_success', label: '最近成功时间' },
  { value: 'name', label: '名称' },
]

function healthText(row: SourceRow): string {
  if (row.health === 'no_runs') return '从未抓取'
  if (row.health === 'error') return '最近一次抓取失败'
  return '最近一次抓取成功'
}

function periodText(row: SourceRow): string {
  if (row.successful_fetches + row.failed_fetches === 0) return '期间无抓取记录'
  if (row.period_latest_status === 'ok' && row.new_articles === 0) return '成功但无新文章'
  return `${row.successful_fetches} 成功 / ${row.failed_fetches} 失败`
}

export default function SourcesPage({ range }: Props) {
  const [search, setSearch] = useSearchParams()
  const page = Math.max(1, Number(search.get('page')) || 1)
  const filters = {
    page, page_size: 25,
    sort: search.get('sort') || 'health',
    keyword: search.get('keyword') || undefined,
    lang: search.get('lang') || undefined,
    region: search.get('region') || undefined,
    kind: search.get('kind') || undefined,
    configured: search.get('configured') || undefined,
    enabled: search.get('enabled') || undefined,
    health: search.get('health') || undefined,
  }
  const query = useQuery({
    queryKey: ['admin', 'sources', range.start, range.end, filters],
    queryFn: ({ signal }) => getHistoryPage<SourceRow>('sources', range, filters, signal) as Promise<SourcePageData>,
    retry: false,
  })

  function update(key: string, value: string) {
    const next = new URLSearchParams(search)
    if (value) next.set(key, value)
    else next.delete(key)
    if (key !== 'page') next.delete('page')
    setSearch(next)
  }

  const items = query.data?.items || []
  const summary = query.data?.summary
  const filtered = Boolean(filters.keyword || filters.health || filters.lang || filters.region || filters.kind || filters.configured || filters.enabled)
  return <section aria-label="信息源历史查询" className="admin-sources">
    {summary && <div className="admin-source-dashboard">
      <div className="admin-source-dashboard-scope">{filtered ? '统计范围：当前筛选结果' : '统计范围：全部来源'}</div>
      <div className="admin-source-dashboard-body">
        <div className="admin-source-config"><span className="admin-stat-scope">当前配置</span><span className="admin-stat-label">配置中的信息源</span><strong>{summary.configured_total.toLocaleString()}<small>个</small></strong><div className="admin-source-enabled"><span><i className="admin-dot" />已启用 <b>{summary.enabled_total}</b></span><span>未启用 <b>{summary.configured_total - summary.enabled_total}</b></span></div></div>
        <div className="admin-source-period"><span className="admin-stat-scope">所选期间 · 来源数</span><div className="admin-source-period-stats">
          <div><span className="admin-stat-label">抓取成功</span><strong>{summary.successful_sources.toLocaleString()}<small>个</small></strong><small>至少成功抓取 1 次</small></div>
          <div><span className="admin-stat-label">有新文章</span><strong>{summary.productive_sources.toLocaleString()}<small>个</small></strong><small>至少入库 1 篇新文章</small></div>
          <div className={summary.failed_sources ? 'has-failures' : ''}><span className="admin-stat-label">发生抓取失败</span><strong>{summary.failed_sources.toLocaleString()}<small>个</small></strong><small>至少失败 1 次</small></div>
        </div></div>
      </div>
    </div>}
    <div className="admin-history">
    <div className="admin-toolbar">
      <Input.Search key={filters.keyword || ''} aria-label="搜索信息源" placeholder="搜索名称或 ID" defaultValue={filters.keyword} onSearch={value => update('keyword', value.trim())} allowClear />
      <Select aria-label="来源状态" value={filters.health || ''} options={[{ value: '', label: '全部状态' }, { value: 'error', label: '最近失败' }, { value: 'ok', label: '最近成功' }, { value: 'no_runs', label: '从未抓取' }]} onChange={value => update('health', value)} />
      <details className="admin-more-filters" key={`advanced-${filters.lang}-${filters.region}-${filters.kind}-${filters.configured}-${filters.enabled}`} open={Boolean(filters.lang || filters.region || filters.kind || filters.configured || filters.enabled)}><summary>更多筛选</summary><div className="admin-more-filter-fields">      <Select aria-label="来源语言" value={filters.lang || ''} options={[{ value: '', label: '全部语言' }, { value: 'zh', label: '中文' }, { value: 'en', label: '英文' }]} onChange={value => update('lang', value)} />
      <Select aria-label="来源地区" value={filters.region || ''} options={[{ value: '', label: '全部地区' }, ...['cn-mainland', 'hk-tw', 'us', 'eu', 'jp', 'me', 'intl'].map(value => ({ value, label: value }))]} onChange={value => update('region', value)} />
      <Select aria-label="来源类型" value={filters.kind || ''} options={[{ value: '', label: '全部类型' }, ...['wire', 'public', 'commercial', 'state', 'independent', 'community', 'academic', 'official'].map(value => ({ value, label: value }))]} onChange={value => update('kind', value)} />
      <Select aria-label="配置状态" value={filters.configured || ''} options={[{ value: '', label: '全部配置' }, { value: 'true', label: '当前配置' }, { value: 'false', label: '已移除' }]} onChange={value => update('configured', value)} />
      <Select aria-label="启用状态" value={filters.enabled || ''} options={[{ value: '', label: '全部启用状态' }, { value: 'true', label: '已启用' }, { value: 'false', label: '未启用' }]} onChange={value => update('enabled', value)} />
</div></details>
      <Select aria-label="来源排序" value={filters.sort} options={sorts} onChange={value => update('sort', value)} />
    </div>
    <FilterContext keys={['keyword', 'health', 'lang', 'region', 'kind', 'configured', 'enabled']} labels={{ keyword: '搜索', health: '健康', lang: '语言', region: '地区', kind: '类型', configured: '当前配置', enabled: '已启用' }} />
    {query.isPending && <p role="status">正在加载信息源…</p>}
    {query.isError && <Alert type="error" showIcon title="无法加载信息源" action={<Button size="small" onClick={() => void query.refetch()}>重试</Button>} />}
    {query.isSuccess && <>
      <div className="admin-results-heading"><Typography.Text type="secondary">{filtered ? '匹配' : '共'} {query.data.total} 个来源</Typography.Text><HistoryExport resource="sources" range={range} filters={filters} /></div>
      {items.length ? <Table rowKey="id" dataSource={items} pagination={false} scroll={{ x: 820 }} columns={[
        { title: '来源', key: 'source', render: (_: unknown, row: SourceRow) => <><button className="admin-title-button" onClick={() => update('source_detail', row.id)}>{row.name || row.id}</button><small>{row.configured ? [row.lang, row.region, row.kind].filter(Boolean).join(' · ') : '已移除 · 历史配置未记录'}</small></> },
        { title: '当前抓取状态', key: 'health', render: (_: unknown, row: SourceRow) => <><Tag color={row.health === 'error' ? 'error' : row.health === 'no_runs' ? 'default' : 'success'}>{healthText(row)}</Tag><small>{periodText(row)}</small></> },
        { title: '新文章', dataIndex: 'new_articles', width: 90 },
        { title: '成功率', key: 'rate', width: 100, render: (_: unknown, row: SourceRow) => row.success_rate === null ? '暂无记录' : <div className="admin-rate"><b>{(row.success_rate * 100).toFixed(1)}%</b><span><i style={{ width: `${row.success_rate * 100}%`, background: row.success_rate < 0.9 ? 'var(--amber)' : 'var(--accent)' }} /></span></div> },
        { title: '最近成功', dataIndex: 'last_success_at', width: 175, render: displayTime },
        { title: '最近错误', key: 'error', width: 190, ellipsis: true, render: (_: unknown, row: SourceRow) => row.last_error ? <>{row.last_error}<small>{displayTime(row.last_error_at)}</small></> : '未记录' },
        { title: '操作', key: 'actions', width: 140, render: (_: unknown, row: SourceRow) => <div className="admin-row-actions"><Button type="link" size="small" onClick={() => update('source_detail', row.id)}>详情</Button><Link aria-label={`查看 ${row.name || row.id} 的文章`} to={{ pathname: '/admin/content', search: `${sharedRangeSearch(search)}&tab=articles&source_id=${encodeURIComponent(row.id)}` }}>查看文章</Link></div> },
      ]} /> : <Empty description="所选范围和筛选条件下没有来源记录" />}
      <Pagination current={page} pageSize={25} total={query.data.total} showSizeChanger={false} onChange={value => update('page', String(value))} />
    </>}
    </div>
    <SourceDetail id={search.get('source_detail')} range={range} search={search} onClose={() => update('source_detail', '')} />
  </section>
}
