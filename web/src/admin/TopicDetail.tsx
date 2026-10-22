import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Descriptions, Drawer, Empty, Pagination, Tabs, Tag } from 'antd'
import { useState } from 'react'

import { DOMAINS, SCOPES } from '../reader/presentation'
import { displayTime, safeExternalUrl } from './adminHistoryApi'
import MemberTasks, { JsonRecord } from './MemberTasks'
import TopicEditor from './TopicEditor'
import { RELATIONS, VOICES } from './topicLabels'
import { getTopic, type MutationReceipt, type TopicDetail as Detail, type TopicMember, type TopicVersion, type VersionCheck } from './topicApi'

const CHECK_REASONS: Record<string, string> = { member_removed: '成员已移除', member_input_unavailable: '成员材料当前不可用', member_input_changed: '成员材料或审核已变化', superseded: '已有后续版本', retracted: '已撤回', update_input_unavailable: '更新依据当前不可用', update_input_changed: '更新依据已变化', topic_unavailable: '话题当前不可用', derivation_input_unavailable: '派生依据当前不可用', derivation_input_changed: '派生依据已变化', derivation_contract_changed: '派生契约已变化', invalid_stored_contract: '保留的派生契约无效' }

function Check({ check }: { check: VersionCheck }) {
  return <span><Tag color={check.valid ? 'success' : 'warning'}>{check.valid ? '依赖有效' : '已失效'}</Tag>{!check.valid && <small>{check.reasons.map(reason => CHECK_REASONS[reason] ?? reason).join('；')}</small>}</span>
}

function RetainedVersions({ data }: { data: Detail }) {
  function record(version: TopicVersion, index: number) {
    const label = version.kind === 'overview' ? '概览草稿' : version.kind === 'guide' ? '导读草稿' : '话题更新'
    return <details className="admin-topic-record" key={`${version.kind ?? version.update_id}-${version.revision}-${index}`}>
      <summary>{label} · r{version.revision} · {version.status === 'retracted' ? '已撤回' : version.status === 'draft' ? '保留草稿' : '保留版本'} <Check check={version.check} /></summary>
      <JsonRecord value={version.payload} />
      {version.contract && <details><summary>该草稿记录的契约</summary><JsonRecord value={version.contract} /></details>}
    </details>
  }
  return <section className="admin-topic-stack" aria-label="保留的派生版本">
    <Alert type="info" showIcon title="旧版本保留，按当前依赖实时检查" description="依赖有效只说明材料与修订仍匹配，不代表语义审核通过或内容已发布。人工修正后请查看此处的失效原因。" />
    <h3>话题更新</h3><p className="admin-note">共 {data.updates_total} 个版本，最多展示 {data.version_record_limit} 个。</p>
    {data.updates.length ? data.updates.map(record) : <Empty description="尚无话题更新版本" />}
    <h3>概览与导读草稿</h3><p className="admin-note">共 {data.derivations_total} 个版本，最多展示 {data.version_record_limit} 个。</p>
    {data.derivations.length ? data.derivations.map(record) : <Empty description="尚无派生草稿" />}
  </section>
}

interface Props { id: string; onClose: () => void; onTask: (id: number) => void; onSaved: (receipt: MutationReceipt) => void }

