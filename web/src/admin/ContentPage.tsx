import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Empty, Input, Pagination, Select, Table, Tabs, Tag, Typography } from 'antd'
import { useSearchParams } from 'react-router-dom'

import type { AdminRange } from './adminFilters'
import { displayTime, getHistoryPage, type ArticleRow, type EventRow } from './adminHistoryApi'
import ArticleDetail from './ArticleDetail'
import EventDetail from './EventDetail'
import HistoryExport from './HistoryExport'

interface Props { range: AdminRange }

const articleStates = [
  { value: '', label: '全部处理状态' },
  { value: 'pending', label: '待处理' },
  { value: 'failed', label: '处理失败' },
  { value: 'summarized', label: '已摘要' },
  { value: 'embedded', label: '已嵌入' },
  { value: 'clustered', label: '已归入事件' },
]
const eventStates = [{ value: '', label: '全部处理状态' }, { value: 'pending', label: '待评分' }, { value: 'scored', label: '已评分' }]
const articleStateLabel = (value: string) => articleStates.find(option => option.value === value)?.label || value
const eventStateLabel = (value: string) => eventStates.find(option => option.value === value)?.label || value
const qualityLabels: Record<string, string> = { grounded: '证据充分', limited: '证据有限', review_limited: '审核受限', unrecorded: '未记录' }

function detailId(value: string | null): number | null {
  if (value === null) return null
  const number = Number(value)
  return Number.isSafeInteger(number) && number > 0 ? number : null
}

