import { useState } from 'react'
import { App, Alert, Button, Descriptions, Empty, Form, Input, InputNumber, Modal, Popconfirm, Progress, Segmented, Select, Space, Statistic, Table, Tabs, Typography, DatePicker } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { ArrowRightOutlined, DownloadOutlined, PlusOutlined } from '@ant-design/icons'
import dayjs, { type Dayjs } from 'dayjs'
import { Panel, Explanation, OverviewTrend, Trend, Status } from './shared'
import { articles, calls, fetches, sources, sourceStats, sourceName, titles, totals, totalCalls, runs, timeLabel, money, within, scopedRange, downloadCSV, dateISO, midnight, dayMs, type Article, type Expense, type View, type Range, type Page, type Bucket } from './data'

export interface PageProps {
  range:Range; view:View; expenses:Expense[]; onUpdate:(patch:Partial<View>)=>void;
  onNavigate:(page:Page,tab?:string,filters?:Partial<View>)=>void;
  onDetail:(type:string,id:string|number)=>void; onExpense:(expense:Expense)=>void; onPaid:(id:number)=>void
}
function Search({value,onChange,placeholder='搜索名称或关键词'}:{value:string;onChange:(query:string)=>void;placeholder?:string}){
  return <Input.Search allowClear placeholder={placeholder} value={value} onChange={e=>onChange(e.target.value)} onSearch={onChange} className="search"/>
}
export function Overview(props:PageProps){
  const {range,onNavigate,onDetail,expenses}=props,t=totals(range,expenses),logs=fetches.filter(f=>within(f.time,range)),count=articles.filter(a=>within(a.time,range)).length
  const rate=logs.length?`${(logs.filter(f=>f.status==='成功').length/logs.length*100).toFixed(1)}%`:'—'
  const failed=articles.filter(a=>a.status==='失败').length,pending=articles.filter(a=>a.status==='待摘要').length
  const metric=(label:string,value:string|number,target:Page,tab:string,action:string)=><button className="metric" onClick={()=>onNavigate(target,tab)}><span>{label}</span><strong>{value}</strong><small>{action} <ArrowRightOutlined/></small></button>
  const onBucket=(b:Bucket,type:'articles'|'cost')=>onNavigate(type==='cost'?'costs':'content',type==='cost'?'调用明细':'文章',{zoom:{start:b.start,end:b.end,label:'图表时段'}})
  return <><div className="overview-kpis">{metric('新入库文章',count,'content','文章','查看文章')}{metric('期间总成本',money(t.llm+t.fixed),'costs','费用构成','查看费用构成')}{metric('抓取成功率',rate,'sources','',`${logs.length} 次抓取 · 查看来源`)}</div><OverviewTrend range={range} onBucket={onBucket}/>
    <div className="section-heading"><span>当前状态</span><Space><Typography.Text type="secondary">最近轮次 13:00</Typography.Text><Button type="link" size="small" onClick={()=>onDetail('run',runs.at(-1)!.id)}>查看记录 →</Button></Space></div>
    <div className="overview-status"><button className="status-card" onClick={()=>onNavigate('sources')}><div><span>信息源</span><strong>8 <small>个启用</small></strong></div><div><Status value="异常"/><small>查看全部信息源 →</small></div></button><button className="status-card" onClick={()=>onNavigate('runs','待处理与失败')}><div><span>内容处理</span><strong>{pending} <small>篇待摘要</small></strong></div><div><Status value="失败"/><small>{failed} 篇失败 · 查看 →</small></div></button></div>
    <Panel title="需要关注" extra={<Typography.Text type="secondary">2 项</Typography.Text>}><button className="attention-row" onClick={()=>onDetail('source','nhk')}><span className="attention-icon bad">!</span><span><strong>NHK World 抓取超时</strong><small>当前异常 · 查看抓取记录</small></span><ArrowRightOutlined/></button><button className="attention-row" onClick={()=>onNavigate('costs','固定账目')}><span className="attention-icon">↻</span><span><strong>备份服务将在 6 天后续费</strong><small>10 月 18 日 · $1.50 · 待付款</small></span><ArrowRightOutlined/></button></Panel>
  </>
}
interface ExpenseInput { name:string;category:string;amount:number;currency:string;cycle:string;coverage:[Dayjs,Dayjs];paid:string }
export function Costs(props:PageProps){
  const {range,view,onUpdate,expenses,onDetail,onExpense,onPaid}=props,t=totals(range,expenses),[form]=Form.useForm<ExpenseInput>(),[adding,setAdding]=useState(false),{message}=App.useApp()
  const period=scopedRange(range,view)
  const list=calls.filter(c=>within(c.time,period)&&(view.purpose==='全部用途'||c.purpose===view.purpose)&&(view.model==='全部模型'||c.model===view.model)&&(c.model+c.purpose).toLowerCase().includes(view.query.toLowerCase())).reverse()
  const tab=['费用构成','调用明细','固定账目'].includes(view.tab)?view.tab:'费用构成'
  const callColumns:ColumnsType<typeof calls[number]>=[
    {title:'时间',dataIndex:'time',render:v=>timeLabel(v),width:125},
    {title:'用途',dataIndex:'purpose',width:100},
    {title:'模型',dataIndex:'model',render:(v,c)=><><span>{v}</span><small>关联文章 #{c.article}</small></>},
    {title:'输入 / 输出',responsive:['lg'],render:(_,c)=>`${c.input} / ${c.output}`,width:140},
    {title:'费用',dataIndex:'cost',render:v=><span className="num">{money(v)}</span>,width:110},
    {title:'',render:(_,c)=><Button type="link" size="small" onClick={()=>onDetail('call',c.id)}>详情</Button>,width:65},
  ]
  const expenseColumns:ColumnsType<Expense>=[
    {title:'名称',dataIndex:'name',render:(v,e)=><><b>{v}</b><small>{e.category}{e.category==='充值'?' · 仅计实际支出':''}</small></>},
    {title:'金额',render:(_,e)=><span className="num">{e.currency} {e.amount.toFixed(2)}</span>,width:115},
    {title:'周期与覆盖',responsive:['md'],render:(_,e)=><>{e.cycle}<small>{e.start} → {e.end}</small></>},
    {title:'付款',render:(_,e)=><><Status value={e.paid?'已确认':'待付款'}/><small>{e.paid??'未计实际支出'}</small></>},
    {title:'',render:(_,e)=>e.paid?'已记录':<Popconfirm title="确认这笔示例账目已付款？" description="仅更新演示，不执行真实支付。" onConfirm={()=>onPaid(e.id)}><Button size="small">确认付款</Button></Popconfirm>},
  ]
  const selected=calls.filter(c=>within(c.time,period)),purposes=[...new Set(calls.map(c=>c.purpose))]
  const grouped=purposes.map(p=>{const xs=selected.filter(c=>c.purpose===p);return {purpose:p,count:xs.length,cost:totalCalls(xs)}})
  const items=[
    {key:'费用构成',label:'费用构成',children:<><Table rowKey="purpose" dataSource={grouped} pagination={false} columns={[{title:'用途',dataIndex:'purpose'},{title:'调用次数',dataIndex:'count'},{title:'记录费用',dataIndex:'cost',render:money},{title:'',render:(_,row)=><Button type="link" size="small" onClick={()=>onUpdate({tab:'调用明细',purpose:row.purpose,model:'全部模型',query:'',pageNo:1})}>查看调用 →</Button>} ]}/><div className="result-meta">固定费用分摊 {money(t.fixed)}<Button type="link" onClick={()=>onUpdate({tab:'固定账目'})}>查看账目 →</Button></div></>},
    {key:'调用明细',label:'调用明细',children:<><div className="toolbar"><Search value={view.query} onChange={query=>onUpdate({query,pageNo:1})}/><Select aria-label="用途筛选" value={view.purpose} options={['全部用途',...purposes].map(value=>({value,label:value}))} onChange={purpose=>onUpdate({purpose,pageNo:1})}/><Select aria-label="模型筛选" value={view.model} options={['全部模型',...new Set(calls.map(c=>c.model))].map(value=>({value,label:value}))} onChange={model=>onUpdate({model,pageNo:1})}/><Button icon={<DownloadOutlined/>} onClick={()=>downloadCSV('demo-calls.csv',[['ID','时间','用途','模型','费用'],...list.map(c=>[c.id,timeLabel(c.time),c.purpose,c.model,c.cost])])}>导出</Button></div><div className="result-meta"><span>{list.length} 次调用</span><span>筛选小计 <b className="num">{money(totalCalls(list))}</b></span></div><Table rowKey="id" columns={callColumns} dataSource={list} pagination={{current:view.pageNo,pageSize:8,showSizeChanger:false,onChange:pageNo=>onUpdate({pageNo})}} scroll={{x:560}}/></>},
    {key:'固定账目',label:'固定账目',children:<><div className="toolbar ledger-toolbar"><Typography.Text type="secondary">账目与周期规则</Typography.Text><Button type="primary" icon={<PlusOutlined/>} onClick={()=>{form.resetFields();setAdding(true)}}>新增费用</Button></div><Table rowKey="id" columns={expenseColumns} dataSource={expenses} pagination={false} scroll={{x:520}}/><Alert className="renewal" type="info" showIcon title="站内续费提醒" description="备份服务 10 月 18 日 $1.50；VPS 11 月 1 日 $6.00。提醒不会自动扣款。"/></>},
  ]
  const save=async()=>{
    const values=await form.validateFields(),start=values.coverage[0].format('YYYY-MM-DD'),end=values.coverage[1].format('YYYY-MM-DD')
    onExpense({id:Math.max(...expenses.map(e=>e.id))+1,name:values.name,category:values.category,amount:values.amount,currency:values.currency,cycle:values.cycle,start,end,paid:values.paid||null,due:values.cycle==='一次性'?null:dateISO(midnight(end)+dayMs)})
    setAdding(false);message.success('已保存演示账目；刷新后恢复示例')
  }
  return <><Segmented value={view.mode} options={['期间成本','实际支出']} onChange={mode=>onUpdate({mode:String(mode)})}/><div className="cost-summary"><div><span>{view.mode==='期间成本'?'已确认期间总成本':'已确认实际支出'}</span><strong>{money(view.mode==='期间成本'?t.llm+t.fixed:t.cash)}</strong><small>{view.mode==='期间成本'?'按调用与覆盖期统计':'按确认付款日期'}</small></div><div><span>模型调用消耗</span><strong>{money(t.llm)}</strong><small>{t.count} 次调用</small></div><div><span>固定费用分摊</span><strong>{money(t.fixed)}</strong><small>待确认 {money(t.estimated)} · 单列预计</small></div></div><div className="budget"><span>本月模型预算 {money(totalCalls(calls))} / $50.00</span><Progress percent={totalCalls(calls)/50*100} size="small" showInfo={false} style={{width:100}}/><span>固定对应 10 月</span></div><Panel title="调用费用趋势" extra="USD"><Trend range={range} type="cost" onBucket={b=>props.onNavigate('costs','调用明细',{zoom:{start:b.start,end:b.end,label:'图表时段'}})}/></Panel><Panel title="费用明细"><Tabs activeKey={tab} items={items} onChange={tab=>onUpdate({tab,query:'',pageNo:1})}/></Panel><Explanation>汇总币种 USD；演示汇率 CNY / USD = 7.10。充值记支出，调用消耗记成本；两种口径不相加。模型／用途筛选仅作用调用，不过滤固定费用。</Explanation>
    <Modal title="新增费用 · 演示" open={adding} onCancel={()=>setAdding(false)} onOk={()=>void save().catch(()=>{})} okText="保存演示账目" destroyOnHidden>
      <Form form={form} layout="vertical" initialValues={{amount:6,currency:'USD',category:'服务器',cycle:'月付',coverage:[dayjs('2026-10-01'),dayjs('2026-10-31')],paid:''}}>
        <Form.Item label="名称" name="name" rules={[{required:true,message:'请输入费用名称'},{max:60,message:'名称最多 60 字'}]}><Input/></Form.Item>
        <div className="form-grid"><Form.Item label="金额" name="amount" rules={[{required:true,message:'请输入金额'},{type:'number',min:.01,message:'金额必须大于零'}]}><InputNumber min={.01} precision={2} style={{width:'100%'}}/></Form.Item><Form.Item label="币种" name="currency"><Select options={['USD','CNY'].map(value=>({value}))}/></Form.Item></div>
        <div className="form-grid"><Form.Item label="类别" name="category"><Select options={['服务器','域名','存储','其他','充值'].map(value=>({value}))}/></Form.Item><Form.Item label="周期" name="cycle"><Select options={['月付','年付','一次性'].map(value=>({value}))}/></Form.Item></div>
        <Form.Item label="服务覆盖期间" name="coverage" rules={[{required:true,message:'请选择完整覆盖期间'}]}><DatePicker.RangePicker allowClear={false}/></Form.Item><Form.Item label="付款状态" name="paid"><Select options={[{value:'',label:'待付款'},{value:'2026-10-12',label:'已确认付款（演示今日）'}]}/></Form.Item>
        <Typography.Text type="secondary">仅保存演示账目，不执行真实付款或后台续费。</Typography.Text>
      </Form>
    </Modal>
  </>
}
export function Sources(props:PageProps){
  const {range,view,onUpdate,onDetail}=props,stats=sources.map(s=>sourceStats(s,range))
  const list=stats.filter(s=>(s.name+s.language+s.region+s.kind).toLowerCase().includes(view.query.toLowerCase())&&(view.health==='全部状态'||(view.health==='异常'?s.bad:!s.bad)))
  list.sort((a,b)=>view.sort==='文章产出'?b.articles-a.articles:view.sort==='失败率'?(a.rate??1)-(b.rate??1):view.sort==='名称'?a.name.localeCompare(b.name):view.sort==='最近成功时间'?(b.lastSuccess??0)-(a.lastSuccess??0):Number(b.bad)-Number(a.bad)||b.articles-a.articles)
  const columns:ColumnsType<typeof list[number]>=[{title:'来源',render:(_,s)=><><b>{s.name}</b><small>{s.language} · {s.region} · {s.kind}</small></>},{title:'当前状态',render:(_,s)=><Status value={s.bad?'最近超时':'正常'}/>},{title:'期间产出',dataIndex:'articles',render:v=>`${v} 篇`},{title:'成功 / 失败',render:(_,s)=>`${s.ok} / ${s.fail}`},{title:'成功率',responsive:['lg'],render:(_,s)=>s.rate===null?'暂无记录':`${(s.rate*100).toFixed(1)}%`},{title:'最近成功',responsive:['lg'],render:(_,s)=>s.lastSuccess?timeLabel(s.lastSuccess):'暂无记录'},{title:'',render:(_,s)=><Button type="link" size="small" onClick={()=>onDetail('source',s.id)}>详情</Button>}]
  return <><div className="source-summary"><span>当前 <b>8</b> 个源 · 全部启用</span><span>期间成功 <b>{stats.filter(s=>s.ok>0).length}</b></span><span>有产出 <b>{stats.filter(s=>s.articles>0).length}</b></span><span>有失败 <b>{stats.filter(s=>s.fail>0).length}</b></span></div><Panel title="信息源清单" extra={`${list.length} 个结果`}><div className="toolbar"><Search value={view.query} onChange={query=>onUpdate({query})}/><Select aria-label="来源状态" value={view.health} options={['全部状态','异常','正常'].map(value=>({value}))} onChange={health=>onUpdate({health})}/><Select aria-label="来源排序" value={view.sort} options={['异常优先','文章产出','失败率','最近成功时间','名称'].map(value=>({value}))} onChange={sort=>onUpdate({sort})}/></div><Table columns={columns} dataSource={list} rowKey="id" pagination={false} scroll={{x:560}}/></Panel><Explanation>当前健康与期间成功率分开。抓取成功但没有新文章不算异常。</Explanation></>
}
export function Content(props:PageProps){
  const {range,view,onUpdate,onDetail}=props,period=scopedRange(range,view),tab=view.tab==='事件'?'事件':'文章'
  const xs=articles.filter(a=>within(view.basis==='报道时间'?a.published:a.time,period)&&(!view.source||a.source===view.source)&&(a.title+sourceName(a.source)).includes(view.query)).sort((a,b)=>(view.basis==='报道时间'?b.published-a.published:b.time-a.time)||b.id-a.id)
  const events=titles.map((title,id)=>{const rows=articles.filter(a=>a.event===id);return {id,title,earliest:Math.min(...rows.map(a=>a.published)),latest:Math.max(...rows.map(a=>a.published)),count:rows.length,sources:new Set(rows.map(a=>a.source)).size}}).filter(e=>within(e.earliest,period)&&e.title.includes(view.query)&&(!view.source||articles.some(a=>a.event===e.id&&a.source===view.source))).sort((a,b)=>b.earliest-a.earliest)
  const columns:ColumnsType<Article>=[{title:'文章',render:(_,a)=><><b>{a.title}</b><small>#{a.id} · {a.quality}</small></>},{title:'来源',dataIndex:'source',render:sourceName},{title:'报道 / 入库时间',responsive:['md'],render:(_,a)=><>{timeLabel(a.published)}<small>入库 {timeLabel(a.time)}</small></>},{title:'状态',dataIndex:'status',render:value=><Status value={value}/>},{title:'',render:(_,a)=><Button type="link" size="small" onClick={()=>onDetail('article',a.id)}>详情</Button>}]
  return <Panel title="内容查询"><Tabs activeKey={tab} items={[{key:'文章',label:'文章'},{key:'事件',label:'事件'}]} onChange={tab=>onUpdate({tab,query:'',pageNo:1})}/><Space wrap>{view.source&&<Typography.Text>来源：{sourceName(view.source)} <Button size="small" onClick={()=>onUpdate({source:undefined})}>清除</Button></Typography.Text>}</Space><div className="toolbar"><Search value={view.query} onChange={query=>onUpdate({query,pageNo:1})}/>{tab==='文章'&&<><Select aria-label="文章时间口径" value={view.basis} options={['入库时间','报道时间'].map(value=>({value}))} onChange={basis=>onUpdate({basis,pageNo:1})}/><Button icon={<DownloadOutlined/>} onClick={()=>downloadCSV('demo-articles.csv',[['ID','标题','来源','报道时间','入库时间'],...xs.map(a=>[a.id,a.title,sourceName(a.source),timeLabel(a.published),timeLabel(a.time)])])}>导出</Button></>}</div>
  {tab==='文章'?<Table rowKey="id" columns={columns} dataSource={xs} pagination={{pageSize:8,current:view.pageNo,showSizeChanger:false,onChange:pageNo=>onUpdate({pageNo})}} scroll={{x:550}}/>:<><Typography.Paragraph type="secondary">按最早报道时间筛选、倒序排列；重复报道不会把旧事件变成新事件。</Typography.Paragraph><Table rowKey="id" dataSource={events} pagination={false} columns={[{title:'事件',dataIndex:'title'},{title:'最早报道',dataIndex:'earliest',render:timeLabel},{title:'文章 / 报道来源',render:(_,e)=>`${e.count} / ${e.sources}`},{title:'',render:(_,e)=><Button type="link" size="small" onClick={()=>onDetail('event',e.id)}>详情</Button>}]} scroll={{x:520}} locale={{emptyText:<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="此期间没有首次报道的新事件；旧事件的新文章可在文章页查询。"/>}}/></>}
  </Panel>
}
export function Runs(props:PageProps){
  const {range,view,onUpdate,onDetail}=props,tab=['运行历史','待处理与失败','手动任务'].includes(view.tab)?view.tab:'运行历史',xs=runs.filter(r=>within(r.time,range)).reverse()
  const items=[{key:'运行历史',label:'运行历史',children:<Table rowKey="id" dataSource={xs} pagination={{current:view.pageNo,pageSize:8,showSizeChanger:false,onChange:pageNo=>onUpdate({pageNo})}} columns={[{title:'记录时间',dataIndex:'time',render:timeLabel},{title:'摘要 / 聚类',render:(_,r)=>`${r.summarized} / ${r.clustered}`},{title:'耗时',render:()=> '未记录'},{title:'',render:(_,r)=><Button type="link" size="small" onClick={()=>onDetail('run',r.id)}>详情</Button>}]}/>},{key:'待处理与失败',label:'待处理与失败',children:<><Typography.Paragraph type="secondary">当前积压，不随日期筛选变化。</Typography.Paragraph><Table rowKey="id" dataSource={articles.filter(a=>a.status!=='完成')} pagination={{pageSize:8,showSizeChanger:false}} columns={[{title:'文章',dataIndex:'title'},{title:'阶段',render:()=> '摘要'},{title:'状态',dataIndex:'status',render:value=><Status value={value}/>},{title:'',render:(_,a)=><Button type="link" size="small" onClick={()=>onDetail('article',a.id)}>详情</Button>}]}/></>},{key:'手动任务',label:'手动任务',children:<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="手动任务队列在 M3-C 交付，查询版不伪造历史任务。"/>}]
  return <Panel title="运行与任务"><Tabs activeKey={tab} items={items} onChange={tab=>onUpdate({tab,pageNo:1})}/><Explanation>旧记录缺少结束时间和阶段状态，已有处理数量不证明整轮成功。</Explanation></Panel>
}
export function Configuration(props:PageProps){
  const {view,onUpdate,onDetail}=props,tab=['信息源配置','管线与预算','变更与操作记录'].includes(view.tab)?view.tab:'管线与预算'
  const items=[{key:'信息源配置',label:'信息源配置',children:<Table rowKey="id" dataSource={sources} pagination={false} columns={[{title:'来源',dataIndex:'name'},{title:'权重',render:(_,s)=>s.kind==='社区'?.3:1},{title:'超时',render:(_,s)=>s.id==='nhk'?'60s':'20s'},{title:'',render:(_,s)=><Button type="link" size="small" onClick={()=>onDetail('source',s.id)}>详情</Button>}]}/>},{key:'管线与预算',label:'管线与预算',children:<Descriptions column={1} bordered size="small" items={[{key:'1',label:'抓取间隔',children:'30 分钟'},{key:'2',label:'日报时间',children:'08:00 · Asia/Shanghai'},{key:'3',label:'摘要批次',children:'50'},{key:'4',label:'模型月预算',children:'$50.00（示例）'},{key:'5',label:'审核限额',children:'$0.40 / 滚动 24 小时'},{key:'6',label:'模型凭证',children:'已配置（不显示明文）'}]}/>},{key:'变更与操作记录',label:'变更与操作记录',children:<Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="生产审计尚未记录；配置与任务审计在 M3-C 接入。"/>}]
  return <Panel title="配置与操作记录"><Tabs activeKey={tab} items={items} onChange={tab=>onUpdate({tab})}/><Explanation>查询版只读。长期修改走配置 PR；紧急停源与暂停付费处理采用有限临时覆盖。</Explanation></Panel>
}
