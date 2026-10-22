import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Empty, Input, Pagination, Select, Table, Tabs, Tag, Typography } from 'antd'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { DOMAINS } from '../reader/presentation'
import MemberTasks, { MemberTaskDrawer } from './MemberTasks'
import TopicDetail from './TopicDetail'
import TopicEditor from './TopicEditor'
import { getTopics, type MutationReceipt, type TopicRow } from './topicApi'

export default function TopicsPage() {
  const [search, setSearch] = useSearchParams()
  const client = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [receipt, setReceipt] = useState<MutationReceipt | null>(null)
  const q = search.get('q') ?? ''
  const status = search.get('status') ?? ''
  const page = Math.max(1, Number(search.get('page')) || 1)
  const topicId = search.get('topic')
  const taskNumber = Number(search.get('member_task'))
  const taskId = Number.isSafeInteger(taskNumber) && taskNumber > 0 ? taskNumber : null
  const tab = search.get('view') === 'tasks' ? 'tasks' : 'topics'
  const query = useQuery({ queryKey: ['admin', 'topics', q, status, page], queryFn: ({ signal }) => getTopics({ q, status, page }, signal), retry: false })

  function update(patch: Record<string, string | null>) {
    const next = new URLSearchParams(search)
    for (const [key, value] of Object.entries(patch)) {
      if (value) next.set(key, value)
      else next.delete(key)
    }
    setSearch(next)
  }

  function saved(value: MutationReceipt) {
    setCreating(false)
    setReceipt(value)
    void client.invalidateQueries({ queryKey: ['admin', 'topics'] })
    void client.invalidateQueries({ queryKey: ['admin', 'topic', value.topic_id] })
    update({ topic: value.topic_id })
  }

  return <section aria-label="话题与成员管理" className="admin-history admin-topics">
    <div className="admin-history-intro"><div><h2>事件、议题与成员</h2><p>从原文核验归属，保留人工纠错和真实处理凭证。</p></div><Button type="primary" onClick={() => setCreating(true)}>人工建立话题</Button></div>
    {query.data && <Alert showIcon type={query.data.processing_enabled ? 'info' : 'warning'} title={query.data.processing_enabled ? '成员自动处理当前开启' : '成员自动处理当前关闭'} description="此处的人工修正单独留存记录，保存后可查看成员及派生版本的实时依赖状态。" />}
    {receipt && <Alert type="success" showIcon closable onClose={() => setReceipt(null)} title={`已保存人工操作 · 修订 r${receipt.revision}`} description={`操作编号：${receipt.mutation_id}`} />}
    <Tabs activeKey={tab} onChange={value => update({ view: value === 'tasks' ? 'tasks' : null })} items={[
      { key: 'topics', label: '话题列表', children: <div className="admin-topic-stack">
        <div className="admin-toolbar">
          <Input.Search aria-label="搜索话题" key={q} defaultValue={q} allowClear placeholder="搜索事件或议题" onSearch={value => update({ q: value.trim(), page: null })} />
          <Select aria-label="话题状态" value={status} onChange={value => update({ status: value, page: null })} options={[{ value: '', label: '全部话题状态' }, { value: 'active', label: '活跃' }, { value: 'archived', label: '已归档' }]} />
        </div>
        {query.isPending && <p role="status">正在加载话题…</p>}
        {query.isError && <Alert type="error" showIcon title="无法加载话题" action={<Button onClick={() => void query.refetch()}>重试读取</Button>} />}
        {query.data && <>
          <Typography.Text type="secondary">匹配 {query.data.total} 个话题</Typography.Text>
          <Table<TopicRow> rowKey="id" dataSource={query.data.items} pagination={false} scroll={{ x: 660 }} locale={{ emptyText: <Empty description="没有匹配的话题，可人工建立事件或议题" /> }} columns={[
            { title: '事件 / 议题', render: (_, row) => <><button className="admin-title-button" onClick={() => update({ topic: row.id })}>{row.title}</button><small>{row.kind === 'event' ? '事件' : '议题'} · r{row.revision}</small></> },
            { title: '领域', render: (_, row) => row.domains.map(domain => DOMAINS[domain] ?? domain).join(' / ') },
            { title: '状态', render: (_, row) => <Tag>{row.status === 'active' ? '活跃' : '已归档'}</Tag> },
            { title: '活跃成员', dataIndex: 'active_member_count' },
            { title: '操作', render: (_, row) => <Button type="link" aria-label={`查看话题 ${row.title}`} onClick={() => update({ topic: row.id })}>成员与证据</Button> },
          ]} />
          <Pagination current={page} pageSize={query.data.page_size} total={query.data.total} showSizeChanger={false} onChange={value => update({ page: String(value) })} />
        </>}
      </div> },
      { key: 'tasks', label: '成员任务', children: <MemberTasks onTask={id => update({ member_task: String(id) })} /> },
    ]} />
    {topicId && <TopicDetail key={topicId} id={topicId} onClose={() => update({ topic: null })} onTask={id => update({ member_task: String(id) })} onSaved={saved} />}
    {taskId !== null && <MemberTaskDrawer key={taskId} id={taskId} onClose={() => update({ member_task: null })} onTopic={id => update({ topic: id, member_task: null })} />}
    {creating && <TopicEditor mode="create" onClose={() => setCreating(false)} onSaved={saved} onRefresh={() => { setCreating(false); void query.refetch() }} />}
  </section>
}
