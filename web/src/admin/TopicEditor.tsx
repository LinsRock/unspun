import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Drawer, Input, Select, Tag } from 'antd'
import { useState } from 'react'

import { DOMAINS, SCOPES } from '../reader/presentation'
import { safeExternalUrl } from './adminHistoryApi'
import { getMemberContent, TopicApiError, writeTopic, type EvidenceVoice, type MemberRelation, type MutationReceipt, type TopicDetail, type TopicEvidence, type TopicMember, type TopicWrite } from './topicApi'
import { RELATIONS, VOICES } from './topicLabels'

interface Props {
  mode: 'create' | 'member' | 'remove'; topic?: TopicDetail['topic']; member?: TopicMember
  onClose: () => void; onSaved: (receipt: MutationReceipt) => void; onRefresh: () => void
}

function readPending(key: string, mode: Props['mode'], topicId?: string, articleId?: number): TopicWrite | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(key) ?? 'null') as TopicWrite | null
    if (!value || value.kind !== mode || typeof value.body?.mutation_id !== 'string') return null
    if (value.kind !== 'create' && value.topicId !== topicId) return null
    if (value.kind === 'remove' && value.articleId !== articleId) return null
    return value
  } catch { return null }
}

function remember(key: string, value: TopicWrite | null) {
  try {
    if (value) sessionStorage.setItem(key, JSON.stringify(value))
    else sessionStorage.removeItem(key)
  } catch { /* The mounted editor still retains its immutable retry payload. */ }
}