export default function ContentPage({ range }: Props) {
  const [search, setSearch] = useSearchParams()
  const tab = search.get('tab') === 'events' ? 'events' : 'articles'
  const page = Math.max(1, Number(search.get('page')) || 1)
  const filters = {
    page, page_size: 25,
    keyword: search.get('keyword') || undefined,
    source_id: search.get('source_id') || undefined,
    processing_status: search.get('processing_status') || undefined,
    sort: search.get('sort') || 'newest',
    time_basis: tab === 'articles' ? search.get('time_basis') || 'fetched_at' : undefined,
    lang: tab === 'articles' ? search.get('lang') || undefined : undefined,
    quality_status: tab === 'articles' ? search.get('quality_status') || undefined : undefined,
    time_status: tab === 'events' ? search.get('time_status') || 'reported' : undefined,
  }
  const query = useQuery({
    queryKey: ['admin', tab, range.start, range.end, filters],
    queryFn: ({ signal }) => getHistoryPage<ArticleRow | EventRow>(tab, range, filters, signal),
    retry: false,
  })

  function update(patch: Record<string, string | null>) {
    const next = new URLSearchParams(search)
    for (const [key, value] of Object.entries(patch)) {
      if (value) next.set(key, value)
      else next.delete(key)
    }
    if (!('page' in patch)) next.delete('page')
    setSearch(next)
  }

  const articleId = detailId(search.get('article_detail'))
  const eventId = detailId(search.get('event_detail'))
  const items = query.data?.items || []
  return <section aria-label="文章与事件历史查询" className="admin-history">
    <div className="admin-history-intro"><div><h2>内容查询</h2><p>报道时间和入库时间分开；事件按最早有效报道时间排序。</p></div><HistoryExport resource={tab} range={range} filters={filters} /></div>
    <Tabs activeKey={tab} onChange={value => update({ tab: value, keyword: null, processing_status: null, article_detail: null, event_detail: null })} items={[{ key: 'articles', label: '文章' }, { key: 'events', label: '事件' }]} />
    {filters.source_id && <div className="admin-filter-context">来源 ID：{filters.source_id} <Button size="small" onClick={() => update({ source_id: null })}>清除来源</Button></div>}
    <div className="admin-toolbar">
      <Input.Search key={`${tab}-${filters.keyword || ''}`} aria-label="内容关键词" placeholder={tab === 'articles' ? '搜索文章标题' : '搜索事件标题'} defaultValue={filters.keyword} allowClear onSearch={value => update({ keyword: value.trim() })} />
      <Input.Search key={`source-${filters.source_id || ''}`} aria-label="来源 ID 筛选" placeholder="来源 ID" defaultValue={filters.source_id} allowClear onSearch={value => update({ source_id: value.trim() })} />
      {tab === 'articles' && <Select aria-label="文章时间口径" value={filters.time_basis} options={[{ value: 'fetched_at', label: '入库时间' }, { value: 'published_at', label: '报道时间' }]} onChange={value => update({ time_basis: value })} />}
      {tab === 'events' && <Select aria-label="事件时间状态" value={filters.time_status} options={[{ value: 'reported', label: '有有效报道时间' }, { value: 'missing', label: '缺失报道时间' }]} onChange={value => update({ time_status: value })} />}
      <Select aria-label="处理状态" value={filters.processing_status || ''} options={tab === 'articles' ? articleStates : eventStates} onChange={value => update({ processing_status: value })} />
      {tab === 'articles' && <Select aria-label="文章语言" value={filters.lang || ''} options={[{ value: '', label: '全部语言' }, { value: 'zh', label: '中文' }, { value: 'en', label: '英文' }]} onChange={value => update({ lang: value })} />}
      {tab === 'articles' && <Select aria-label="内容质量" value={filters.quality_status || ''} options={[{ value: '', label: '全部质量状态' }, { value: 'grounded', label: '证据充分' }, { value: 'limited', label: '证据有限' }, { value: 'review_limited', label: '审核受限' }, { value: 'unrecorded', label: '未记录' }]} onChange={value => update({ quality_status: value })} />}
      <Select aria-label="时间排序" value={filters.sort} options={[{ value: 'newest', label: '最新优先' }, { value: 'oldest', label: '最早优先' }]} onChange={value => update({ sort: value })} />
    </div>
    {tab === 'events' && filters.time_status === 'missing' && <Alert className="admin-time-note" type="info" showIcon title="当前按系统发现时间筛选缺失报道时间的事件；发现时间不是报道时间。" />}
    {query.isPending && <p role="status">正在加载{tab === 'articles' ? '文章' : '事件'}…</p>}
    {query.isError && <Alert type="error" showIcon title="无法加载内容历史" action={<Button size="small" onClick={() => void query.refetch()}>重试</Button>} />}
    {query.isSuccess && <>
      <Typography.Text type="secondary">匹配 {query.data.total} {tab === 'articles' ? '篇文章' : '个事件'}</Typography.Text>
      {items.length ? tab === 'articles' ? <Table rowKey="id" dataSource={items as ArticleRow[]} pagination={false} scroll={{ x: 850 }} columns={[
        { title: '文章', key: 'article', render: (_: unknown, row: ArticleRow) => <><strong>{row.title_zh || row.title}</strong><small>#{row.id} · {qualityLabels[row.quality_status || 'unrecorded'] || row.quality_status}</small></> },
        { title: '来源', key: 'source', render: (_: unknown, row: ArticleRow) => row.source_name || row.source_id },
        { title: '报道 / 入库', key: 'times', width: 180, render: (_: unknown, row: ArticleRow) => <>{displayTime(row.published_at)}<small>入库 {displayTime(row.fetched_at)}</small></> },
        { title: '处理状态', key: 'status', width: 135, render: (_: unknown, row: ArticleRow) => <Tag>{articleStateLabel(row.processing_status)}</Tag> },
        { title: '事件', key: 'event', width: 80, render: (_: unknown, row: ArticleRow) => row.event_id ? `#${row.event_id}` : '未归属' },
        { title: '操作', key: 'action', width: 90, render: (_: unknown, row: ArticleRow) => <Button type="link" size="small" aria-label={`查看文章 ${row.id} 详情`} onClick={() => update({ article_detail: String(row.id) })}>详情</Button> },
      ]} /> : <Table rowKey="id" dataSource={items as EventRow[]} pagination={false} scroll={{ x: 760 }} columns={[
        { title: '事件', key: 'event', render: (_: unknown, row: EventRow) => <strong>{row.title || `事件 #${row.id}`}</strong> },
        { title: '最早 / 最新报道', key: 'times', width: 190, render: (_: unknown, row: EventRow) => <>{displayTime(row.earliest_published_at)}<small>最新 {displayTime(row.latest_published_at)}</small>{row.range_time_basis === 'first_seen_at' && <small>按发现时间纳入</small>}</> },
        { title: '文章 / 来源', key: 'counts', width: 130, render: (_: unknown, row: EventRow) => `${row.article_count} / ${row.source_count}` },
        { title: '评分', key: 'score', width: 95, render: (_: unknown, row: EventRow) => row.score_final ?? '未评分' },
        { title: '状态', key: 'status', width: 95, render: (_: unknown, row: EventRow) => eventStateLabel(row.processing_status) },
        { title: '操作', key: 'action', width: 90, render: (_: unknown, row: EventRow) => <Button type="link" size="small" aria-label={`查看事件 ${row.id} 详情`} onClick={() => update({ event_detail: String(row.id) })}>详情</Button> },
      ]} /> : <Empty description={tab === 'articles' ? '所选范围和筛选条件下没有文章' : filters.time_status === 'missing' ? '所选范围没有缺失报道时间且在期间发现的事件' : '所选范围没有首次报道的事件；旧事件新文章可在文章页查找'} />}
      <Pagination current={page} pageSize={25} total={query.data.total} showSizeChanger={false} onChange={value => update({ page: String(value) })} />
    </>}
    <ArticleDetail id={articleId} range={range} onClose={() => update({ article_detail: null })} onEvent={id => update({ tab: 'events', processing_status: null, article_detail: null, event_detail: String(id) })} />
    <EventDetail id={eventId} range={range} onClose={() => update({ event_detail: null })} onArticle={id => update({ tab: 'articles', processing_status: null, event_detail: null, article_detail: String(id) })} />
  </section>
}