export default function TopicDetail({ id, onClose, onTask, onSaved }: Props) {
  const [memberPage, setMemberPage] = useState(1)
  const [historyPage, setHistoryPage] = useState(1)
  const [tab, setTab] = useState('members')
  const [taskArticleId, setTaskArticleId] = useState<number>()
  const [editor, setEditor] = useState<{ mode: 'member' | 'remove'; topic: Detail['topic']; member?: TopicMember } | null>(null)
  const query = useQuery({ queryKey: ['admin', 'topic', id, memberPage, historyPage], queryFn: ({ signal }) => getTopic(id, memberPage, historyPage, signal), retry: false })
  const data = query.data

  function refresh() {
    setEditor(null)
    void query.refetch()
  }

  return <>
    <Drawer title={data?.topic.title ?? '话题详情'} open onClose={onClose} size={Math.min(960, window.innerWidth)} className="admin-detail-drawer">
      {query.isPending && <p role="status">正在读取成员、修订与派生版本…</p>}
      {query.isError && <Alert type="error" showIcon title="无法加载话题详情" action={<Button onClick={() => void query.refetch()}>重试读取</Button>} />}
      {data && query.isFetching && <p role="status">正在刷新当前修订，请稍候再编辑…</p>}
      {data && <div className="admin-topic-stack">
        <Descriptions size="small" bordered column={1} items={[
          { key: 'id', label: '话题', children: <span className="admin-topic-id">{data.topic.id}</span> },
          { key: 'kind', label: '类型 / 状态', children: `${data.topic.kind === 'event' ? '事件' : '议题'} · ${data.topic.status === 'active' ? '活跃' : '已归档'}` },
          { key: 'domains', label: '领域', children: data.topic.domains.map(domain => DOMAINS[domain] ?? domain).join(' / ') },
          { key: 'revision', label: '当前修订', children: `r${data.topic.revision} · 更新于 ${displayTime(data.topic.updated_at)}` },
        ]} />
        <Tabs activeKey={tab} onChange={value => { setTab(value); if (value === 'tasks') setTaskArticleId(undefined) }} items={[
          { key: 'members', label: `成员与证据（${data.members_total}）`, children: <section className="admin-topic-stack" aria-label="话题成员与证据">
            <div className="admin-topic-inline"><Button type="primary" disabled={query.isFetching || query.isError} onClick={() => setEditor({ mode: 'member', topic: data.topic })}>补充成员</Button><span className="admin-note">包含保留的已移除记录；保存时核验当前材料与修订。</span></div>
            {data.members.length ? data.members.map(member => {
              const href = safeExternalUrl(member.url)
              return <article className="admin-topic-member" key={member.article_id}>
                <div className="admin-topic-member-heading"><div><h3>{member.title}</h3><small>内容 #{member.article_id} · {member.source_id} · 材料 #{member.material_id}</small></div><Tag color={member.active ? undefined : 'default'}>{member.active ? RELATIONS[member.relation] : '已移除'}</Tag></div>
                <p>{member.basis}</p>
                <p className="admin-topic-meta">{SCOPES[member.scope] ?? member.scope} · {member.decision_version === 'r2-member-manual-v1' ? '人工修正' : '已记录判断'} <Check check={member.check} /></p>
                <details className="admin-topic-evidence" open><summary>原文依据（{member.evidence.length} 处）</summary>{member.evidence.map((item, index) => <blockquote className="admin-evidence" key={index}><small>内容 #{item.article_id} · 材料 #{item.material_id} · 第 {item.paragraph + 1} 段 · {VOICES[item.voice]}</small><p>{item.quote}</p></blockquote>)}</details>
                <div className="admin-topic-inline">
                  {href && <a href={href} target="_blank" rel="noopener noreferrer">打开原文 ↗</a>}
                  <Button size="small" disabled={query.isFetching || query.isError} onClick={() => setEditor({ mode: 'member', topic: data.topic, member })}>{member.active ? '修正成员' : '重新加入成员'}</Button>
                  {member.active && <Button size="small" danger disabled={query.isFetching || query.isError} onClick={() => setEditor({ mode: 'remove', topic: data.topic, member })}>移除成员</Button>}
                  <Button type="link" size="small" onClick={() => { setTaskArticleId(member.article_id); setTab('tasks') }}>查看判断与任务</Button>
                </div>
                <details className="admin-topic-receipt"><summary>判断版本</summary><p>{member.decision_version}</p></details>
              </article>
            }) : <Empty description="尚无成员，可从当前合格材料人工补充" />}
            <Pagination current={memberPage} pageSize={data.page_size} total={data.members_total} showSizeChanger={false} onChange={setMemberPage} />
          </section> },
          { key: 'history', label: `修订历史（${data.changes_total}）`, children: <section className="admin-topic-stack" aria-label="话题修订历史">
            <p className="admin-note">保留每次操作的前后内容、认证操作者和人工原因。</p>
            {data.changes.length ? data.changes.map(change => <details className="admin-topic-record" key={change.revision}>
              <summary>r{change.revision} · {change.reason}</summary><p>{change.actor} · {displayTime(change.recorded_at)}</p><p className="admin-topic-id">操作编号：{change.mutation_id}</p>
              <div className="admin-topic-comparison"><section><h4>修改前</h4><JsonRecord value={change.before} /></section><section><h4>修改后</h4><JsonRecord value={change.after} /></section></div>
              <details><summary>原始操作</summary><JsonRecord value={change.command} /></details>
            </details>) : <Empty description="暂无修订记录" />}
            <Pagination current={historyPage} pageSize={data.page_size} total={data.changes_total} showSizeChanger={false} onChange={setHistoryPage} />
          </section> },
          { key: 'versions', label: '更新与派生版本', children: <RetainedVersions data={data} /> },
          { key: 'tasks', label: '判断与任务', children: <MemberTasks key={taskArticleId ?? 'all'} topicId={id} articleId={taskArticleId} onTask={onTask} /> },
        ]} />
      </div>}
    </Drawer>
    {editor && <TopicEditor {...editor} onClose={() => setEditor(null)} onRefresh={refresh} onSaved={receipt => { setEditor(null); onSaved(receipt); void query.refetch() }} />}
  </>
}
