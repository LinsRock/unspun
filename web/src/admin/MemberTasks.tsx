import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Descriptions, Drawer, Empty, Input, Pagination, Select, Table, Tag } from 'antd'
import { useState } from 'react'

import { displayTime } from './adminHistoryApi'
import { getMemberTask, getMemberTasks, memberCost, type MemberCall, type MemberTask } from './topicApi'

const TASK_KINDS = { topic_recall: '成员召回', topic_judge: '成员判断', topic_review: '成员审核' }
const TASK_STATES: Record<string, string> = { pending: '待处理', running: '运行中', retry_wait: '等待依赖或重试', budget_deferred: '预算暂缓', blocked: '已阻塞', completed: '已完成', failed: '已失败', independent: '独立内容', draft: '判断草稿', applied: '已应用', rejected: '未通过', stale: '已过时', reserved: '已预留', usage_unknown: '用量未知', responded: '已返回', settled_without_result: '已结算但无结果', lease_expired: '租约过期', deferred: '已延期' }
const state = (value: string) => TASK_STATES[value] ?? value

export function JsonRecord({ value }: { value: unknown }) {
  return <pre className="admin-json-detail admin-topic-json">{JSON.stringify(value, null, 2)}</pre>
}

export default function MemberTasks({ topicId, articleId: initialArticleId, onTask }: { topicId?: string; articleId?: number; onTask: (id: number) => void }) {
  const [articleId, setArticleId] = useState(initialArticleId)
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(1)
  const [filterError, setFilterError] = useState<string | null>(null)
  const query = useQuery({ queryKey: ['admin', 'member-tasks', topicId, articleId, status, page], queryFn: ({ signal }) => getMemberTasks({ topic_id: topicId, article_id: articleId, status, page }, signal), retry: false })
  return <section aria-label="成员任务记录" className="admin-topic-stack">
    <p className="admin-note">查看已记录的召回、判断与审核任务，保留原始状态和逐笔费用。</p>
    <div className="admin-toolbar">
      <Input.Search aria-label="任务内容 ID" key={articleId ?? 'all'} defaultValue={articleId} placeholder="按内容 ID 查询" allowClear onSearch={value => {
        const id = value.trim() ? Number(value) : undefined
        if (id !== undefined && (!Number.isSafeInteger(id) || id < 1)) { setFilterError('请输入有效的内容 ID。'); return }
        setFilterError(null); setArticleId(id); setPage(1)
      }} />
      <Select aria-label="成员任务状态" value={status} onChange={value => { setStatus(value); setPage(1) }} options={[{ value: '', label: '全部任务状态' }, ...['pending', 'running', 'retry_wait', 'budget_deferred', 'blocked', 'completed', 'failed'].map(value => ({ value, label: state(value) }))]} />
    </div>
    {filterError && <Alert type="error" title={filterError} />}
    {query.isError && <Alert type="error" showIcon title="无法加载成员任务" action={<Button onClick={() => void query.refetch()}>重试读取</Button>} />}
    {query.isPending && <p role="status">正在读取成员任务…</p>}
    {query.data && <>
      <Table<MemberTask> size="small" rowKey="id" dataSource={query.data.items} pagination={false} scroll={{ x: 720 }} locale={{ emptyText: <Empty description="没有匹配的成员任务" /> }} columns={[
        { title: '任务', render: (_, row) => <Button type="link" onClick={() => onTask(row.id)}>#{row.id} · {TASK_KINDS[row.kind] ?? row.kind}</Button> },
        { title: '状态', render: (_, row) => <Tag color={row.status === 'failed' || row.status === 'blocked' ? 'warning' : undefined}>{state(row.status)}</Tag> },
        { title: '内容', render: (_, row) => row.article_id === null ? '未关联' : `#${row.article_id}` },
        { title: '尝试 / 失败', render: (_, row) => `${row.attempts} / ${row.failures}` },
        { title: '创建时间', render: (_, row) => displayTime(row.created_at) },
        { title: '最近错误', render: (_, row) => row.last_error || '无已记录错误' },
      ]} />
      <Pagination current={page} pageSize={query.data.page_size} total={query.data.total} showSizeChanger={false} onChange={setPage} />
    </>}
  </section>
}

export function MemberTaskDrawer({ id, onClose, onTopic }: { id: number; onClose: () => void; onTopic: (id: string) => void }) {
  const query = useQuery({ queryKey: ['admin', 'member-task', id], queryFn: ({ signal }) => getMemberTask(id, signal), retry: false })
  const data = query.data
  return <Drawer title={`成员任务 #${id}`} open onClose={onClose} size={Math.min(960, window.innerWidth)} className="admin-detail-drawer">
    {query.isPending && <p role="status">正在读取判断、审核与费用…</p>}
    {query.isError && <Alert type="error" showIcon title="无法加载成员任务详情" action={<Button onClick={() => void query.refetch()}>重试读取</Button>} />}
    {data && <div className="admin-topic-stack">
      <Descriptions bordered size="small" column={1} items={[
        { key: 'kind', label: '任务类型', children: TASK_KINDS[data.task.kind] ?? data.task.kind },
        { key: 'state', label: '任务状态', children: state(data.task.status) },
        { key: 'article', label: '内容 / 来源', children: `#${data.task.article_id ?? '未关联'} · ${data.task.source_id ?? '未关联'}` },
        { key: 'version', label: '策略版本', children: data.task.strategy_version },
        { key: 'created', label: '创建 / 结束', children: `${displayTime(data.task.created_at)} / ${displayTime(data.task.finished_at)}` },
        { key: 'error', label: '最近错误', children: data.task.last_error ?? '无已记录错误' },
      ]} />
      <section aria-label="任务费用汇总"><h3>本任务费用</h3>
        <div className="admin-topic-costs">
          <div><small>已知费用小计</small><strong>{memberCost(data.costs.known_usd)}</strong></div>
          <div><small>未解决的全额预留</small><strong>{memberCost(data.costs.held_usd)}</strong></div>
          <div><small>未知请求 / 物理请求</small><strong>{data.costs.unknown_requests} / {data.costs.physical_requests}</strong></div>
        </div>
        <p className="admin-note">仅汇总当前物理任务；同一内容的判断与审核任务分别记录费用。</p>
        {data.costs.unknown_requests > 0 && <Alert type="warning" showIcon title="费用尚未完整确认" description="已知小计不包含未知请求的实际费用；未解决的预留仍独立保留。" />}
        {data.costs.physical_requests === 0 && <p className="admin-note">没有关联的物理调用记录；这不能证明历史费用为零。</p>}
      </section>
      <section><h3>原始判断与审核</h3><p className="admin-note">共 {data.judgments_total} 条，最多展示 {data.record_limit} 条。人工成员修正另见话题修订记录。</p>
        {data.judgments.length ? data.judgments.map(judgment => <details className="admin-topic-record" key={judgment.input_fingerprint}>
          <summary>内容 #{judgment.article_id} · {state(judgment.status)} · 话题 r{judgment.topic_revision}{judgment.applied_revision !== null ? ` → r${judgment.applied_revision}` : ''}</summary>
          <p>判断任务 #{judgment.task_id} · {displayTime(judgment.created_at)}</p>
          <Button type="link" onClick={() => onTopic(judgment.topic_id)}>查看关联话题</Button>
          <h4>判断原文</h4><JsonRecord value={judgment.decision} />
          <h4>审核原文</h4>{judgment.review ? <JsonRecord value={judgment.review} /> : <p>未记录审核，不能视为通过。</p>}
          <p className="admin-topic-id">输入指纹：{judgment.input_fingerprint}</p>
        </details>) : <Empty description="尚无可关联的成员判断" />}
      </section>
      <section><h3>物理调用与逐笔费用</h3><p className="admin-note">共 {data.calls_total} 条，最多展示 {data.record_limit} 条；上方费用汇总涵盖本任务全部调用。</p>
        <Table<MemberCall> size="small" rowKey="id" pagination={false} dataSource={data.calls} scroll={{ x: 1100 }} locale={{ emptyText: '没有可关联的物理调用记录' }} columns={[
          { title: '物理调用 / 阶段', width: 240, render: (_, call) => <><span className="admin-topic-id">{call.id}</span><small>{call.stage ?? '未记录阶段'} / {call.phase ?? '未记录阶段'} · {call.model}</small></> },
          { title: '状态', width: 130, render: (_, call) => <>{state(call.status)}<small>HTTP {call.http_status ?? '未记录'}</small></> },
          { title: '已知费用', width: 125, render: (_, call) => memberCost(call.known_cost_usd) },
          { title: '未解决预留', width: 125, render: (_, call) => call.reserved_usd === null ? '无未解决预留' : memberCost(call.reserved_usd) },
          { title: '任务 / 尝试', width: 130, render: (_, call) => `#${call.task_id ?? '未关联'} / #${call.task_attempt_id ?? '未关联'}` },
          { title: '凭证关联', render: (_, call) => <details><summary>提供方与时间</summary><p className="admin-topic-id">提供方 ID：{call.provider_generation_id ?? '未记录'}</p><p>{displayTime(call.started_at)} → {displayTime(call.ended_at)}</p><p>{call.error ?? '无已记录错误'}</p></details> },
        ]} />
      </section>
      <section><h3>尝试记录</h3><p className="admin-note">共 {data.attempts_total} 条，最多展示 {data.record_limit} 条。</p>
        {data.attempts.length ? data.attempts.map(attempt => <details className="admin-topic-record" key={attempt.id}><summary>尝试 #{attempt.id} · {state(attempt.status)} · 领取版本 {attempt.claim_version}</summary><p>{displayTime(attempt.started_at)} → {displayTime(attempt.ended_at)}</p><p>处理者：{attempt.worker}</p><p>{attempt.error ?? '无已记录错误'}</p></details>) : <p>尚无尝试记录。</p>}
      </section>
      <details className="admin-topic-record"><summary>任务原始结果</summary>{data.task.result ? <JsonRecord value={data.task.result} /> : <p>未记录结果。</p>}</details>
    </div>}
  </Drawer>
}
