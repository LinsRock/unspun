import { useRef, type ReactNode } from 'react'
import { Card, Collapse, DatePicker, Empty, Tag, Typography } from 'antd'
import { Bar, BarChart, CartesianGrid, Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import dayjs from 'dayjs'
import { asOf, buckets, dateISO, dayMs, midnight, money, presets, zone, type Bucket, type Range } from './data'

export function Panel({title,extra,children}:{title:string;extra?:ReactNode;children:ReactNode}){
  return <Card className="panel" title={title} extra={extra}>{children}</Card>
}
export function Status({value}:{value:string}){
  const color=['失败','最近超时','异常'].includes(value)?'error':['待摘要','待付款','信息有限'].includes(value)?'warning':['正常','完成','成功','已确认'].includes(value)?'success':undefined
  return <Tag color={color}>{value}</Tag>
}
export function DateRange({range,onChange}:{range:Range;onChange:(range:Range)=>void}){
  const pendingPreset=useRef<Range|null>(null)
  return <div className="querybar"><div className="date-control"><Tag>{range.label}</Tag><DatePicker.RangePicker
    value={[dayjs(dateISO(range.start)),dayjs(dateISO(range.end-1))]}
    presets={presets.map(p=>({label:p.label,value:()=>{pendingPreset.current=p;return [dayjs(p.start).tz(zone),dayjs(p.end-1).tz(zone)]}}))}
    allowClear={false} needConfirm format="YYYY-MM-DD" maxDate={dayjs('2026-10-12')}
    onChange={dates=>{
      if(!dates?.[0]||!dates[1])return
      const preset=pendingPreset.current
      if(preset&&dates[0].valueOf()===preset.start&&dates[1].valueOf()===preset.end-1){onChange(preset);pendingPreset.current=null;return}
      const start=midnight(dates[0].format('YYYY-MM-DD')),end=Math.min(asOf,midnight(dates[1].format('YYYY-MM-DD'))+dayMs)
      if(start<end)onChange({start,end,label:'自定义'})
    }}
    onOpenChange={open=>{
      if(open){
        pendingPreset.current=null
        if(window.innerWidth<=680)requestAnimationFrame(()=>{
          const panels=document.querySelector<HTMLElement>('.ant-picker-dropdown-range .ant-picker-panels')
          const selected=panels?.querySelector<HTMLElement>('.ant-picker-cell-range-start, .ant-picker-cell-selected')
          const panel=selected?.closest<HTMLElement>('.ant-picker-panel')
          if(panels&&panel)panels.scrollLeft=panel.offsetLeft-panels.offsetLeft
        })
      }
    }}
    renderExtraFooter={()=> <Typography.Text type="secondary">北京时间 · 查询截至演示时点 10 月 12 日 14:00</Typography.Text>}
    styles={{popup:{root:{maxWidth:'calc(100vw - 24px)',overflowX:'auto'}}}}
  /></div><Typography.Text type="secondary" className="timezone">北京时间</Typography.Text></div>
}
export function Trend({range,type,onBucket}:{range:Range;type:'articles'|'cost';onBucket:(bucket:Bucket)=>void}){
  const data=buckets(range,type)
  const costPrecision=Math.max(2,-Math.floor(Math.log10(Math.max(...data.map(d=>d.value),1e-8)/4)))
  const tick=(n:number)=>type==='cost'?`$${n.toFixed(costPrecision)}`:String(n)
  if(!data.some(item=>item.value>0))return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="此期间暂无记录"/>
  return <><Typography.Text type="secondary" className="chart-unit">{type==='cost'?'调用费用 · USD':'入库文章 · 篇'}</Typography.Text><div className="chart-container"><ResponsiveContainer width="100%" height="100%"><BarChart data={data} margin={{top:18,right:12,bottom:6,left:2}} accessibilityLayer>
    <CartesianGrid vertical={false} stroke="var(--line)"/>
    <XAxis dataKey="label" tick={{fill:'var(--ink-3)',fontSize:11}} axisLine={false} tickLine={false} minTickGap={28}/>
    <YAxis domain={[0,'auto']} tickFormatter={tick} allowDecimals={type==='cost'} width={52} tick={{fill:'var(--ink-3)',fontSize:11}} axisLine={false} tickLine={false}/>
    <Tooltip cursor={{fill:'var(--accent-soft)'}} contentStyle={{background:'var(--surface)',border:'1px solid var(--line)',borderRadius:8,color:'var(--ink)'}} labelFormatter={(label)=>`${label} · 北京时间`} formatter={(value)=>[type==='cost'?money(Number(value)):`${value} 篇`,type==='cost'?'调用费用':'入库文章']}/>
    <Bar dataKey="value" fill="var(--accent)" radius={[4,4,0,0]} maxBarSize={56} isAnimationActive={false} onClick={data=>onBucket((data as unknown as {payload:Bucket}).payload)}/>
  </BarChart></ResponsiveContainer></div></>
}
export function OverviewTrend(props:{range:Range;onBucket:(bucket:Bucket,type:'articles'|'cost')=>void}){
  return <div className="overview-trends">{(['articles','cost'] as const).map(type=>{
    const total=buckets(props.range,type).reduce((sum,b)=>sum+b.value,0)
    return <Panel key={type} title={type==='articles'?'文章入库趋势':'调用费用趋势'}><div className="trend-total"><span>所选期间合计</span><strong data-trend-total={type}>{type==='articles'?`${total} 篇`:money(total)}</strong></div><Trend range={props.range} type={type} onBucket={b=>props.onBucket(b,type)}/></Panel>
  })}</div>
}
export interface CostSlice {purpose:string;count:number;cost:number}
export function CostComposition({data,onPurpose}:{data:CostSlice[];onPurpose:(purpose:string)=>void}){
  const slices=data.filter(d=>d.cost>0),total=data.reduce((sum,d)=>sum+d.cost,0)
  const colors=['var(--accent)','#4e7fa7','#789ec0','#a3bad4','#6b7e98','#bec5ce']
  if(!total)return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="此期间没有调用费用"/>
  return <section className="cost-composition" aria-label="模型调用费用构成"><div className="composition-heading"><Typography.Text type="secondary">模型调用费用构成 · 不含固定费用</Typography.Text><span className="num" data-composition-total>{money(total)}</span></div><div className="pie-container"><ResponsiveContainer width="100%" height="100%"><PieChart accessibilityLayer><Pie data={slices} dataKey="cost" nameKey="purpose" innerRadius={62} outerRadius={96} paddingAngle={2} stroke="var(--surface)" isAnimationActive={false} onClick={slice=>onPurpose((slice as unknown as {payload:CostSlice}).payload.purpose)}>{slices.map((slice,i)=><Cell key={slice.purpose} fill={colors[i%colors.length]}/>)}</Pie><Tooltip contentStyle={{background:'var(--surface)',border:'1px solid var(--line)',borderRadius:8,color:'var(--ink)'}} formatter={(value)=>`${money(Number(value))} · ${(Number(value)/total*100).toFixed(1)}%`}/><Legend verticalAlign="bottom" iconType="circle" iconSize={8} formatter={purpose=>{const slice=slices.find(s=>s.purpose===purpose);return <span className="pie-legend-label">{purpose} {slice?(slice.cost/total*100).toFixed(1)+'%':''}</span>}}/></PieChart></ResponsiveContainer></div></section>
}
export function Explanation({children}:{children:ReactNode}){return <Collapse ghost size="small" className="explanation" items={[{key:'explanation',label:'口径与数据说明',children}]}/>}
