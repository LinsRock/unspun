import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Empty, Input, message, Modal, Table, Tabs } from 'antd'
import { useState } from 'react'
import dayjs from 'dayjs'

import ExpenseForm, { RateForm, RuleForm } from './ExpenseForm'
import { EditEntry, EditRate, EditRule } from './ExpenseEditors'
import { getCost, money, writeExpense, type ExpenseEntry, type ExpenseRule, type FxRate } from './costsApi'

export default function ExpenseLedger() {
  const client = useQueryClient()
  const [page, setPage] = useState(1)
  const [reason, setReason] = useState('')
  const [paying, setPaying] = useState<ExpenseEntry | null>(null)
  const [canceling, setCanceling] = useState<ExpenseEntry | null>(null)
  const [editingEntry, setEditingEntry] = useState<ExpenseEntry | null>(null)
  const [editingRule, setEditingRule] = useState<ExpenseRule | null>(null)
  const [editingRate, setEditingRate] = useState<FxRate | null>(null)
  const [saving, setSaving] = useState(false)
  const entries = useQuery({ queryKey: ['admin', 'expenses', page], queryFn: ({ signal }) => getCost<ExpenseEntry[]>('expenses', new URLSearchParams({ page: String(page), page_size: '20' }), signal), retry: false })
  const rules = useQuery({ queryKey: ['admin', 'expense-rules'], queryFn: ({ signal }) => getCost<ExpenseRule[]>('expense-rules', undefined, signal), retry: false })
  const rates = useQuery({ queryKey: ['admin', 'expense-rates'], queryFn: ({ signal }) => getCost<FxRate[]>('expense-rates', undefined, signal), retry: false })
  const refresh = () => void client.invalidateQueries({ queryKey: ['admin'] })

  async function confirmPayment() {
    if (!paying || !reason.trim()) return
    setSaving(true)
    try {
      const todayBeijing = new Date(Date.now() + 8 * 60 * 60 * 1000).toISOString().slice(0, 10)
      await writeExpense(`expenses/${paying.id}`, 'PATCH', { version: paying.version, status: 'paid', paid_on: todayBeijing, reason: reason.trim() })
      message.success('付款已确认')
      setPaying(null)
      setReason('')
      refresh()
    } catch (error) { message.error(error instanceof Error ? error.message : '提交失败') }
    finally { setSaving(false) }
  }

  async function cancelEntry() {
    if (!canceling || !reason.trim()) return
    setSaving(true)
    try {
      await writeExpense(`expenses/${canceling.id}`, 'PATCH', { version: canceling.version, status: 'canceled', reason: reason.trim() })
      message.success('待付账目已取消')
      setCanceling(null)
      setReason('')
      refresh()
    } catch (error) { message.error(error instanceof Error ? error.message : '提交失败') }
    finally { setSaving(false) }
  }

  async function generate(rule: ExpenseRule) {
    setSaving(true)
    try {
      const result = await writeExpense<{ items: ExpenseEntry[] }>(`expense-rules/${rule.id}/generate`, 'POST', { through: dayjs().add(1, 'year').format('YYYY-MM-DD') })
      message.success(`生成 ${result.items.length} 条账目；重复期间不会再次生成`)
      refresh()
    } catch (error) { message.error(error instanceof Error ? error.message : '生成失败') }
    finally { setSaving(false) }
  }

  return <section className="admin-panel">
    <div className="admin-cost-actions admin-list-actions"><ExpenseForm onSaved={refresh} /><RuleForm onSaved={refresh} /><RateForm onSaved={refresh} /></div>
    <Tabs items={[
      { key: 'entries', label: '账目', children: <>{entries.isError && <p role="alert">账目加载失败。<Button onClick={() => void entries.refetch()}>重试</Button></p>}<Table rowKey="id" loading={entries.isPending} dataSource={entries.data ?? []} scroll={{ x: 740 }} locale={{ emptyText: <Empty description="没有账目" /> }} pagination={{ current: page, pageSize: 20, total: (page - 1) * 20 + (entries.data?.length ?? 0) + ((entries.data?.length ?? 0) === 20 ? 1 : 0), showSizeChanger: false, onChange: setPage }} columns={[{ title: '名称', dataIndex: 'name' }, { title: '类别', dataIndex: 'category' }, { title: '金额', render: (_, row: ExpenseEntry) => `${money(row.amount)} ${row.currency}` }, { title: '服务期间', render: (_, row: ExpenseEntry) => row.period_start ? `${row.period_start} 至 ${row.period_end}` : '充值' }, { title: '状态', dataIndex: 'status', render: (value: string) => ({ pending: '待付', paid: '已付', canceled: '已取消' })[value] ?? value }, { title: '付款', dataIndex: 'paid_on', render: (value: string | null, row: ExpenseEntry) => value ?? row.paid_at ?? '未记录' }, { title: '操作', render: (_, row: ExpenseEntry) => <><Button onClick={() => setEditingEntry(row)}>修订</Button>{row.status === 'pending' && <><Button onClick={() => setPaying(row)}>确认付款</Button><Button danger onClick={() => setCanceling(row)}>取消账目</Button></>}</> }]} /></> },
      { key: 'rules', label: '周期规则', children: <>{rules.isError && <p role="alert">规则加载失败。</p>}<Table rowKey="id" loading={rules.isPending} dataSource={rules.data ?? []} pagination={false} scroll={{ x: 700 }} columns={[{ title: '名称', dataIndex: 'name' }, { title: '周期', dataIndex: 'cadence' }, { title: '金额', render: (_, row: ExpenseRule) => `${money(row.amount)} ${row.currency}` }, { title: '锚点', dataIndex: 'anchor_date' }, { title: '提前提醒', dataIndex: 'reminder_days', render: (value: number) => `${value} 天` }, { title: '操作', render: (_, row: ExpenseRule) => <><Button onClick={() => setEditingRule(row)}>修订</Button><Button disabled={saving} onClick={() => void generate(row)}>生成未来一年账目</Button></> }]} /></> },
      { key: 'rates', label: '汇率', children: <>{rates.isError && <p role="alert">汇率加载失败。</p>}<Table rowKey="id" loading={rates.isPending} dataSource={rates.data ?? []} pagination={false} columns={[{ title: '币种', dataIndex: 'currency' }, { title: '生效日', dataIndex: 'effective_on' }, { title: '兑 USD', dataIndex: 'rate_to_usd' }, { title: '来源', dataIndex: 'source' }, { title: '操作', render: (_, row: FxRate) => <Button onClick={() => setEditingRate(row)}>修订</Button> }]} /></> },
    ]} />
    <Modal title="确认付款" open={Boolean(paying)} onCancel={() => { setPaying(null); setReason('') }} onOk={() => void confirmPayment()} okButtonProps={{ disabled: !reason.trim() || saving, loading: saving }}><p>确认后按今天的北京时间自然日记录付款；历史付款请使用账目修正接口。</p><Input.TextArea aria-label="确认原因" value={reason} onChange={event => setReason(event.target.value)} placeholder="付款凭证或原因" /></Modal>
    <Modal title="取消待付账目" open={Boolean(canceling)} onCancel={() => { setCanceling(null); setReason('') }} onOk={() => void cancelEntry()} okButtonProps={{ disabled: !reason.trim() || saving, loading: saving, danger: true }}><p>取消后该笔预计费用不再计入期间成本。</p><Input.TextArea aria-label="取消原因" value={reason} onChange={event => setReason(event.target.value)} placeholder="取消原因" /></Modal>
    <EditEntry row={editingEntry} onClose={() => setEditingEntry(null)} onSaved={refresh} />
    <EditRule row={editingRule} onClose={() => setEditingRule(null)} onSaved={refresh} />
    <EditRate row={editingRate} onClose={() => setEditingRate(null)} onSaved={refresh} />
  </section>
}
