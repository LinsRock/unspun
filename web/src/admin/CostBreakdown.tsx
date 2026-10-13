import { useQuery } from '@tanstack/react-query'
import { Button, Empty, Table, message } from 'antd'
import { Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { AdminRange } from './adminFilters'
import { costParams, getCost, money, type CostSummary, type FixedCostRow, type Paged } from './costsApi'

export default function CostBreakdown({ data, range }: { data: CostSummary; range: AdminRange }) {
  const trend = data.trend.map(item => ({ ...item, cost_usd: Number(item.cost_usd) }))
  const purposes = data.purposes.map(item => ({ ...item, cost_usd: Number(item.cost_usd) }))
  const purposeTotal = purposes.reduce((sum, item) => sum + item.cost_usd, 0)
  const colors = ['#4c78a8', '#e69f00', '#009e73', '#cc79a7', '#56b4e9', '#d55e00']
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
    <h2>调用费用趋势</h2>
    {trend.length ? <div style={{ width: '100%', height: 240 }}><ResponsiveContainer><BarChart data={trend} accessibilityLayer><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="day" /><YAxis tickFormatter={value => money(value)} width={70} domain={[0, 'auto']} /><Tooltip formatter={value => `$${money(String(value))}`} /><Legend /><Bar dataKey="cost_usd" name="调用费用 USD" fill="var(--accent)" /></BarChart></ResponsiveContainer></div> : <Empty description="所选期间没有调用费用" />}
    {purposes.some(item => item.cost_usd > 0) && <><h2>调用用途占比</h2><div style={{ width: '100%', height: 240 }}><ResponsiveContainer><PieChart accessibilityLayer><Pie data={purposes.filter(item => item.cost_usd > 0)} dataKey="cost_usd" nameKey="name" innerRadius={55} outerRadius={85}>{purposes.filter(item => item.cost_usd > 0).map((item, index) => <Cell key={item.name} fill={colors[index % colors.length]} />)}</Pie><Tooltip formatter={value => `$${money(String(value))}`} /><Legend /></PieChart></ResponsiveContainer></div></>}
    <div className="admin-cost-tables">
      <Table size="small" rowKey="name" dataSource={data.purposes} pagination={false} locale={{ emptyText: '暂无用途费用' }} columns={[{ title: '用途', dataIndex: 'name' }, { title: '调用费用 USD', dataIndex: 'cost_usd', render: money }, { title: '占比', dataIndex: 'cost_usd', render: (value: string) => purposeTotal > 0 ? `${(Number(value) / purposeTotal * 100).toFixed(1)}%` : '—' }]} />
      <Table size="small" rowKey="name" dataSource={data.models} pagination={false} locale={{ emptyText: '暂无模型费用' }} columns={[{ title: '模型', dataIndex: 'name' }, { title: '调用费用 USD', dataIndex: 'cost_usd', render: money }]} />
    </div>
    <div className="admin-cost-actions"><h2>期间固定费用明细</h2><Button onClick={() => void exportFixed()}>导出 CSV</Button></div>
    <p className="admin-note">分摊额按与所选范围重叠的北京时间自然日计算，包含待付款预计费用。</p>
    {fixed.isError && <p role="alert">固定费用明细加载失败。<Button onClick={() => void fixed.refetch()}>重试</Button></p>}
    <Table rowKey="id" loading={fixed.isPending} dataSource={fixed.data?.items ?? []} pagination={false} scroll={{ x: 700 }} locale={{ emptyText: <Empty description="所选期间没有固定费用" /> }} columns={[{ title: '名称', dataIndex: 'name' }, { title: '类别', dataIndex: 'category' }, { title: '覆盖', render: (_, row: FixedCostRow) => `${row.period_start} 至 ${row.period_end}` }, { title: '状态', dataIndex: 'status', render: (value: string) => value === 'paid' ? '已付' : '预计' }, { title: '期间分摊', render: (_, row: FixedCostRow) => `${money(row.allocated)} ${row.currency}` }]} />
    {(fixed.data?.total ?? 0) > (fixed.data?.items.length ?? 0) && <p className="admin-note">仅显示前 {fixed.data?.items.length} 条；导出 CSV 查看全部匹配记录。</p>}
    <p className="admin-note">固定费用按覆盖的北京时间自然日分摊，与调用用途统计分开。历史调用的文章、事件和运行关联未记录。</p>
  </section>
}
