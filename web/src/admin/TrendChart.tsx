import { Empty } from 'antd'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { money } from './costsApi'

export default function TrendChart({ title, total, data, keyName, unit, onSelectDay }: { title: string; total: string; data: { day: string; value: number }[]; keyName: string; unit: string; onSelectDay?: (day: string) => void }) {
  return <section className="admin-panel admin-trend" aria-label={title}>
    <div className="admin-trend-heading"><h2>{title}</h2><strong>{total}</strong></div>
    {data.length ? <>
      <div className="admin-chart" role="img" aria-label={`${title}图，详细数值见下表`}>
        <ResponsiveContainer width="100%" height="100%"><BarChart data={data} accessibilityLayer margin={{ top: 8, right: 8, bottom: 8, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="day" tickFormatter={day => day.slice(5)} minTickGap={20} /><YAxis domain={[0, 'auto']} allowDecimals={unit !== '篇'} width={unit === '篇' ? 42 : 74} tickFormatter={value => unit === '篇' ? String(value) : money(value)} /><Tooltip formatter={value => `${money(String(value))} ${unit}`} /><Bar dataKey="value" name={keyName} fill="var(--accent)" onClick={(_, index) => { const point = data[index]; if (point) onSelectDay?.(point.day) }} />
        </BarChart></ResponsiveContainer>
      </div>
      <table className="admin-chart-table"><caption>{title}数据</caption><thead><tr><th scope="col">北京时间日期</th><th scope="col">{keyName}</th><th scope="col">操作</th></tr></thead><tbody>{data.map(item => <tr key={item.day}><th scope="row">{item.day}</th><td>{money(item.value)} {unit}</td><td><button type="button" onClick={() => onSelectDay?.(item.day)} aria-label={`查看 ${item.day} ${keyName}明细`}>查看</button></td></tr>)}</tbody></table>
    </> : <Empty description="所选期间没有记录" />}
  </section>
}
