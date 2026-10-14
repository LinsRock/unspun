import { useQuery } from '@tanstack/react-query'
import { Button, Empty, Table, message } from 'antd'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { AdminRange } from './adminFilters'
import { costParams, getCost, money, type CostSummary, type FixedCostRow, type Paged } from './costsApi'

export default function CostBreakdown({ data, range }: { data: CostSummary; range: AdminRange }) {
  const trend = data.trend.map(item => ({ ...item, cost_usd: Number(item.cost_usd) }))
  const purposes = data.purposes.map(item => ({ ...item, cost_usd: Number(item.cost_usd) }))
  const purposeTotal = purposes.reduce((sum, item) => sum + item.cost_usd, 0)
  const colors = ['var(--chart-primary)', 'var(--chart-secondary)', '#b69b6f', 'var(--chart-muted)', '#a48bb6', '#bd817b']
  const fixed = useQuery({ queryKey: ['admin', 'fixed-costs', range.start, range.end], queryFn: ({ signal }) => getCost<Paged<FixedCostRow>>('costs/entries', costParams(range), signal), retry: false })
  async function exportFixed() {
    try {
      const response = await fetch(`/api/admin/costs/entries/export.csv?${costParams(range)}`, { credentials: 'same-origin', cache: 'no-store' })
      if (response.status === 422) throw new Error('匹配记录超过 5000 条，请缩小范围。')
      if (!response.ok) throw new Error('导出失败。')
      const url = URL.createObjectURL(await response.blob())
      const link = document.createElement('a')
      link.href = url
      link.download = 'fixed-costs.csv'
      link.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 0)
    } catch (error) { message.error(error instanceof Error ? error.message : '导出失败') }
  }
  return <section className="admin-panel" aria-label="费用构成">
    <div className="admin-section-heading"><h2>调用费用趋势</h2><span className="admin-scope">所选期间 · USD</span></div>
    {trend.length ? <div style={{ width: '100%', height: 240 }}><ResponsiveContainer><BarChart data={trend} accessibilityLayer><CartesianGrid vertical={false} stroke="var(--line)" strokeDasharray="3 4" /><XAxis dataKey="day" tickLine={false} axisLine={false} tickFormatter={value => String(value).slice(5)} /><YAxis tickLine={false} axisLine={false} tickFormatter={value => money(value)} width={70} domain={[0, 'auto']} /><Tooltip formatter={value => `$${money(String(value))}`} /><Bar radius={[3, 3, 0, 0]} maxBarSize={32} dataKey="cost_usd" name="调用费用 USD" fill="var(--accent)" /></BarChart></ResponsiveContainer></div> : <Empty description="所选期间没有调用费用" />}
    <div className="admin-cost-tables"><section><div className="admin-section-heading"><h2>调用用途分布</h2><small>不含固定费用</small></div><div className="admin-horizontal-bars">{purposes.filter(item => item.cost_usd > 0).sort((a, b) => b.cost_usd - a.cost_usd).map((item, index) => <div key={item.name}><span>{item.name}<b>${money(item.cost_usd)}<small>{(item.cost_usd / purposeTotal * 100).toFixed(1)}%</small></b></span><div><i style={{ width: `${item.cost_usd / purposeTotal * 100}%`, background: colors[index % colors.length] }} /></div></div>)}</div>{purposeTotal === 0 && <Empty description="所选期间没有调用费用" />}</section><section><h2>模型成本</h2><Table size="small" rowKey="name" dataSource={data.models} pagination={false} locale={{ emptyText: '暂无模型费用' }} columns={[{ title: '模型', dataIndex: 'name' }, { title: 'USD', dataIndex: 'cost_usd', render: money }]} /></section></div>
    <div className="admin-cost-actions"><h2>固定费用分摊</h2><Button onClick={() => void exportFixed()}>导出 CSV</Button></div>
    <p className="admin-note">按服务天数计算本期费用；已付款与待付款分别标明。</p>
    {fixed.isError && <p role="alert">固定费用明细加载失败。<Button onClick={() => void fixed.refetch()}>重试</Button></p>}
    <Table rowKey="id" loading={fixed.isPending} dataSource={fixed.data?.items ?? []} pagination={false} scroll={{ x: 700 }} locale={{ emptyText: <Empty description="所选期间没有固定费用" /> }} columns={[{ title: '名称', dataIndex: 'name' }, { title: '类别', dataIndex: 'category' }, { title: '服务期间', render: (_, row: FixedCostRow) => `${row.period_start} 至 ${row.period_end}` }, { title: '状态', dataIndex: 'status', render: (value: string) => value === 'paid' ? '已付款' : '待付款' }, { title: '本期分摊', render: (_, row: FixedCostRow) => `${money(row.allocated)} ${row.currency}` }]} />
    {(fixed.data?.total ?? 0) > (fixed.data?.items.length ?? 0) && <p className="admin-note">仅显示前 {fixed.data?.items.length} 条；导出 CSV 查看全部匹配记录。</p>}
    <p className="admin-footnote">历史模型调用尚无关联文章、事件或运行记录。</p>
  </section>
}
