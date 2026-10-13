import { useQuery } from '@tanstack/react-query'
import { Button, Empty, Select, Table, Tabs } from 'antd'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import { fetchAdmin, type BacklogResult, type BacklogStage, type PageResult, type RunRecord } from './adminApi'
import { sharedRangeSearch, type AdminRange } from './adminFilters'
import RunDetail from './RunDetail'

const stageLabels: Record<BacklogStage, string> = { pending_summary: '待摘要', abandoned_summary: '摘要失败上限', pending_embedding: '待 Embedding', pending_score: '待评分' }

export default function RunsPage({ range }: { range: AdminRange }) {
  const [search, setSearch] = useSearchParams()
  const [detailId, setDetailId] = useState<number | null>(null)
  const tab = search.get('tab') === 'backlog' || search.get('tab') === 'tasks' ? search.get('tab')! : 'history'
  const stage = (Object.keys(stageLabels) as BacklogStage[]).find(value => value === search.get('stage')) ?? 'pending_summary'
  const page = Math.max(1, Number(search.get('page')) || 1)
  const runParams = new URLSearchParams({ start: range.start, end: range.end, page: String(page) })
  const runQuery = useQuery({ queryKey: ['admin', 'runs', range.start, range.end, page], queryFn: ({ signal }) => fetchAdmin<PageResult<RunRecord>>('runs', runParams, signal), enabled: tab === 'history', retry: false })
  const backlogParams = new URLSearchParams({ stage, page: String(page) })
  const backlogQuery = useQuery({ queryKey: ['admin', 'backlog', stage, page], queryFn: ({ signal }) => fetchAdmin<BacklogResult>('backlog', backlogParams, signal), enabled: tab === 'backlog', retry: false })

  function update(values: Record<string, string | null>) {
    const next = new URLSearchParams(search)
    for (const [key, value] of Object.entries(values)) {
      if (value === null) next.delete(key)
      else next.set(key, value)
    }
    setSearch(next)
  }

  function contentDetail(id: number, itemStage: BacklogStage) {
    const params = new URLSearchParams(sharedRangeSearch(search))
    const event = itemStage === 'pending_score'
    params.set('tab', event ? 'events' : 'articles')
    params.set(event ? 'event_detail' : 'article_detail', String(id))
    return { pathname: '/admin/content', search: params.toString() }
  }

  return <div className="admin-panel">
    <Tabs activeKey={tab} onChange={value => update({ tab: value, page: null })} items={[
      { key: 'history', label: '运行历史' }, { key: 'backlog', label: '待处理与失败' }, { key: 'tasks', label: '手动任务' },
    ]} />
    {tab === 'history' && <>
      <p className="admin-note">记录的是 AI 处理轮次。历史结束时间、阶段状态和关联费用未记录；单个信息源失败不代表整轮失败。</p>
      {runQuery.isPending && <p role="status">正在加载运行记录…</p>}
      {runQuery.isError && <div role="alert">运行记录加载失败。<Button onClick={() => void runQuery.refetch()}>重试</Button></div>}
      {runQuery.data && <Table rowKey="id" dataSource={runQuery.data.items} scroll={{ x: 650 }} locale={{ emptyText: <Empty description="所选期间没有运行记录" /> }} pagination={{ current: page, pageSize: runQuery.data.page_size, total: runQuery.data.total, showSizeChanger: false, onChange: next => update({ page: String(next) }) }} columns={[
        { title: 'ID', dataIndex: 'id' },
        { title: '记录时间', dataIndex: 'run_at', render: (value: string) => new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) },
        { title: '摘要 / 聚类 / 评分', render: (_, run: RunRecord) => `${run.summarized} / ${run.clustered} / ${run.scored}` },
        { title: '状态', render: (_, run: RunRecord) => run.status ?? '未记录' },
        { title: '耗时', render: (_, run: RunRecord) => run.duration_seconds === null ? '未记录' : `${run.duration_seconds} 秒` },
        { title: '操作', render: (_, run: RunRecord) => <Button size="small" onClick={() => setDetailId(run.id)}>详情</Button> },
      ]} />}
      <RunDetail id={detailId} onClose={() => setDetailId(null)} />
    </>}
    {tab === 'backlog' && <>
      <p className="admin-note">当前积压 · 不随页面日期范围变化。worker 处理期间，汇总与列表可能短暂不同。</p>
      <Select aria-label="积压阶段" value={stage} options={Object.entries(stageLabels).map(([value, label]) => ({ value, label }))} onChange={value => update({ stage: value, page: null })} />
      {backlogQuery.isPending && <p role="status">正在加载当前积压…</p>}
      {backlogQuery.isError && <div role="alert">当前积压加载失败。<Button onClick={() => void backlogQuery.refetch()}>重试</Button></div>}
      {backlogQuery.data && <>
        <p>待摘要 {backlogQuery.data.counts.pending_summaries} · 摘要失败上限 {backlogQuery.data.counts.abandoned_summaries} · 待 Embedding {backlogQuery.data.counts.pending_embeddings} · 待评分 {backlogQuery.data.counts.pending_scores}</p>
        <Table rowKey="id" dataSource={backlogQuery.data.items} scroll={{ x: 520 }} locale={{ emptyText: <Empty description="当前阶段没有积压" /> }} pagination={{ current: page, pageSize: backlogQuery.data.page_size, total: backlogQuery.data.total, showSizeChanger: false, onChange: next => update({ page: String(next) }) }} columns={[
          { title: 'ID', dataIndex: 'id' }, { title: '对象', dataIndex: 'title' }, { title: '来源', dataIndex: 'source_id', render: (value: string | null) => value ?? '—' }, { title: '阶段', render: () => stageLabels[stage] },
          { title: '详情', render: (_, item: BacklogResult['items'][number]) => <Link to={contentDetail(item.id, item.stage)}>查看{item.stage === 'pending_score' ? '事件' : '文章'} #{item.id}</Link> },
        ]} />
      </>}
    </>}
    {tab === 'tasks' && <Empty description="手动任务队列将在 M3-C 交付；当前没有历史任务记录。" />}
  </div>
}
