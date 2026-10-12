import { Button, Descriptions, Empty, Table, Timeline, Typography } from 'antd'
import { articles, calls, fetches, runs, sourceName, sources, sourceStats, timeLabel, titles, money, within, type Range } from './data'
import { Status, Explanation } from './shared'

export interface Detail { type:string; id:string | number }
export function detailTitle(detail:Detail){
  if(detail.type==='source')return sourceName(String(detail.id))
  if(detail.type==='article')return articles.find(a=>a.id===Number(detail.id))?.title??'文章'
  if(detail.type==='event')return titles[Number(detail.id)]
  return `${detail.type==='call'?'调用':'运行'} #${detail.id}`
}
export function DetailBody({detail,range,onDetail,onSourceArticles}:{detail:Detail;range:Range;onDetail:(type:string,id:string|number)=>void;onSourceArticles:(source:string)=>void}){
  const id=Number(detail.id)
  if(detail.type==='source'){
    const source=sources.find(s=>s.id===detail.id)
    if(!source)return <Empty description="未找到来源"/>
    const stat=sourceStats(source,range),logs=fetches.filter(f=>f.source===source.id&&within(f.time,range)).slice(-6).reverse()
    return <><Descriptions column={2} size="small" items={[{key:'status',label:'当前状态',children:<Status value={source.bad?'最近超时':'正常'}/>},{key:'count',label:'期间产出',children:`${stat.articles} 篇`},{key:'kind',label:'地区 / 类型',children:`${source.region} / ${source.kind}`},{key:'timeout',label:'当前超时',children:source.bad?'60 秒':'20 秒'}]}/><Typography.Title level={5}>最近抓取 · 所选期间</Typography.Title><Table rowKey="id" dataSource={logs} pagination={false} size="small" columns={[{title:'时间',dataIndex:'time',render:timeLabel},{title:'结果',dataIndex:'status',render:value=><Status value={value}/>},{title:'错误',dataIndex:'error',render:value=>value??'—'}]}/><Button type="primary" className="detail-action" onClick={()=>onSourceArticles(source.id)}>查看该源文章 →</Button><Explanation>启停与手动抓取在 M3-C 加入，当前原型只做查询。</Explanation></>
  }
  if(detail.type==='article'){
    const a=articles.find(item=>item.id===id)
    if(!a)return <Empty description="未找到文章"/>
    return <><Descriptions column={2} size="small" items={[{key:'source',label:'来源',children:sourceName(a.source)},{key:'status',label:'状态',children:<Status value={a.status}/>},{key:'published',label:'报道时间',children:timeLabel(a.published)},{key:'fetched',label:'系统入库',children:timeLabel(a.time)}]}/><Typography.Title level={5}>中文摘要 · 示例</Typography.Title><Typography.Paragraph>该示例用于查看文章、证据和事件归属。来源发布时间与系统入库时间分别保留，不代表真实新闻。</Typography.Paragraph><Typography.Title level={5}>原文依据 · 示例</Typography.Title><Typography.Paragraph className="evidence">“新数据与相关方法已公布，仍需进一步研究。”</Typography.Paragraph><Button className="detail-action" onClick={()=>onDetail('event',a.event)}>查看所属事件 →</Button><Explanation>精选准入与实质进展尚未记录，随 M3-D/E 接入。</Explanation></>
  }
  if(detail.type==='event'){
    const xs=articles.filter(a=>a.event===id).sort((a,b)=>a.published-b.published)
    if(!xs.length)return <Empty description="未找到事件"/>
    return <><Descriptions column={2} size="small" items={[{key:'first',label:'最早报道',children:timeLabel(xs[0].published)},{key:'latest',label:'最新报道',children:timeLabel(xs.at(-1)!.published)},{key:'count',label:'文章 / 报道来源',children:`${xs.length} / ${new Set(xs.map(a=>a.source)).size}`},{key:'score',label:'综合分（示例）',children:70+id*3}]}/><Typography.Title level={5}>报道时间线 · 最近 5 篇</Typography.Title><Timeline items={xs.slice(-5).map(a=>({content:<><Typography.Text type="secondary">{timeLabel(a.published)} · {sourceName(a.source)}</Typography.Text><br/><Button type="link" size="small" onClick={()=>onDetail('article',a.id)}>文章 #{a.id} →</Button></>}))}/><Explanation>报道时间线不等于实质进展。聚类纠正在 M3-C 提供，不修改旧日报快照。</Explanation></>
  }
  if(detail.type==='call'){
    const c=calls.find(item=>item.id===id)
    if(!c)return <Empty description="未找到调用"/>
    return <><Descriptions column={1} bordered size="small" items={[{key:'purpose',label:'用途',children:c.purpose},{key:'model',label:'模型',children:c.model},{key:'time',label:'时间',children:timeLabel(c.time)},{key:'token',label:'输入 / 输出 token',children:`${c.input} / ${c.output}`},{key:'cost',label:'记录费用',children:money(c.cost)}]}/><Button className="detail-action" onClick={()=>onDetail('article',c.article)}>查看关联文章 #{c.article} →</Button><Explanation>本示例具有关联；旧生产记录缺失的字段显示“未记录”。费用记录不等同供应商账单。</Explanation></>
  }
  const run=runs.find(r=>r.id===id)
  if(!run)return <Empty description="未找到运行"/>
  return <><Descriptions column={1} size="small" items={[{key:'time',label:'记录时间',children:timeLabel(run.time)},{key:'end',label:'结束时间 / 耗时',children:'未记录 / 未记录'}]}/><Table rowKey="stage" size="small" pagination={false} dataSource={[{stage:'摘要',count:run.summarized},{stage:'embedding',count:run.embedded},{stage:'聚类',count:run.clustered},{stage:'评分',count:run.scored}]} columns={[{title:'阶段',dataIndex:'stage'},{title:'处理量',dataIndex:'count'},{title:'结果',render:()=> '未记录'}]}/><Explanation>处理量不证明整轮成功，阶段结果与恢复记录在 M3-C 补充。</Explanation></>
}
