import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Drawer, Select, Table, Tag } from 'antd'
import { request } from '../reader/api'
import { SCOPES } from '../reader/presentation'
import { safeHref } from '../links'

interface Version { id: number; kind: string; status: string; reason: string | null; input_fingerprint: string; payload?: object; review_evidence?: object }
interface Candidate { id: number; title: string; source_id: string; current_material_id: number | null; canonical_content_id: number | null; derivations: Version[] }
interface Task { id: number; queue: string; kind: string; status: string; source_id: string | null; article_id: number | null; failures: number; due_at: string; last_error: string | null; attempt_records: { id: number; status: string; error: string | null }[] }
interface Source { id: string; name: string; configured_owner: string; runtime_initialized: boolean; runtime_owner: string | null; stages: Record<string, boolean>; last_success_at: string | null; last_new_item_at: string | null; sampled_material_versions: number; material_failure_fraction: number | null }
interface Detail { id: number; title: string; url: string; current_material_id: number | null; materials: { id: number; scope: string; access_status: string; retrieved_at: string; completeness: string; completeness_basis: string; paragraphs: { text: string }[] }[]; observations: { id: number; source_id: string; observed_at: string; metadata: object }[]; derivations: Version[]; calls: { id: string; stage: string; phase: string; status: string; task_id: number | null; known_cost_usd: number | null; reserved_usd: string | null; error: string | null }[] }
const STATES: Record<string, string> = { pending: '待处理', running: '领取中', generating: '生成中', completed: '已完成', ready: '已审核', rejected: '内容不入选', failed: '技术失败', blocked: '处理阻塞', retry_wait: '等待重试／依赖', budget_deferred: '预算暂缓', review_pending: '草稿待审核', invalidated: '版本已失效' }
const time = (value: string | null) => value ? new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) : '未记录'
export default function R1StatusPanel() {
  const [queue, setQueue] = useState(''); const [selected, setSelected] = useState<number | null>(null)
  const contents = useQuery({ queryKey: ['admin', 'r1-contents'], queryFn: ({ signal }) => request<{ items: Candidate[] }>('/api/admin/r1/contents?limit=25', { signal }), retry: false })
  const tasks = useQuery({ queryKey: ['admin', 'r1-tasks', queue], queryFn: ({ signal }) => request<{ items: Task[] }>(`/api/admin/r1/tasks?limit=50${queue ? `&queue=${queue}` : ''}`, { signal }), retry: false })
  const sources = useQuery({ queryKey: ['admin', 'r1-sources'], queryFn: ({ signal }) => request<{ items: Source[] }>('/api/admin/r1/sources', { signal }), retry: false })
  const detail = useQuery({ queryKey: ['admin', 'r1-detail', selected], enabled: selected !== null, queryFn: ({ signal }) => request<Detail>(`/api/admin/r1/contents/${selected}`, { signal }), retry: false })
  return <section aria-label="R1 内容与任务状态" className="admin-r1-panel">
    <div className="admin-list-header"><div><h2>R1 独立内容与任务</h2><p>以下为当前实际状态，不受旧轮次日期筛选影响。只读检查，不启动付费处理。</p></div><Button onClick={() => { void contents.refetch(); void tasks.refetch(); void sources.refetch() }}>刷新 R1 状态</Button></div>
    <Alert type="info" showIcon title="技术失败、预算暂缓与内容不入选分别记录；材料就绪不代表卡片已获准发布。历史未关联费用仍保留为未记录。" />
    {(contents.error || tasks.error || sources.error) && <p role="alert">部分 R1 状态暂时无法读取，请检查接口部署和网络后刷新。</p>}
    <h3>最近 25 个候选</h3><Table<Candidate> size="small" rowKey="id" dataSource={contents.data?.items ?? []} loading={contents.isPending} pagination={false} scroll={{ x: 720 }} columns={[
      { title: '内容', dataIndex: 'title', render: (_, row) => <Button type="link" onClick={() => setSelected(row.id)}>#{row.id} {row.title}</Button> },
      { title: '来源', dataIndex: 'source_id' },
      { title: '材料', render: (_, row) => row.current_material_id ? `版本 #${row.current_material_id}` : '尚未取得' },
      { title: '派生阶段', render: (_, row) => row.canonical_content_id ? `同一内容 → #${row.canonical_content_id}` : row.derivations.length ? row.derivations.map(v => <div key={v.id}><Tag>{v.kind}</Tag>{STATES[v.status] ?? v.status}{v.reason ? ` · ${v.reason}` : ''}</div>) : '尚无整理结果；不是内容拒绝' },
    ]} />
    <div className="admin-list-header"><h3>最近 50 条任务</h3><Select aria-label="R1 任务队列" value={queue} onChange={setQueue} options={[{ value: '', label: '全部队列' }, { value: 'discovery', label: '发现' }, { value: 'material', label: '材料' }, { value: 'paid', label: '卡片与准入' }, { value: 'guide', label: '导读' }]} /></div>
    <Table<Task> size="small" rowKey="id" dataSource={tasks.data?.items ?? []} loading={tasks.isPending} pagination={false} scroll={{ x: 740 }} columns={[
      { title: '任务／阶段', render: (_, row) => `#${row.id} · ${row.kind}` }, { title: '状态', render: (_, row) => STATES[row.status] ?? row.status },
      { title: '对象', render: (_, row) => row.article_id ? <Button type="link" onClick={() => setSelected(row.article_id)}>内容 #{row.article_id}</Button> : row.source_id ?? '未关联' },
      { title: '故障次数', dataIndex: 'failures' }, { title: '下次可领取', render: (_, row) => time(row.due_at) }, { title: '最近错误／尝试', render: (_, row) => <details><summary>{row.last_error ?? '无已记录错误'}</summary>{row.attempt_records.map(a => <p key={a.id}>#{a.id} {a.status} {a.error}</p>)}</details> },
    ]} />
    <h3>来源：实际成功与新增分别检查</h3><Table<Source> size="small" rowKey="id" dataSource={sources.data?.items ?? []} pagination={false} scroll={{ x: 900 }} columns={[
      { title: '来源', render: (_, row) => `${row.name} · ${row.id}` }, { title: '所有权', render: (_, row) => `配置 ${row.configured_owner} / 运行 ${row.runtime_owner ?? '未初始化'}` }, { title: '阶段开关', render: (_, row) => Object.entries(row.stages).filter(([, on]) => on).map(([stage]) => stage).join(' / ') || '全部关闭' },
      { title: '最近实际成功', render: (_, row) => time(row.last_success_at) }, { title: '最近观察到新条目', render: (_, row) => time(row.last_new_item_at) }, { title: '材料失败', render: (_, row) => row.material_failure_fraction === null ? '尚无样本' : `${(100 * row.material_failure_fraction).toFixed(1)}% / 最近 ${row.sampled_material_versions} 个材料版本` },
    ]} />
    <Drawer title={detail.data?.title ?? 'R1 材料与处理记录'} open={selected !== null} onClose={() => setSelected(null)} size="large" width="min(900px, 100vw)">
      {detail.isPending && <p role="status">正在读取材料、尝试和费用关联…</p>}{detail.error && <p role="alert">读取失败。<Button onClick={() => void detail.refetch()}>重试</Button></p>}
      {detail.data && <><a href={safeHref(detail.data.url)} target="_blank" rel="noopener noreferrer">打开实际来源 ↗</a><h3>材料版本（最近 20 个）</h3>{detail.data.materials.map(m => <details key={m.id}><summary>#{m.id} {m.id === detail.data?.current_material_id ? '当前采用 · ' : ''}{SCOPES[m.scope] ?? m.scope} · {m.access_status} · {time(m.retrieved_at)}</summary><p>完整度：{m.completeness} · {m.completeness_basis}</p>{m.paragraphs.map((p, i) => <p key={i} style={{ whiteSpace: 'pre-wrap' }}>{p.text}</p>)}</details>)}<h3>派生与审核凭证（最近 100 个）</h3>{detail.data.derivations.map(v => <details key={v.id}><summary>{v.kind} · {STATES[v.status] ?? v.status} · {v.reason}</summary><pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(v, null, 2)}</pre></details>)}<h3>已发生调用与未知费用</h3>{detail.data.calls.length === 0 ? <p>没有可关联的物理调用记录；不把缺记录当作零成本。</p> : detail.data.calls.map(call => <p key={call.id}>{call.stage}/{call.phase} · 任务 {call.task_id ?? '未关联'} · {call.status} · {call.known_cost_usd === null ? '费用未知' : `$${call.known_cost_usd.toFixed(6)}`}{call.reserved_usd ? ` · 仍预留 $${call.reserved_usd}` : ''} · {call.error}</p>)}<h3>来源观察（最近 100 个）</h3>{detail.data.observations.map(o => <details key={o.id}><summary>{o.source_id} · {time(o.observed_at)}</summary><pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(o.metadata, null, 2)}</pre></details>)}</>}
    </Drawer>
  </section>
}