export default function TopicEditor({ mode, topic, member, onClose, onSaved, onRefresh }: Props) {
  const storageKey = `unspun:topic-edit:${mode}:${topic?.id ?? 'new'}:${member?.article_id ?? 'new'}`
  const [pending, setPending] = useState(() => readPending(storageKey, mode, topic?.id, member?.article_id))
  const savedMember = pending?.kind === 'member' ? pending.body : undefined
  const savedTopic = pending?.kind === 'create' ? pending.body : undefined
  const [title, setTitle] = useState(savedTopic?.title ?? '')
  const [kind, setKind] = useState<'event' | 'issue'>(savedTopic?.kind ?? 'event')
  const [domains, setDomains] = useState<string[]>(savedTopic?.domains ?? [])
  const [articleInput, setArticleInput] = useState(String(savedMember?.article_id ?? member?.article_id ?? ''))
  const [articleId, setArticleId] = useState<number | null>(savedMember?.article_id ?? member?.article_id ?? null)
  const [relation, setRelation] = useState<MemberRelation | undefined>(savedMember?.relation ?? member?.relation)
  const [basis, setBasis] = useState(savedMember?.basis ?? member?.basis ?? '')
  const [reason, setReason] = useState(pending?.body.reason ?? '')
  const [evidence, setEvidence] = useState<TopicEvidence[]>(savedMember?.evidence ?? member?.evidence ?? [])
  const [paragraphIndex, setParagraphIndex] = useState<number | null>(null)
  const [quote, setQuote] = useState('')
  const [selectedVoice, setSelectedVoice] = useState<EvidenceVoice>()
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [conflict, setConflict] = useState(false)
  const content = useQuery({
    queryKey: ['admin', 'member-content', articleId], enabled: mode === 'member' && articleId !== null,
    queryFn: ({ signal }) => getMemberContent(articleId!, signal), retry: false, refetchOnWindowFocus: false,
  })
  const paragraph = content.data?.paragraphs.find(value => value.index === paragraphIndex) ?? content.data?.paragraphs.find(value => [...value.text].length >= 8) ?? content.data?.paragraphs[0]
  const voice = paragraph?.voice ?? selectedVoice
  const locked = pending !== null || conflict || saving
  const heading = mode === 'create' ? '人工建立话题' : mode === 'remove' ? '移除成员' : member ? '修正成员' : '补充成员'
  const href = content.data && safeExternalUrl(content.data.url)

  function loadArticle() {
    const id = Number(articleInput)
    if (!Number.isSafeInteger(id) || id < 1) { setError('请输入有效的内容 ID。'); return }
    setError(null)
    setQuote('')
    setParagraphIndex(null)
    setSelectedVoice(undefined)
    if (id !== articleId) setEvidence([])
    setArticleId(id)
    if (id === articleId) void content.refetch()
  }

  function addEvidence() {
    const material = content.data
    const length = [...quote].length
    if (!material || !paragraph || length < 8 || length > 8000 || !paragraph.text.includes(quote)) {
      setError('请从当前段落选择连续的 8–8000 个原文字符。'); return
    }
    if (!voice || !paragraph.allowed_voices.includes(voice)) { setError('请按原文选择这处证据的视角。'); return }
    if (evidence.length >= 20) { setError('最多保留 20 处原文依据。'); return }
    if (evidence.some(item => item.material_id === material.material_id && item.paragraph === paragraph.index && item.quote === quote)) {
      setError('这处原文依据已经加入。'); return
    }
    setEvidence([...evidence, { article_id: material.article_id, material_id: material.material_id, paragraph: paragraph.index, quote, voice }])
    setQuote('')
    setError(null)
  }

  function prepare(): TopicWrite | null {
    if (!reason.trim()) { setError('请填写本次人工操作的原因。'); return null }
    const base = { mutation_id: crypto.randomUUID(), expected_revision: topic?.revision ?? 0, reason: reason.trim() }
    if (mode === 'create') {
      if (!title.trim() || !domains.length || domains.length > 3) { setError('请填写话题名称，并选择 1–3 个领域。'); return null }
      return { kind: 'create', body: { mutation_id: base.mutation_id, reason: base.reason, topic_id: crypto.randomUUID(), kind, title: title.trim(), domains } }
    }
    if (!topic) return null
    if (mode === 'remove' && member) return { kind: 'remove', topicId: topic.id, articleId: member.article_id, body: base }
    const material = content.data
    if (!material || content.isError || content.isFetching) { setError('请先载入当前合格材料。'); return null }
    if (!relation) { setError('请明确选择成员关系。'); return null }
    if (!basis.trim() || !evidence.length) { setError('请填写关联依据，并加入至少一处原文证据。'); return null }
    if (evidence.some(item => item.article_id !== material.article_id || item.material_id !== material.material_id || !material.paragraphs.some(p => p.index === item.paragraph && p.allowed_voices.includes(item.voice) && p.text.includes(item.quote)))) {
      setError('已有证据属于旧材料，请移除旧证据后从当前原文重新选择。'); return null
    }
    return { kind: 'member', topicId: topic.id, body: { ...base, article_id: material.article_id, material_id: material.material_id, relation, basis: basis.trim(), evidence } }
  }

  async function submit() {
    if (saving || conflict) return
    const write = pending ?? prepare()
    if (!write) return
    setPending(write)
    remember(storageKey, write)
    setSaving(true)
    setError(null)
    try {
      const receipt = await writeTopic(write)
      remember(storageKey, null)
      onSaved(receipt)
    } catch (failure) {
      if (failure instanceof TopicApiError && failure.status === 409) {
        setConflict(true)
        setError('话题修订或操作收据已变化。请刷新并重新审阅当前成员，再开始新的编辑。')
      } else if (failure instanceof TopicApiError && failure.status >= 400 && failure.status < 500) {
        remember(storageKey, null)
        setPending(null)
        setError(failure.message)
      } else {
        setError('尚未确认保存结果。已保留本次提交，请使用“重试同一提交”核实结果。')
      }
    } finally { setSaving(false) }
  }

  function refresh() {
    remember(storageKey, null)
    onRefresh()
  }

  return <Drawer title={heading} open onClose={saving ? undefined : onClose} closable={!saving} maskClosable={!saving} keyboard={!saving} size={Math.min(720, window.innerWidth)} className="admin-detail-drawer">
    <form className="admin-topic-form" onSubmit={event => { event.preventDefault(); void submit() }}>
      <p className="admin-note">{topic ? `正在审阅修订 r${pending && pending.kind !== 'create' ? pending.body.expected_revision : topic.revision}。` : ''}人工修改保留操作者与原因，并即时检查已有派生版本的有效性。</p>
      {pending && !conflict && <Alert type="info" showIcon title="本次提交已固定" description="网络重试会复用同一操作编号及原始内容。关闭后重新打开此编辑仍可核实提交。" />}
      {error && <Alert type="error" showIcon title={error} action={conflict ? <Button onClick={refresh}>刷新并重新审阅</Button> : undefined} />}
      {mode === 'create' && <>
        <div className="admin-topic-field"><label htmlFor="topic-title">话题名称</label><Input id="topic-title" value={title} maxLength={2000} disabled={locked} onChange={event => setTitle(event.target.value)} /></div>
        <div className="admin-topic-field"><label htmlFor="topic-kind">类型</label><Select id="topic-kind" value={kind} disabled={locked} onChange={setKind} options={[{ value: 'event', label: '事件' }, { value: 'issue', label: '议题' }]} /></div>
        <div className="admin-topic-field"><label htmlFor="topic-domains">领域（1–3 个）</label><Select id="topic-domains" mode="multiple" maxCount={3} value={domains} disabled={locked} onChange={setDomains} options={Object.entries(DOMAINS).map(([value, label]) => ({ value, label }))} /></div>
      </>}
      {mode === 'member' && <>
        <div className="admin-topic-field"><label htmlFor="member-article">内容 ID</label><div className="admin-topic-inline"><Input id="member-article" inputMode="numeric" value={articleInput} disabled={locked || Boolean(member)} onChange={event => setArticleInput(event.target.value)} /><Button disabled={locked} loading={content.isFetching} onClick={loadArticle}>载入材料</Button></div></div>
        {content.isPending && articleId !== null && <p role="status">正在核验当前材料…</p>}
        {content.isError && <Alert type="error" showIcon title="无法取得当前合格材料" description={content.error.message} />}
        {content.data && <section className="admin-topic-material" aria-label="当前原文材料">
          <strong>{content.data.title}</strong>
          <p>内容 #{content.data.article_id} · 材料 #{content.data.material_id} · {SCOPES[content.data.scope] ?? content.data.scope}</p>
          {content.data.requested_article_id !== content.data.article_id && <p>该内容已归并，保存时使用规范内容 #{content.data.article_id}。</p>}
          {href && <a href={href} target="_blank" rel="noopener noreferrer">打开原文 ↗</a>}
          <div className="admin-topic-field"><label htmlFor="member-paragraph">原文段落</label><Select id="member-paragraph" value={paragraph?.index} disabled={locked} options={content.data.paragraphs.map(p => ({ value: p.index, label: `第 ${p.index + 1} 段 · ${p.voice ? VOICES[p.voice] : '按原文选择视角'}` }))} onChange={value => { setParagraphIndex(value); setQuote(''); setSelectedVoice(undefined) }} /></div>
          {paragraph && <>
            <Input.TextArea aria-label="可选择的原文" className="admin-topic-source-text" value={paragraph.text} readOnly autoSize={{ minRows: 5, maxRows: 12 }} onSelect={event => {
              if (locked) return
              const field = event.currentTarget
              if (field.selectionEnd > field.selectionStart) setQuote(field.value.slice(field.selectionStart, field.selectionEnd))
            }} />
            <p className="admin-note">在原文中选中连续文字，或使用整段。引用须为 8–8000 字，保留原文措辞和材料视角。</p>
            <div className="admin-topic-inline"><Button disabled={locked || [...paragraph.text].length < 8 || [...paragraph.text].length > 8000} onClick={() => setQuote(paragraph.text)}>使用整段原文</Button>{paragraph.voice && <Tag>{VOICES[paragraph.voice]}</Tag>}</div>
            <div className="admin-topic-field"><label htmlFor="member-quote">已选原文</label><Input.TextArea id="member-quote" value={quote} readOnly autoSize={{ minRows: 2, maxRows: 6 }} placeholder="请在上方原文中选择" /></div>
            <div className="admin-topic-field"><label htmlFor="member-voice">原文视角</label><Select id="member-voice" value={voice} placeholder="按原文明确选择视角" disabled={locked || paragraph.voice !== null} onChange={setSelectedVoice} options={paragraph.allowed_voices.map(value => ({ value, label: VOICES[value] }))} /></div>
            <Button disabled={locked || !quote} onClick={addEvidence}>加入这处证据</Button>
          </>}
        </section>}
        <section aria-label="已选证据"><h3>原文依据（{evidence.length}/20）</h3>{evidence.length ? evidence.map((item, index) => <blockquote className="admin-evidence" key={`${index}-${item.material_id}-${item.paragraph}`}>
          <small>内容 #{item.article_id} · 材料 #{item.material_id} · 第 {item.paragraph + 1} 段 · {VOICES[item.voice]}</small><p>{item.quote}</p>
          <Button type="link" danger size="small" disabled={locked} onClick={() => setEvidence(evidence.filter((_, itemIndex) => itemIndex !== index))} aria-label={`移除证据 ${index + 1}`}>移除此处证据</Button>
        </blockquote>) : <p className="admin-note">尚未选择原文依据。</p>}</section>
        <div className="admin-topic-field"><label htmlFor="member-relation">成员关系</label><Select id="member-relation" disabled={locked} value={relation} placeholder="按原文明确选择关系" onChange={setRelation} options={Object.entries(RELATIONS).map(([value, label]) => ({ value, label }))} /></div>
        <div className="admin-topic-field"><label htmlFor="member-basis">关联依据</label><Input.TextArea id="member-basis" disabled={locked} value={basis} maxLength={2000} autoSize={{ minRows: 2, maxRows: 5 }} onChange={event => setBasis(event.target.value)} placeholder="解释原文为何支持这项成员关系" /></div>
      </>}
      {mode === 'remove' && member && <Alert type="warning" showIcon title={`将“${member.title}”从当前成员中移除`} description="原成员记录、原文证据与历史修订继续保留。依赖该成员的派生版本将重新检查有效性。" />}
      <div className="admin-topic-field"><label htmlFor="topic-reason">{mode === 'create' ? '建立原因' : '修改原因'}</label><Input.TextArea id="topic-reason" value={reason} maxLength={500} disabled={locked} autoSize={{ minRows: 2, maxRows: 5 }} onChange={event => setReason(event.target.value)} placeholder="说明这次人工操作的原因，供后续追溯" /></div>
      <div className="admin-topic-inline"><Button type="primary" htmlType="submit" danger={mode === 'remove'} disabled={conflict} loading={saving}>{pending ? '重试同一提交' : mode === 'create' ? '建立话题' : mode === 'remove' ? '确认移除成员' : '保存成员'}</Button><Button disabled={saving} onClick={onClose}>关闭</Button></div>
      {pending && <details className="admin-topic-receipt"><summary>本次操作收据</summary><p>操作编号：{pending.body.mutation_id}</p><p>基于修订 r{pending.kind === 'create' ? 0 : pending.body.expected_revision}</p></details>}
    </form>
  </Drawer>
}
