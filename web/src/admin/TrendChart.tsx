import { Empty } from 'antd'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { money } from './costsApi'

interface Series { key: string; label: string; color: string }
interface TrendRow { day: string; [key: string]: string | number }

export default function TrendChart({ title, total, data, series, format = 'count', onSelectDay, note }: {
  title: string
  total: string
  data: TrendRow[]
  series: Series[]
  format?: 'count' | 'money'
  onSelectDay?: (day: string) => void
  note?: string
}) {
  const formatValue = (value: string | number) => format === 'money' ? money(value) : String(value)
  return <section className="admin-panel admin-trend" aria-label={title}>
    <div className="admin-trend-heading"><h2>{title}</h2><strong>{total}</strong></div>
    {note && <p className="admin-note">{note}</p>}
    {data.length && series.length ? <>
      <div className="admin-chart" role="img" aria-label={`${title}图，详细数值见下表`}>
        <ResponsiveContainer width="100%" height="100%"><BarChart data={data} accessibilityLayer margin={{ top: 8, right: 8, bottom: 8, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="day" tickFormatter={day => String(day).slice(5)} minTickGap={20} /><YAxis domain={[0, 'auto']} allowDecimals={format === 'money'} width={format === 'count' ? 42 : 74} tickFormatter={value => formatValue(value)} /><Tooltip formatter={value => `${formatValue(String(value))}${format === 'money' ? ' USD' : ''}`} />
          {series.map(item => <Bar key={item.key} dataKey={item.key} name={item.label} fill={item.color} stackId={series.length > 1 ? 'trend' : undefined} onClick={(_, index) => { const point = data[index]; if (point) onSelectDay?.(point.day) }} />)}
        </BarChart></ResponsiveContainer>
      </div>
      <table className="admin-chart-table"><caption>{title}数据</caption><thead><tr><th scope="col">北京时间</th>{series.map(item => <th key={item.key} scope="col">{item.label}</th>)}{onSelectDay && <th scope="col">操作</th>}</tr></thead><tbody>{data.map(item => <tr key={item.day}><th scope="row">{item.day}</th>{series.map(seriesItem => <td key={seriesItem.key}>{formatValue(item[seriesItem.key] ?? 0)}{format === 'money' ? ' USD' : ''}</td>)}{onSelectDay && <td><button type="button" onClick={() => onSelectDay(item.day)} aria-label={`查看 ${item.day} ${series[0]?.label}明细`}>查看</button></td>}</tr>)}</tbody></table>
    </> : <Empty description="所选期间没有记录" />}
  </section>
}
