import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Empty, Progress, Segmented, Select, Table, Tabs, message } from 'antd'
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
    <div className="admin-panel admin-cost-summary">
      {summary.isPending && <p role="status">正在加载费用…</p>}
      {summary.isError && <Alert type="error" message="费用加载失败" action={<Button onClick={() => void summary.refetch()}>重试</Button>} />}
      {summary.data && <>
        <div className="admin-cost-summary-grid">
          <div className="admin-cost-hero">
            <Segmented aria-label="费用口径" value={mode} onChange={value => setMode(value as 'period' | 'spend')} options={[{ label: '使用成本', value: 'period' }, { label: '付款支出', value: 'spend' }]} />
            <div className="admin-cost-amount"><strong>{mode === 'spend' && summary.data.fixed.spend_precision === 'time_incomplete' ? '暂无法统计' : money(mode === 'period' ? summary.data.total_confirmed_usd : summary.data.fixed.spend_usd)}</strong>{!(mode === 'spend' && summary.data.fixed.spend_precision === 'time_incomplete') && <span>USD</span>}</div>
            <p className="admin-cost-explanation">{mode === 'period' ? '所选期间的模型调用费用，加上已付款固定费用的分摊金额。' : '所选期间已确认的付款金额，包含模型账户充值。'}</p>
            {mode === 'period' ? <>
              <div className="admin-cost-metrics"><div><small>模型调用</small><strong>{money(summary.data.calls.cost_usd)}</strong></div><div><small>固定费用分摊</small><strong>{money(summary.data.fixed.confirmed_usd)}</strong></div><div><small>待付款费用分摊</small><strong>{money(summary.data.fixed.expected_usd)}</strong></div></div>
              <p className="admin-cost-usage">日均成本 {money(summary.data.average_daily_usd)} USD · 模型调用 {summary.data.calls.count.toLocaleString()} 次</p>
              <p className="admin-footnote">待付款费用单列，未计入上方使用成本。</p>
            </> : <Button type="link" className="admin-payment-link" onClick={() => update({ tab: 'ledger', page: null })}>查看付款账目 →</Button>}
          </div>
          <div className="admin-budget"><div><strong>本月模型预算</strong><span>USD</span></div><div className="admin-budget-amount"><strong>{money(summary.data.budget.spent)}</strong><span>/ {money(summary.data.budget.limit)}</span></div><Progress percent={Number(summary.data.budget.limit) > 0 ? Math.min(100, Number(summary.data.budget.spent) / Number(summary.data.budget.limit) * 100) : 0} showInfo={false} strokeColor={Number(summary.data.budget.spent) >= Number(summary.data.budget.limit) ? 'var(--hot)' : 'var(--accent)'} /><small>已用 / 预算 · 始终显示本月，不随日期筛选变化</small>{Number(summary.data.budget.spent) >= Number(summary.data.budget.limit) && <p className="admin-budget-warning">已达到本月预算</p>}</div>
        </div>
        {summary.data.fixed.unconverted_currencies.length > 0 && <Alert type="warning" showIcon message={`部分费用尚未换算为 USD：${summary.data.fixed.unconverted_currencies.join('、')}`} description="请补充汇率后查看完整总额。" />}
        {mode === 'spend' && summary.data.fixed.spend_precision === 'time_incomplete' && <Alert type="info" showIcon message="付款日期无法匹配当前时段" description="部分账目只记录了付款日期。请选择完整日期范围查看付款支出。" />}
        <details className="admin-methodology"><summary>计算方式与用量详情</summary><div className="admin-cost-method-details">
          <p>使用成本：模型调用按发生时间统计；已付款固定费用按服务天数分摊到所选期间。待付款费用不计入已确认成本。</p>
          <p>付款支出：按确认付款日期统计。模型账户充值计入付款，不重复计入使用成本。</p>
          <p>日均成本：按所选期间涉及的 {summary.data.covered_days} 个自然日计算。</p>
          <p>模型用量：输入 {summary.data.calls.prompt_tokens.toLocaleString()} tokens · 输出 {summary.data.calls.completion_tokens.toLocaleString()} tokens</p>
          <p>已付款固定费用（原币）：{Object.entries(summary.data.fixed.confirmed_by_currency).map(([currency, value]) => `${money(value)} ${currency}`).join(' · ') || '无'}</p>
          <p>待付款固定费用（原币）：{Object.entries(summary.data.fixed.expected_by_currency).map(([currency, value]) => `${money(value)} ${currency}`).join(' · ') || '无'}</p>
          {summary.data.fixed.spend_precision === 'time_incomplete' && <p>已记录准确付款时刻：{Object.entries(summary.data.fixed.exact_spend_by_currency).map(([currency, value]) => `${money(value)} ${currency}`).join(' · ') || '无'}；仅记录付款日期：{Object.entries(summary.data.fixed.date_only_unplaced_by_currency).map(([currency, value]) => `${money(value)} ${currency}`).join(' · ') || '无'}</p>}
        </div></details>

      </>}
    </div>
    <Tabs activeKey={tab} onChange={value => update({ tab: value, page: null })} items={[{ key: 'summary', label: '构成与趋势' }, { key: 'calls', label: '调用明细' }, { key: 'ledger', label: '账目' }, { key: 'renewals', label: '续费提醒' }]} />
    {tab === 'summary' && summary.data && <CostBreakdown data={summary.data} range={range} />}
    {tab === 'calls' && <section className="admin-panel"><div className="admin-cost-actions admin-list-actions"><Button onClick={() => void downloadCalls(range, model, purpose).catch(error => message.error(error instanceof Error ? error.message : '导出失败'))}>导出 CSV</Button></div>
      <div className="admin-cost-filters"><Select allowClear placeholder="全部模型" value={model} style={{ minWidth: 150 }} options={summary.data?.models.map(item => ({ label: item.name, value: item.name }))} onChange={value => update({ model: value ?? null, page: null })} /><Select allowClear placeholder="全部用途" value={purpose} style={{ minWidth: 150 }} options={summary.data?.purposes.map(item => ({ label: item.name, value: item.name }))} onChange={value => update({ purpose: value ?? null, page: null })} /></div>
      {summary.data && <p>当前筛选：{summary.data.filtered_calls.count} 次调用，合计 {money(summary.data.filtered_calls.cost_usd)} USD。筛选仅影响明细，不改变上方总额。</p>}
      {calls.isError && <Alert type="error" message="调用明细加载失败" action={<Button onClick={() => void calls.refetch()}>重试</Button>} />}
      <Table rowKey="id" loading={calls.isPending} dataSource={calls.data?.items ?? []} scroll={{ x: 850 }} locale={{ emptyText: <Empty description="所选期间没有调用记录" /> }} pagination={{ current: page, pageSize: calls.data?.page_size ?? 25, total: calls.data?.total ?? 0, showSizeChanger: false, onChange: next => update({ page: String(next) }) }} columns={[{ title: '时间', dataIndex: 'created_at', render: (value: string) => new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) }, { title: '用途', dataIndex: 'purpose' }, { title: '模型', dataIndex: 'model' }, { title: '输入 / 输出', render: (_, row: CallRow) => `${row.prompt_tokens} / ${row.completion_tokens}` }, { title: 'USD', dataIndex: 'cost_usd', render: money }, { title: '关联对象', render: () => '未记录' }]} />
    </section>}
    {tab === 'ledger' && <ExpenseLedger />}
    {tab === 'renewals' && <Renewals />}
  </div>
}
