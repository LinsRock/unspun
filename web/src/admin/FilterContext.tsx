import { Button, Tag } from 'antd'
import { useSearchParams } from 'react-router-dom'

export default function FilterContext({ keys, labels = {} }: { keys: string[]; labels?: Record<string, string> }) {
  const [search, setSearch] = useSearchParams()
  const active = keys.filter(key => search.get(key))
  if (!active.length) return null
  function remove(keysToRemove: string[]) {
    const next = new URLSearchParams(search)
    keysToRemove.forEach(key => next.delete(key))
    next.delete('page')
    setSearch(next)
  }
  const values: Record<string, string> = { error: '最近失败', ok: '最近成功', no_runs: '从未抓取', pending: '待处理', failed: '处理失败', summarized: '已摘要', embedded: '已嵌入', clustered: '已归入事件', scored: '已评分', zh: '中文', en: '英文', grounded: '证据充分', limited: '证据有限', review_limited: '审核受限', unrecorded: '未记录', true: '是', false: '否', fetched_at: '入库时间', published_at: '报道时间', reported: '有效报道时间', missing: '缺失报道时间', discovered: '系统新建时间' }
  return <div className="admin-filter-context"><span>已筛选</span>{active.map(key => <Tag closable key={key} onClose={event => { event.preventDefault(); remove([key]) }}>{labels[key] ?? key}：{values[search.get(key)!] ?? search.get(key)}</Tag>)}<Button type="text" size="small" onClick={() => remove(active)}>重置筛选</Button></div>
}
