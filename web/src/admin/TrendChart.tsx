import { Empty } from 'antd'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { money } from './costsApi'

interface Series { key: string; label: string; color: string }
interface TrendRow { day: string; [key: string]: string | number }

export default function TrendChart({ title, total, data, series, format = 'count', onSelectDay, note, variant = 'bar' }: {
  title: string
  total: string
  data: TrendRow[]
  series: Series[]
  format?: 'count' | 'money'
  onSelectDay?: (day: string) => void
  variant?: 'bar' | 'area'
  note?: string
}) {
  const formatValue = (value: string | number) => format === 'money' ? money(value) : String(value)
  const Chart = variant === 'area' ? AreaChart : BarChart
  return <section className="admin-panel admin-trend" aria-label={title}>
    <div className="admin-trend-heading"><h2>{title}</h2><strong>{total}</strong></div>
    {note && <p className="admin-note">{note}</p>}
    {data.length && series.length ? <>
      <div className="admin-chart" role="img" aria-label={`${title}图，详细数值见下表`}>
        <ResponsiveContainer width="100%" height="100%"><Chart data={data} onClick={state => { if (variant === 'area' && state.activeLabel !== undefined) onSelectDay?.(String(state.activeLabel)) }} accessibilityLayer margin={{ top: 8, right: 8, bottom: 8, left: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--line)" strokeDasharray="3 4" /><XAxis dataKey="day" tickFormatter={day => String(day).length > 10 ? String(day).slice(11, 16) : String(day).slice(5)} tickLine={false} axisLine={false} minTickGap={20} /><YAxis tickLine={false} axisLine={false} tick={{ fontSize: 11, fill: 'var(--ink-3)' }} domain={[0, 'auto']} allowDecimals={format === 'money'} width={format === 'count' ? 42 : 74} tickFormatter={value => formatValue(value)} /><Tooltip formatter={value => `${formatValue(String(value))}${format === 'money' ? ' USD' : ''}`} />
          {series.map(item => variant === 'area' ? <Area key={item.key} type="monotone" dataKey={item.key} name={item.label} stroke={item.color} strokeWidth={2.5} fill={item.color} fillOpacity={0.08} activeDot={{ r: 5 }} /> : <Bar key={item.key} dataKey={item.key} name={item.label} fill={item.color} maxBarSize={32} radius={[3, 3, 0, 0]} cursor={onSelectDay ? 'pointer' : undefined} stackId={series.length > 1 ? 'trend' : undefined} onClick={(_, index) => { const point = data[index]; if (point) onSelectDay?.(point.day) }} />)}
        </Chart></ResponsiveContainer>
      </div>
      <div className="admin-chart-legend">{series.map(item => <span key={item.key}><i style={{ background: item.color }} />{item.label}</span>)}</div>
      <details className="admin-chart-data"><summary>查看数据{onSelectDay && '与明细'}</summary><table className="admin-chart-table"><caption>{title}数据</caption><thead><tr><th scope="col">北京时间</th>{series.map(item => <th key={item.key} scope="col">{item.label}</th>)}{onSelectDay && <th scope="col">操作</th>}</tr></thead><tbody>{data.map(item => <tr key={item.day}><th scope="row">{item.day}</th>{series.map(seriesItem => <td key={seriesItem.key}>{formatValue(item[seriesItem.key] ?? 0)}{format === 'money' ? ' USD' : ''}</td>)}{onSelectDay && <td><button type="button" onClick={() => onSelectDay(item.day)} aria-label={`查看 ${item.day} ${series[0]?.label}明细`}>查看</button></td>}</tr>)}</tbody></table></details>
    </> : <Empty description="所选期间没有记录" />}
  </section>
}
