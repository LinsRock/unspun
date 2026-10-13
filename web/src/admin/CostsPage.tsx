import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Empty, Segmented, Select, Table, Tabs, message } from 'antd'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import type { AdminRange } from './adminFilters'
import CostBreakdown from './CostBreakdown'
import { costParams, downloadCalls, getCost, money, type CallRow, type CostSummary, type Paged } from './costsApi'
import ExpenseLedger from './ExpenseLedger'
import Renewals from './Renewals'

export default function CostsPage({ range }: { range: AdminRange }) {
  const [mode, setMode] = useState<'period' | 'spend'>('period')
  const [search, setSearch] = useSearchParams()
  const tab = ['summary', 'calls', 'ledger', 'renewals'].includes(search.get('tab') ?? '') ? search.get('tab')! : 'summary'
  const model = search.get('model') ?? undefined
  const purpose = search.get('purpose') ?? undefined
  const page = Math.max(1, Number(search.get('page')) || 1)
  const params = costParams(range, { model, purpose })
  const summary = useQuery({ queryKey: ['admin', 'costs', range.start, range.end, model, purpose], queryFn: ({ signal }) => getCost<CostSummary>('costs', params, signal), retry: false })
  const calls = useQuery({ queryKey: ['admin', 'cost-calls', range.start, range.end, model, purpose, page], queryFn: ({ signal }) => getCost<Paged<CallRow>>('costs/calls', costParams(range, { model, purpose, page }), signal), enabled: tab === 'calls', retry: false })

  function update(values: Record<string, string | null>) {
    const next = new URLSearchParams(search)
    for (const [key, value] of Object.entries(values)) {
      if (value === null) next.delete(key)
      else next.set(key, value)
    }
    setSearch(next)
  }

  return <div className="admin-costs">
    <div className="admin-panel"><p className="admin-note">期间成本 = 调用发生额 + 固定费用覆盖期间分摊。实际支出按确认付款日期；预计固定费用单列。范围终点不含。</p>
      {summary.isPending && <p role="status">正在加载费用…</p>}
      {summary.isError && <Alert type="error" message="费用加载失败" action={<Button onClick={() => void summary.refetch()}>重试</Button>} />}
      {summary.data && <>
        <Segmented aria-label="费用口径" value={mode} onChange={value => setMode(value as 'period' | 'spend')} options={[{ label: '期间成本', value: 'period' }, { label: '实际支出', value: 'spend' }]} />
        <p className="admin-cost-primary">{mode === 'period' ? '期间已确认成本' : '实际支出'}：<strong>{money(mode === 'period' ? summary.data.total_confirmed_usd : summary.data.fixed.spend_usd)} USD</strong></p>
        <div className="admin-cost-metrics"><div><small>期间已确认成本 USD</small><strong>{money(summary.data.total_confirmed_usd)}</strong></div><div><small>调用费用 USD</small><strong>{money(summary.data.calls.cost_usd)}</strong></div><div><small>预计固定费用 USD</small><strong>{money(summary.data.fixed.expected_usd)}</strong></div><div><small>实际支出 USD</small><strong>{money(summary.data.fixed.spend_usd)}</strong></div></div>
        <p>期间平均每日已确认成本：{money(summary.data.average_daily_usd)} USD（按 {summary.data.covered_days} 个覆盖自然日）</p>
        <p>调用 {summary.data.calls.count} 次 · 输入 {summary.data.calls.prompt_tokens} token · 输出 {summary.data.calls.completion_tokens} token</p>
        <p>本月模型调用预算（始终为当前月，与页面历史范围无关）：{money(summary.data.budget.spent)} / {money(summary.data.budget.limit)} USD</p>
        {summary.data.fixed.unconverted_currencies.length > 0 && <Alert type="warning" message={`缺少汇率：${summary.data.fixed.unconverted_currencies.join('、')}；USD 总额不完整。`} />}
        {summary.data.fixed.spend_precision === 'time_incomplete' && <Alert type="info" message="当前为滚动或小时范围：仅记录付款日期的账目无法放入准确时段，实际支出总额不显示。" description={`准确时刻付款：${Object.entries(summary.data.fixed.exact_spend_by_currency).map(([currency, value]) => `${money(value)} ${currency}`).join(' · ') || '无'}；仅有日期的付款：${Object.entries(summary.data.fixed.date_only_unplaced_by_currency).map(([currency, value]) => `${money(value)} ${currency}`).join(' · ') || '无'}`} />}
        <p className="admin-note">原币已确认：{Object.entries(summary.data.fixed.confirmed_by_currency).map(([currency, value]) => `${money(value)} ${currency}`).join(' · ') || '无'} · 原币预计：{Object.entries(summary.data.fixed.expected_by_currency).map(([currency, value]) => `${money(value)} ${currency}`).join(' · ') || '无'}</p>
      </>}
    </div>
    <Tabs activeKey={tab} onChange={value => update({ tab: value, page: null })} items={[{ key: 'summary', label: '构成与趋势' }, { key: 'calls', label: '调用明细' }, { key: 'ledger', label: '账目与规则' }, { key: 'renewals', label: '续费提醒' }]} />
    {tab === 'summary' && summary.data && <CostBreakdown data={summary.data} range={range} />}
    {tab === 'calls' && <section className="admin-panel"><div className="admin-cost-actions"><h2>调用明细</h2><Button onClick={() => void downloadCalls(range, model, purpose).catch(error => message.error(error instanceof Error ? error.message : '导出失败'))}>导出 CSV</Button></div>
      <div className="admin-cost-filters"><Select allowClear placeholder="全部模型" value={model} style={{ minWidth: 150 }} options={summary.data?.models.map(item => ({ label: item.name, value: item.name }))} onChange={value => update({ model: value ?? null, page: null })} /><Select allowClear placeholder="全部用途" value={purpose} style={{ minWidth: 150 }} options={summary.data?.purposes.map(item => ({ label: item.name, value: item.name }))} onChange={value => update({ purpose: value ?? null, page: null })} /></div>
      {summary.data && <p>筛选调用小计：{money(summary.data.filtered_calls.cost_usd)} USD / {summary.data.filtered_calls.count} 次。上方期间总成本始终包含全部调用和固定费用。</p>}
      {calls.isError && <Alert type="error" message="调用明细加载失败" action={<Button onClick={() => void calls.refetch()}>重试</Button>} />}
      <Table rowKey="id" loading={calls.isPending} dataSource={calls.data?.items ?? []} scroll={{ x: 850 }} locale={{ emptyText: <Empty description="所选期间没有调用记录" /> }} pagination={{ current: page, pageSize: calls.data?.page_size ?? 25, total: calls.data?.total ?? 0, showSizeChanger: false, onChange: next => update({ page: String(next) }) }} columns={[{ title: '时间', dataIndex: 'created_at', render: (value: string) => new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) }, { title: '用途', dataIndex: 'purpose' }, { title: '模型', dataIndex: 'model' }, { title: '输入 / 输出', render: (_, row: CallRow) => `${row.prompt_tokens} / ${row.completion_tokens}` }, { title: 'USD', dataIndex: 'cost_usd', render: money }, { title: '关联对象', render: () => '未记录' }]} />
    </section>}
    {tab === 'ledger' && <ExpenseLedger />}
    {tab === 'renewals' && <Renewals />}
  </div>
}
