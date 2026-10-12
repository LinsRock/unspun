import dayjs from 'dayjs'
import utc from 'dayjs/plugin/utc'
import timezone from 'dayjs/plugin/timezone'
import 'dayjs/locale/zh-cn'

dayjs.extend(utc)
dayjs.extend(timezone)
dayjs.locale('zh-cn')
export const zone = 'Asia/Shanghai'
export const asOf = dayjs.tz('2026-10-12 14:00', zone).valueOf()
export const dayMs = 86_400_000
export const midnight = (date: string) => dayjs.tz(date, zone).startOf('day').valueOf()
export const dateISO = (time: number) => dayjs(time).tz(zone).format('YYYY-MM-DD')
export const timeLabel = (time: number) => dayjs(time).tz(zone).format('MM-DD HH:mm')
export const money = (value: number) => `$${value.toFixed(value > 0 && value < .01 ? 5 : 4)}`
export type Page = 'overview' | 'costs' | 'sources' | 'content' | 'runs' | 'config'
export interface Range { start: number; end: number; label: string }
export interface View {
  page: Page; tab: string; query: string; sort: string; health: string; purpose: string;
  model: string; source?: string; basis: string; mode: string; pageNo: number; zoom?: Range
}
export const defaultView: View = { page: 'overview', tab: '', query: '', sort: '异常优先', health: '全部状态', purpose: '全部用途', model: '全部模型', basis: '入库时间', mode: '期间成本', pageNo: 1 }
export const presets: Range[] = [
  { label: '今天', start: midnight('2026-10-12'), end: asOf },
  { label: '昨天', start: midnight('2026-10-11'), end: midnight('2026-10-12') },
  { label: '本周', start: midnight('2026-10-12'), end: asOf },
  { label: '上周', start: midnight('2026-10-05'), end: midnight('2026-10-12') },
  { label: '本月', start: midnight('2026-10-01'), end: asOf },
  { label: '上月', start: midnight('2026-09-01'), end: midnight('2026-10-01') },
  { label: '今年', start: midnight('2026-01-01'), end: asOf },
  { label: '最近 24 小时', start: asOf - dayMs, end: asOf },
  { label: '最近 7 天', start: asOf - dayMs * 7, end: asOf },
]
export const within = (time: number, range: Range) => time >= range.start && time < range.end
export const scopedRange = (range: Range, view: View): Range => view.zoom ? { start: Math.max(range.start, view.zoom.start), end: Math.min(range.end, view.zoom.end), label: '图表时段' } : range
export interface Source { id: string; name: string; language: string; region: string; kind: string; bad: boolean }
export const sources: Source[] = [
  { id:'nhk',name:'NHK World',language:'英文',region:'东亚',kind:'公共媒体',bad:true },
  { id:'nasa',name:'NASA',language:'英文',region:'北美',kind:'官方',bad:false },
  { id:'bbc',name:'BBC World',language:'英文',region:'欧洲',kind:'公共媒体',bad:false },
  { id:'caixin',name:'财新',language:'中文',region:'东亚',kind:'新闻媒体',bad:false },
  { id:'quanta',name:'Quanta Magazine',language:'英文',region:'北美',kind:'科学媒体',bad:false },
  { id:'carbon',name:'Carbon Brief',language:'英文',region:'欧洲',kind:'专业媒体',bad:false },
  { id:'psyche',name:'Psyche',language:'英文',region:'欧洲',kind:'人文媒体',bad:false },
  { id:'hn',name:'Hacker News',language:'英文',region:'北美',kind:'社区',bad:false },
]
export const titles = ['新一轮月球观测数据公开','区域洪水救援进入恢复阶段','央行公布政策会议纪要','研究团队公布新材料实验结果','城市启动公共交通试点','一项心理学研究重新评估记忆机制']
export interface Article { id:number; source:string; event:number; time:number; published:number; title:string; status:string; quality:string }
export interface Call { id:number; time:number; purpose:string; model:string; cost:number; input:number; output:number; article:number }
export interface Fetch { id:number; source:string; time:number; status:string; error:string | null }
export interface Run { id:number; time:number; summarized:number; embedded:number; clustered:number; scored:number }
export const articles: Article[] = [], calls: Call[] = [], fetches: Fetch[] = [], runs: Run[] = []
for(let day=1;day<=12;day++) for(const hour of [2,6,10,13]) {
  const time = midnight(`2026-10-${String(day).padStart(2,'0')}`)+hour*3_600_000
  for(const source of sources){
    const failed=source.bad&&(day+hour)%3!==0
    fetches.push({id:fetches.length+1,source:source.id,time,status:failed?'失败':'成功',error:failed?'读取上游超时（示例）':null})
  }
  runs.push({id:runs.length+1,time,summarized:6+day%5,embedded:9,clustered:8,scored:4})
  for(let n=0;n<3+day%4;n++){
    const id=articles.length+1,source=sources[(day+hour+n)%sources.length],event=(day+n)%titles.length
    articles.push({id,source:source.id,event,time,published:time-n%3*dayMs,title:titles[event],status:id%17===0?'失败':id%13===0?'待摘要':'完成',quality:id%11===0?'信息有限':'有原文依据'})
    const purpose=['摘要','重要性评分','观点对比','内容审核','日报','embedding'][id%6]
    calls.push({id,time,purpose,model:purpose==='embedding'?'qwen3-embedding-8b':purpose==='摘要'||purpose==='日报'?'gemini-2.5-flash-lite':'gemini-2.5-flash',cost:purpose==='日报'?.00021:.0008+id%7*.002,input:900+id%500,output:100+id%300,article:id})
  }
}
export interface Expense { id:number; name:string; category:string; amount:number; currency:string; cycle:string; start:string; end:string; paid:string | null; due:string | null }
export const initialExpenses: Expense[] = [
  {id:1,name:'VPS 主机',category:'服务器',amount:6,currency:'USD',cycle:'月付',start:'2026-10-01',end:'2026-10-31',paid:'2026-10-01',due:'2026-11-01'},
  {id:2,name:'域名续费',category:'域名',amount:120,currency:'CNY',cycle:'年付',start:'2026-01-01',end:'2026-12-31',paid:'2026-01-01',due:'2027-01-01'},
  {id:3,name:'对象存储与备份',category:'存储',amount:1.5,currency:'USD',cycle:'月付',start:'2026-10-01',end:'2026-10-31',paid:null,due:'2026-10-18'},
  {id:4,name:'模型账户充值',category:'充值',amount:20,currency:'USD',cycle:'一次性',start:'2026-10-01',end:'2026-10-01',paid:'2026-10-01',due:null},
]
export const totalCalls = (xs: Call[]) => xs.reduce((sum,item)=>sum+item.cost,0)
export function totals(range: Range, expenses: Expense[]){
  const selected=calls.filter(c=>within(c.time,range));let fixed=0,estimated=0,cash=0
  for(const e of expenses){
    const amount=e.amount/(e.currency==='CNY'?7.1:1)
    if(e.paid&&within(midnight(e.paid)+12*3_600_000,range))cash+=amount
    if(e.category==='充值')continue
    const from=midnight(e.start),to=midnight(e.end)+dayMs
    const overlap=Math.max(0,Math.min(midnight(dateISO(range.end-1))+dayMs,to)-Math.max(midnight(dateISO(range.start)),from))
    if(e.paid)fixed+=amount*overlap/(to-from);else estimated+=amount*overlap/(to-from)
  }
  return {llm:totalCalls(selected),fixed,estimated,cash,count:selected.length}
}
export const sourceName = (id:string) => sources.find(s=>s.id===id)?.name??id
export function sourceStats(source:Source,range:Range){
  const logs=fetches.filter(f=>f.source===source.id&&within(f.time,range)),ok=logs.filter(f=>f.status==='成功').length
  const lastSuccess=fetches.filter(f=>f.source===source.id&&f.status==='成功').at(-1)?.time
  return {...source,ok,fail:logs.length-ok,rate:logs.length?ok/logs.length:null,articles:articles.filter(a=>a.source===source.id&&within(a.time,range)).length,lastSuccess}
}
export interface Bucket { start:number; end:number; label:string; value:number }
export function buckets(range:Range,type:'articles'|'cost'):Bucket[]{
  const hourly=range.end-range.start<=dayMs,step=hourly?7_200_000:Math.max(dayMs,Math.ceil((range.end-range.start)/dayMs/14)*dayMs),result:Bucket[]=[]
  for(let t=range.start;t<range.end;t+=step){
    const end=Math.min(t+step,range.end),filter={start:t,end,label:''}
    const value=type==='cost'?totalCalls(calls.filter(c=>within(c.time,filter))):articles.filter(a=>within(a.time,filter)).length
    result.push({start:t,end,label:dayjs(t).tz(zone).format(hourly?'HH:mm':'MM-DD'),value})
  }
  return result
}
export function downloadCSV(filename:string,rows:(string|number)[][]){
  const cell=(value:string|number)=>`"${String(value).replace(/^[=+@-]/,"'$&").replaceAll('"','""')}"`
  const url=URL.createObjectURL(new Blob(['\uFEFF'+rows.map(row=>row.map(cell).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'}))
  const anchor=document.createElement('a');anchor.href=url;anchor.download=filename;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000)
}
