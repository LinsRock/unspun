import { useEffect, useRef, useState } from 'react'
import { App as AntApp, Button, ConfigProvider, Drawer, Menu, Space, Tag, Typography, theme } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { DashboardOutlined, DollarOutlined, DatabaseOutlined, FileTextOutlined, ClockCircleOutlined, SettingOutlined, MoonOutlined, SunOutlined, ArrowLeftOutlined } from '@ant-design/icons'
import { DateRange } from './shared'
import { Overview, Costs, Sources, Content, Runs, Configuration, type PageProps } from './pages'
import { DetailBody, detailTitle, type Detail } from './DetailDrawer'
import { dateISO, defaultView, initialExpenses, presets, timeLabel, type Expense, type Page, type Range, type View } from './data'

const pages:Record<Page,{label:string;subtitle:string;icon:React.ReactNode}>= {
  overview:{label:'总览',subtitle:'当前状态、区间产出与成本。',icon:<DashboardOutlined/>},
  costs:{label:'费用',subtitle:'从全部运行成本到每次调用。',icon:<DollarOutlined/>},
  sources:{label:'信息源',subtitle:'查看来源产出与抓取稳定性。',icon:<DatabaseOutlined/>},
  content:{label:'文章与事件',subtitle:'查看原文证据、处理结果与事件归属。',icon:<FileTextOutlined/>},
  runs:{label:'运行与任务',subtitle:'查询历史运行与当前积压。',icon:<ClockCircleOutlined/>},
  config:{label:'配置与操作记录',subtitle:'当前配置与可追踪的操作。',icon:<SettingOutlined/>},
}
function readURL():{range:Range;view:View}{
  const query=new URLSearchParams(location.search),page=location.hash.slice(1) as Page
  const view:View={...defaultView,page:pages[page]?page:'overview'}
  for(const key of ['tab','query','sort','health','purpose','model','source','basis','mode'] as const)if(query.has(key))view[key]=query.get(key)!
  view.pageNo=Math.max(1,Number(query.get('pageNo'))||1)
  if(query.has('zoomStart'))view.zoom={start:Number(query.get('zoomStart')),end:Number(query.get('zoomEnd')),label:'图表时段'}
  const start=Number(query.get('start')),end=Number(query.get('end'))
  return {view,range:query.has('start')&&Number.isFinite(start)&&Number.isFinite(end)&&start<end?{start,end,label:query.get('range')||'自定义'}:presets[0]}
}
function writeURL(range:Range,view:View){
  const q=new URLSearchParams({start:String(range.start),end:String(range.end),range:range.label})
  for(const key of ['tab','query','sort','health','purpose','model','source','basis','mode','pageNo'] as const)if(view[key])q.set(key,String(view[key]))
  if(view.zoom){q.set('zoomStart',String(view.zoom.start));q.set('zoomEnd',String(view.zoom.end))}
  history.replaceState(null,'',`${location.pathname}?${q}#${view.page}`)
}
function Workspace({dark,setDark}:{dark:boolean;setDark:(dark:boolean)=>void}){
  const initial=useRef(readURL()).current,[range,setRange]=useState(initial.range),[view,setView]=useState(initial.view),[expenses,setExpenses]=useState<Expense[]>(initialExpenses.map(e=>({...e}))),[details,setDetails]=useState<Detail[]>([]),saved=useRef<Partial<Record<Page,View>>>({}),{message}=AntApp.useApp()
  useEffect(()=>writeURL(range,view),[range,view])
  useEffect(()=>{const restore=()=>{const next=readURL();setRange(next.range);setView(next.view);setDetails([])};window.addEventListener('popstate',restore);return ()=>window.removeEventListener('popstate',restore)},[])
  const push=()=>{writeURL(range,view);history.pushState(null,'',location.href)}
  const navigate=(page:Page,tab='',filters:Partial<View>={},fresh=true)=>{
    saved.current[view.page]=view;push();setDetails([])
    setView({...defaultView,...(!fresh?saved.current[page]??{}:{}),page,...(tab?{tab}:{}),...filters});window.scrollTo(0,0)
  }
  const update=(patch:Partial<View>)=>setView(v=>({...v,...patch}))
  const onDetail=(type:string,id:string|number)=>setDetails(ds=>[...ds,{type,id}])
  const onRange=(next:Range)=>{push();setRange(next);update({zoom:undefined,pageNo:1})}
  const props:PageProps={range,view,expenses,onUpdate:update,onNavigate:navigate,onDetail,onExpense:e=>setExpenses(es=>[...es,e]),onPaid:id=>{setExpenses(es=>es.map(e=>e.id===id?{...e,paid:'2026-10-12'}:e));message.success('演示付款已记录，不执行真实支付')}}
  const menuItems=Object.entries(pages).map(([key,p])=>({key,label:p.label,icon:p.icon}))
  const Component={overview:Overview,costs:Costs,sources:Sources,content:Content,runs:Runs,config:Configuration}[view.page]
  const detail=details.at(-1)
  return <><aside className="sidebar"><a className="brand" href="#overview" onClick={e=>{e.preventDefault();navigate('overview','',{},false)}}><span className="brand-mark">u</span>unspun <small>管理后台</small></a><div className="nav-label">工作区</div><Menu selectedKeys={[view.page]} items={menuItems} onClick={e=>navigate(e.key as Page,'',{},false)} mode="inline" className="desktop-menu"/><Menu selectedKeys={[view.page]} items={menuItems} onClick={e=>navigate(e.key as Page,'',{},false)} mode="horizontal" className="mobile-menu"/><Button className="theme-toggle" icon={dark?<SunOutlined/>:<MoonOutlined/>} onClick={()=>setDark(!dark)}>切换深浅色</Button></aside>
    <main><header><div><div className="eyebrow">UNSPUN / WORKSPACE</div><h1>{pages[view.page].label}</h1><Typography.Text type="secondary">{pages[view.page].subtitle}</Typography.Text></div><Tag>React 原型 · 示例数据</Tag></header><DateRange range={range} onChange={onRange}/>
      {view.zoom&&<div className="drill-context"><Button type="link" size="small" icon={<ArrowLeftOutlined/>} onClick={()=>history.back()}>返回上一页</Button><span>时段 {timeLabel(view.zoom.start)} — {timeLabel(view.zoom.end)}</span><Button size="small" onClick={()=>update({zoom:undefined,pageNo:1})}>清除时段</Button></div>}
      <Component {...props}/><footer>示例时点 2026-10-12 14:00 · 账务操作仅在本次演示生效</footer>
    </main>
    <Drawer open={!!detail} title={detail?detailTitle(detail):''} onClose={()=>setDetails([])} size={Math.min(620,window.innerWidth)} extra={details.length>1?<Button size="small" onClick={()=>setDetails(ds=>ds.slice(0,-1))} icon={<ArrowLeftOutlined/>}>返回详情</Button>:null}>
      {detail&&<DetailBody detail={detail} range={range} onDetail={onDetail} onSourceArticles={source=>navigate('content','文章',{source})}/>}
    </Drawer>
  </>
}
export default function AdminApp(){
  const [dark,setDark]=useState(matchMedia('(prefers-color-scheme: dark)').matches)
  useEffect(()=>{document.documentElement.dataset.theme=dark?'dark':'light'},[dark])
  return <ConfigProvider locale={zhCN} componentSize="middle" theme={{algorithm:dark?theme.darkAlgorithm:theme.defaultAlgorithm,token:{colorPrimary:dark?'#6fb0d8':'#22608f',colorBgLayout:dark?'#15171a':'#faf8f4',colorBgContainer:dark?'#1c1f23':'#ffffff',colorText:dark?'#e9ebed':'#2a2722',colorBorder:dark?'#373b40':'#e7e2d8',colorSuccess:dark?'#72bd96':'#3a7d5d',colorWarning:dark?'#d2ab61':'#9a701f',colorError:dark?'#e07b5c':'#b5432a',borderRadius:8,fontFamily:'-apple-system, system-ui, "PingFang SC", sans-serif',fontSize:13},components:{Card:{headerFontSize:15},Table:{cellPaddingBlock:14,headerBg:dark?'#212529':'#fdfcf9'},Menu:{itemHeight:43,itemSelectedBg:dark?'rgba(111,176,216,.13)':'rgba(34,96,143,.09)'}}}}><AntApp><Workspace dark={dark} setDark={setDark}/></AntApp></ConfigProvider>
}
