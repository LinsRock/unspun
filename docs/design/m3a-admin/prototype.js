/* Local design fixture: no API calls, production credentials, or server writes. */
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const asOf = Date.parse('2026-10-12T14:00:00+08:00');
const dayMs = 86400000;
const pages = {
  overview:['总览','◫','当前运行状态，与所选期间的产出和成本。'],
  costs:['费用','＄','从总成本到每次调用，查看费用的来源。'],
  sources:['信息源','⊞','查产出、稳定性和每一次抓取结果。'],
  content:['文章与事件','▤','沿着原文、证据与事件归属理解处理结果。'],
  runs:['运行与任务','◷','查看历史运行，以及当前待处理与失败项。'],
  config:['配置与操作记录','⚙','查看当前配置，追踪已记录的变更。'],
};
const sources = [
  {id:'nhk',name:'NHK World',lang:'英文',region:'东亚',kind:'公共媒体',bad:true},
  {id:'nasa',name:'NASA',lang:'英文',region:'北美',kind:'官方',bad:false},
  {id:'bbc',name:'BBC World',lang:'英文',region:'欧洲',kind:'公共媒体',bad:false},
  {id:'caixin',name:'财新',lang:'中文',region:'东亚',kind:'新闻媒体',bad:false},
  {id:'quanta',name:'Quanta Magazine',lang:'英文',region:'北美',kind:'科学媒体',bad:false},
  {id:'carbon',name:'Carbon Brief',lang:'英文',region:'欧洲',kind:'专业媒体',bad:false},
  {id:'psyche',name:'Psyche',lang:'英文',region:'欧洲',kind:'人文媒体',bad:false},
  {id:'hn',name:'Hacker News',lang:'英文',region:'北美',kind:'社区',bad:false},
];
const stories = ['新一轮月球观测数据公开','区域洪水救援进入恢复阶段','央行公布政策会议纪要','研究团队公布新材料实验结果','城市启动公共交通试点','一项心理学研究重新评估记忆机制'];
const articles=[]; const calls=[]; const fetches=[]; const runs=[];
for(let day=1;day<=12;day++) {
  for(let hour of [2,6,10,13]) {
    const time=`2026-10-${String(day).padStart(2,'0')}T${String(hour).padStart(2,'0')}:00:00+08:00`;
    sources.forEach((s,i)=>fetches.push({source:s.id,time,status:s.bad && (day+hour)%3!==0?'error':'ok',error:s.bad?'读取上游超时（示例）':null}));
    runs.push({id:runs.length+1,time,summarized:6+(day%5),embedded:9,clustered:8,scored:4});
    for(let n=0;n<3+(day%4);n++) {
      const id=articles.length+1, source=sources[(day+hour+n)%sources.length], event=(day+n)%stories.length;
      articles.push({id,source:source.id,event,time,published:new Date(Date.parse(time)-(n%3)*dayMs).toISOString(),title:stories[event],status:id%17===0?'失败':id%13===0?'待摘要':'完成',quality:id%11===0?'信息有限':'有原文依据'});
      const uses=['摘要','重要性评分','观点对比','内容审核','日报','embedding'];
      const purpose=uses[id%uses.length], cost=purpose==='日报'?0.00021:0.0008+(id%7)*0.002;
      calls.push({id,time,purpose,model:purpose==='embedding'?'qwen3-embedding-8b':purpose==='摘要'||purpose==='日报'?'gemini-2.5-flash-lite':'gemini-2.5-flash',cost,input:900+id%500,output:100+id%300,article:id});
    }
  }
}
const expenses=[
  {id:1,name:'VPS 主机',category:'服务器',amount:6,currency:'USD',cycle:'月付',start:'2026-10-01',end:'2026-10-31',paid:'2026-10-01',due:'2026-11-01'},
  {id:2,name:'域名续费',category:'域名',amount:120,currency:'CNY',cycle:'年付',start:'2026-01-01',end:'2026-12-31',paid:'2026-01-01',due:'2027-01-01'},
  {id:3,name:'对象存储与备份',category:'存储',amount:1.5,currency:'USD',cycle:'月付',start:'2026-10-01',end:'2026-10-31',paid:null,due:'2026-10-18'},
  {id:4,name:'模型账户充值',category:'充值',amount:20,currency:'USD',cycle:'一次性',start:'2026-10-01',end:'2026-10-01',paid:'2026-10-01',due:null},
];
let state={page:'overview',preset:'今天',start:Date.parse('2026-10-12T00:00:00+08:00'),end:asOf,tab:'',q:'',sort:'异常优先',articleBasis:'入库时间',purpose:'全部用途',model:'全部模型',mode:'期间成本',pageNum:1,health:'全部状态',scenario:'normal'};
try{state.sort=localStorage.getItem('unspun-prototype-source-sort')||state.sort;}catch{}
let filteredArticles=[];let filteredCalls=[];let filteredSources=[];
const inside=(t)=>Date.parse(t)>=state.start&&Date.parse(t)<state.end;
const date=(t)=>new Date(t).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
const dateISO=(t)=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai'}).format(new Date(t));
const usd=(n)=>'$'+n.toFixed(n!==0 && n<0.01?5:4);
const sum=(xs,key)=>xs.reduce((n,x)=>n+x[key],0);
const sourceName=(id)=>sources.find(s=>s.id===id)?.name||id;
const pill=(s,kind='')=>`<span class="pill ${kind}">${esc(s)}</span>`;
const empty=(s='所选期间暂无记录。试试其他日期。')=>`<div class="empty">${s}</div>`;
function totals(){
  const selected=calls.filter(c=>inside(c.time));let fixed=0,estimated=0,cash=0;
  for(const e of expenses){
    const converted=e.amount/(e.currency==='CNY'?7.1:1);
    if(e.paid&&inside(e.paid+'T12:00:00+08:00'))cash+=converted;
    if(e.category==='充值')continue;
    const from=Date.parse(e.start+'T00:00:00+08:00'),to=Date.parse(e.end+'T00:00:00+08:00')+dayMs;
    const queryFrom=Date.parse(dateISO(state.start)+'T00:00:00+08:00');
    const queryTo=Date.parse(dateISO(state.end-1)+'T00:00:00+08:00')+dayMs;
    const overlap=Math.max(0,Math.min(queryTo,to)-Math.max(queryFrom,from));
    const cost=converted*overlap/(to-from);
    if(e.paid)fixed+=cost;else estimated+=cost;
  }
  return {llm:sum(selected,'cost'),fixed,estimated,cash,count:selected.length};
}
function metric(label,value,sub,route,tab=''){return `<button class="metric" data-nav="${route}" data-tab="${tab}"><span>${label} ↗</span><strong>${value}</strong><small>${sub}</small></button>`;}
function table(headers,rows){return `<div class="table-wrap"><table><thead><tr>${headers.map(h=>`<th ${h.hide?'class="mobile-hide"':''}>${h.label||h}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`;}
function panel(title,body,meta=''){return `<section class="panel"><div class="panel-head"><h2>${title}</h2><span>${meta}</span></div>${body}</section>`;}
function pagination(count){return `<div class="pagination"><span>${count} 条结果 · 每页 8 条</span><div><button data-page="prev" ${state.pageNum<=1?'disabled':''}>上一页</button><span> ${state.pageNum} / ${Math.max(1,Math.ceil(count/8))} </span><button data-page="next" ${state.pageNum*8>=count?'disabled':''}>下一页</button></div></div>`;}
function paged(xs){return xs.slice((state.pageNum-1)*8,state.pageNum*8);}
function searchbar(extra=''){return `<form class="toolbar" id="search-form"><input name="q" aria-label="搜索" placeholder="搜索标题、名称或关键词" value="${esc(state.q)}"><button>查询</button>${state.q?'<button type="button" data-clear>清除搜索</button>':''}${extra}</form>`;}
function tabs(items){return `<div class="tabs">${items.map(x=>`<button data-tab-switch="${x}" class="${state.tab===x?'active':''}">${x}</button>`).join('')}</div>`;}
function chart(type){
  const hourly=state.end-state.start<=dayMs;
  const step=hourly?2*3600000:Math.max(dayMs,Math.ceil((state.end-state.start)/dayMs/14)*dayMs);
  const buckets=[];
  for(let t=state.start;t<state.end;t+=step){
    const xs=(type==='cost'?calls:articles).filter(x=>Date.parse(x.time)>=t&&Date.parse(x.time)<Math.min(t+step,state.end));
    buckets.push({t,end:Math.min(t+step,state.end),value:type==='cost'?sum(xs,'cost'):xs.length});
  }
  const max=Math.max(0,...buckets.map(b=>b.value));
  if(!max)return empty('此期间没有'+(type==='cost'?'调用费用':'入库文章')+'记录。');
  const raw=max/4,mag=10**Math.floor(Math.log10(raw));
  const unit=[1,2,5,10].find(n=>n*mag>=raw)*mag,yMax=unit*4;
  const narrow=window.innerWidth<=680,fullWidth=narrow?360:720;
  const left=narrow?45:54,top=22,width=fullWidth-left-22,height=155,bw=width/buckets.length;
  const tick=n=>type==='cost'?'$'+n.toFixed(Math.max(2,-Math.floor(Math.log10(unit)))):String(Math.round(n));
  return `<div class="chart-frame"><span class="chart-unit">${type==='cost'?'调用费用 · USD':'入库文章 · 篇'}</span><svg class="axis-chart" viewBox="0 0 ${fullWidth} 220" role="group" aria-label="${type==='cost'?'调用费用':'入库文章'}趋势，纵轴从零开始"><g class="chart-grid">${[0,1,2,3,4].map(i=>{const y=top+height-i*height/4;return `<line x1="${left}" x2="${left+width}" y1="${y}" y2="${y}"/><text x="${left-9}" y="${y+4}" text-anchor="end">${tick(i*unit)}</text>`;}).join('')}</g>${buckets.map((b,i)=>{const x=left+i*bw+bw*.17,h=b.value/yMax*height,label=hourly?date(b.t).split(' ')[1]:dateISO(b.t).slice(5),value=type==='cost'?usd(b.value):b.value+' 篇';return `<g><rect class="plot-bar" x="${x}" y="${top+height-h}" width="${bw*.66}" height="${h}" rx="3" tabindex="0" role="button" data-bucket="${b.t}" data-bucket-end="${b.end}" data-bucket-type="${type}" data-chart-value="${date(b.t)} · ${value}" aria-label="${date(b.t)}，${value}，查看明细"><title>${date(b.t)} · ${value}</title></rect>${i%Math.ceil(buckets.length/(narrow?4:8))===0?`<text class="x-tick" x="${x+bw*.33}" y="${top+height+24}" text-anchor="middle">${label}</text>`:''}</g>`;}).join('')}</svg><div class="chart-tooltip" role="status"></div></div>`;
}
function sourceStats(s){const fs=fetches.filter(f=>f.source===s.id&&inside(f.time)),ok=fs.filter(f=>f.status==='ok').length,arts=articles.filter(a=>a.source===s.id&&inside(a.time)).length;return {...s,ok,fail:fs.length-ok,articles:arts,rate:fs.length?ok/fs.length:null};}
function overview(){
  const t=totals(),arts=articles.filter(a=>inside(a.time)),fs=fetches.filter(f=>inside(f.time));
  const rate=fs.length?(fs.filter(f=>f.status==='ok').length/fs.length*100).toFixed(1)+'%':'—';
  const pending=articles.filter(a=>a.status==='待摘要').length,failed=articles.filter(a=>a.status==='失败').length;
  const type=state.chartType||'articles';
  return `<div class="overview-kpis">${metric('新入库文章',arts.length,'查看文章 →','content','文章')}${metric('期间总成本',usd(t.llm+t.fixed),'查看费用构成 →','costs','费用构成')}${metric('抓取成功率',rate,fs.length+' 次抓取 · 查看来源 →','sources')}</div>
  <section class="panel main-trend"><div class="panel-head"><div><h2>采集与费用趋势</h2><span>${type==='cost'?'模型调用费用，不含固定成本':'按入库时间统计'}</span></div><div class="segment"><button data-chart-type="articles" class="${type==='articles'?'active':''}">文章</button><button data-chart-type="cost" class="${type==='cost'?'active':''}">调用费用</button></div></div>${chart(type)}</section>
  <div class="section-label"><span>当前状态</span><span class="muted">最近轮次 13:00 <button class="text-button" data-detail="run:${runs.at(-1).id}">查看记录 →</button></span></div>
  <div class="overview-status"><button class="status-card" data-nav="sources"><div><span class="muted">信息源</span><strong>8 <small>个启用</small></strong></div><div><span>${pill('1 个异常','warn')}</span><span class="card-link">查看全部信息源 →</span></div></button><button class="status-card" data-nav="runs" data-tab="待处理与失败"><div><span class="muted">内容处理</span><strong>${pending} <small>篇待摘要</small></strong></div><div><span>${pill(failed+' 篇失败','warn')}</span><span class="card-link">查看待处理与失败 →</span></div></button></div>
  <section class="panel attention-panel"><div class="panel-head"><h2>需要关注</h2><span>2 项</span></div><button class="attention-row" data-detail="source:nhk"><span class="attention-icon bad">!</span><span><strong>NHK World 抓取超时</strong><small>当前异常 · 查看抓取记录</small></span><span class="arrow">→</span></button><button class="attention-row" data-nav="costs" data-tab="固定账目"><span class="attention-icon">↻</span><span><strong>备份服务将在 6 天后续费</strong><small>10 月 18 日 · $1.50 · 待付款</small></span><span class="arrow">→</span></button></section>`;
}
function costsPage(){
  if(!['调用明细','固定账目','费用构成'].includes(state.tab))state.tab='费用构成';
  const t=totals();filteredCalls=calls.filter(c=>insideScoped(c.time)&&(state.purpose==='全部用途'||c.purpose===state.purpose)&&(state.model==='全部模型'||c.model===state.model)&&(c.purpose+c.model).toLowerCase().includes(state.q.toLowerCase())).reverse();
  let body='';
  if(state.tab==='调用明细')body=searchbar(`<select id="purpose" aria-label="费用用途">${['全部用途','摘要','embedding','重要性评分','观点对比','内容审核','日报'].map(x=>`<option ${x===state.purpose?'selected':''}>${x}</option>`).join('')}</select><select id="model" aria-label="模型">${['全部模型',...new Set(calls.map(c=>c.model))].map(x=>`<option ${x===state.model?'selected':''}>${x}</option>`).join('')}</select><button type="button" data-export="calls">导出 CSV</button>`)+`<div class="result-meta"><span>${filteredCalls.length} 次调用</span><span>筛选小计 <b class="num">${usd(sum(filteredCalls,'cost'))}</b></span></div>`+(filteredCalls.length?table(['时间','用途','模型',{label:'输入 / 输出',hide:true},'费用'],paged(filteredCalls).map(c=>`<tr class="row-link" tabindex="0" data-detail="call:${c.id}"><td class="num">${date(c.time)}</td><td>${c.purpose}</td><td>${c.model}<small>关联文章 #${c.article}</small></td><td class="num mobile-hide">${c.input} / ${c.output}</td><td class="num">${usd(c.cost)}</td></tr>`))+pagination(filteredCalls.length):empty());
  if(state.tab==='固定账目')body=`<div class="toolbar"><span>账目与周期规则</span><span class="spacer"></span><button data-add-expense class="primary">＋ 新增费用</button></div><div class="note">规则生成待付账目，确认付款才计实际支出。下列为当前账目清单；上方统计按所选期间分摊。</div>`+table(['名称','金额','周期与覆盖','付款','操作'],expenses.map(e=>`<tr><td>${esc(e.name)}<small>${esc(e.category)}${e.category==='充值'?' · 仅计实际支出':''}</small></td><td class="num">${e.currency} ${e.amount.toFixed(2)}</td><td>${e.cycle}<small>${e.start} → ${e.end}</small></td><td>${e.paid?pill('已确认','ok'):pill('待付款','warn')}<small>${e.paid||'未计实际支出'}</small></td><td>${e.paid?'<span class="muted">已记录</span>':`<button data-pay="${e.id}">确认付款</button>`}</td></tr>`))+`<div class="budget">站内续费提醒 · 默认提前 7 天<br>备份服务：10-18 续费 $1.50；VPS：11-01 续费 $6.00。不会自动扣款。</div>`;
  if(state.tab==='费用构成'){
    const uses=[...new Set(calls.map(c=>c.purpose))];const selected=calls.filter(c=>inside(c.time));
    body=table(['用途','调用次数','记录费用'],uses.map(p=>{const xs=selected.filter(c=>c.purpose===p);return `<tr class="row-link" tabindex="0" data-purpose="${p}"><td>${p} ↗</td><td class="num">${xs.length}</td><td class="num">${usd(sum(xs,'cost'))}</td></tr>`;}))+`<div class="result-meta"><span>固定费用分摊 ${usd(t.fixed)}</span><button class="text-button" data-tab-switch="固定账目">查看账目 →</button></div>`;
  }
  const monthSpend=sum(calls,'cost');
  const total=state.mode==='期间成本'?t.llm+t.fixed:t.cash;
  return `<div class="tabs"><button data-mode="期间成本" class="${state.mode==='期间成本'?'active':''}">期间成本</button><button data-mode="实际支出" class="${state.mode==='实际支出'?'active':''}">实际支出</button></div>
  <div class="cost-summary"><div><span>${state.mode==='期间成本'?'已确认期间总成本':'已确认实际支出'}</span><strong>${usd(total)}</strong><small>${state.mode==='期间成本'?'按调用发生与服务覆盖期统计':'按付款日期统计'}</small></div><div><span>模型调用消耗</span><strong>${usd(t.llm)}</strong><small>${t.count} 次调用</small></div><div><span>固定费用分摊</span><strong>${usd(t.fixed)}</strong><small>待确认 ${usd(t.estimated)} · 单列预计成本</small></div></div>
  <div class="budget"><span>本月模型预算 ${usd(monthSpend)} / $50.00</span><progress max="50" value="${monthSpend}"></progress><span>固定对应 10 月</span></div>
  ${panel('调用费用趋势',chart('cost'),'USD')}${panel('费用明细',tabs(['费用构成','调用明细','固定账目'])+body)}
  <details class="explanation"><summary>费用口径与汇率</summary><p>汇总币种 USD；演示汇率 CNY / USD = 7.10。实际支出与期间成本不相加。充值记支出，调用消耗记成本。</p></details>`;
}
function sourcesPage(){
  filteredSources=sources.map(sourceStats).filter(s=>(s.name+s.lang+s.region+s.kind).toLowerCase().includes(state.q.toLowerCase())&&(state.health==='全部状态'||(state.health==='异常'?s.bad:!s.bad)));
  filteredSources.sort((a,b)=>state.sort==='文章产出'?b.articles-a.articles:state.sort==='失败率'?(b.rate===null?-1:1-b.rate)-(a.rate===null?-1:1-a.rate):state.sort==='名称'?a.name.localeCompare(b.name):state.sort==='最近成功时间'?lastSuccess(b.id)-lastSuccess(a.id):Number(b.bad)-Number(a.bad)||b.articles-a.articles);
  const ss=sources.map(sourceStats);
  return `<div class="source-summary"><span>当前 <b>8</b> 个源 · 全部启用</span><span>期间成功 <b>${ss.filter(s=>s.ok>0).length}</b></span><span>有产出 <b>${ss.filter(s=>s.articles>0).length}</b></span><span>有失败 <b>${ss.filter(s=>s.fail>0).length}</b></span></div>${panel('信息源清单',searchbar(`<select id="health" aria-label="来源状态">${['全部状态','异常','正常'].map(x=>`<option ${x===state.health?'selected':''}>${x}</option>`).join('')}</select><select id="sort" aria-label="来源排序">${['异常优先','文章产出','失败率','最近成功时间','名称'].map(x=>`<option ${x===state.sort?'selected':''}>${x}</option>`).join('')}</select>`)+(filteredSources.length?table(['来源','当前状态','期间产出','成功 / 失败',{label:'成功率',hide:true},{label:'最近成功',hide:true}],filteredSources.map(s=>`<tr class="row-link" tabindex="0" data-detail="source:${s.id}"><td><b>${s.name}</b><small>${s.lang} · ${s.region} · ${s.kind}</small></td><td>${pill(s.bad?'最近超时':'正常',s.bad?'bad':'ok')}</td><td class="num">${s.articles} 篇</td><td class="num">${s.ok} / ${s.fail}</td><td class="mobile-hide num">${s.rate===null?'暂无记录':(s.rate*100).toFixed(1)+'%'}</td><td class="mobile-hide num">${date(lastSuccess(s.id))}</td></tr>`)):empty()),filteredSources.length+' 个结果')}<div class="note">当前健康与所选期间的成功率分开；抓取成功但没有新文章，不算异常。</div>`;
}
function lastSuccess(id){return Math.max(...fetches.filter(f=>f.source===id&&f.status==='ok').map(f=>Date.parse(f.time)));}
function contentPage(){
  if(!['文章','事件'].includes(state.tab))state.tab='文章';
  const basis=state.articleBasis==='报道时间'?'published':'time';
  filteredArticles=articles.filter(a=>insideScoped(a[basis])&&(!state.source||a.source===state.source)&&(a.title+sourceName(a.source)).includes(state.q)).sort((a,b)=>Date.parse(b[basis])-Date.parse(a[basis])||b.id-a.id);
  const extra=`<select id="content-sort" aria-label="文章时间口径"><option ${basis==='time'?'selected':''}>入库时间</option><option ${basis==='published'?'selected':''}>报道时间</option></select><button type="button" data-export="articles">导出 CSV</button>`;
  let body=state.source?`<button class="chip" data-clear-source>来源：${sourceName(state.source)} ×</button>`:'';
  body+=searchbar(extra);
  if(state.tab==='文章')body+=(filteredArticles.length?table(['文章','来源',{label:'报道 / 入库时间',hide:true},'状态'],paged(filteredArticles).map(a=>`<tr class="row-link" tabindex="0" data-detail="article:${a.id}"><td><b>${a.title}</b><small>#${a.id} · ${a.quality}</small></td><td>${sourceName(a.source)}</td><td class="num mobile-hide">${date(a.published)}<small>入库 ${date(a.time)}</small></td><td>${pill(a.status,a.status==='失败'?'bad':a.status==='完成'?'ok':'warn')}</td></tr>`))+pagination(filteredArticles.length):empty());
  else{
    const evs=stories.map((title,i)=>{const xs=articles.filter(a=>a.event===i);return {id:i,title,xs,earliest:Math.min(...xs.map(a=>Date.parse(a.published))),latest:Math.max(...xs.map(a=>Date.parse(a.published)))};}).filter(e=>e.earliest>=state.start&&e.earliest<state.end&&e.title.includes(state.q)&&(!state.source||e.xs.some(a=>a.source===state.source))).sort((a,b)=>b.earliest-a.earliest);
    body=`<div class="note">最新事件按最早报道时间筛选、倒序排列。今天入库的文章可以属于更早的事件；查看全部示例事件可切“本月”。</div>`+body+(evs.length?table(['事件','最早报道','文章 / 报道来源','综合分'],evs.map(e=>`<tr class="row-link" tabindex="0" data-detail="event:${e.id}"><td><b>${e.title}</b><small>最近报道 ${date(e.latest)}</small></td><td class="num">${date(e.earliest)}</td><td class="num">${e.xs.length} / ${new Set(e.xs.map(a=>a.source)).size}</td><td class="num">${70+e.id*3}</td></tr>`)):empty('此期间没有首次报道的新事件。旧事件的新文章仍可在“文章”标签查询。'));
  }
  return panel('内容查询',tabs(['文章','事件'])+body);
}
function runTable(xs){return xs.length?table(['轮次','摘要 / 聚类',{label:'耗时',hide:true},'记录'],xs.map(r=>`<tr class="row-link" tabindex="0" data-detail="run:${r.id}"><td class="num">${date(r.time)}</td><td class="num">${r.summarized} / ${r.clustered}</td><td class="mobile-hide muted">未记录</td><td>${pill('有处理记录')}</td></tr>`)):empty();}
function runsPage(){
  if(!['运行历史','待处理与失败','手动任务'].includes(state.tab))state.tab='运行历史';
  const xs=runs.filter(r=>inside(r.time)).reverse();
  let body=state.tab==='运行历史'?runTable(paged(xs))+pagination(xs.length):state.tab==='手动任务'?empty('手动任务队列在 M3-C 交付。首版查询不伪造历史任务。'):table(['对象','当前阶段','状态','最近错误'],articles.filter(a=>a.status!=='完成').slice(-8).map(a=>`<tr class="row-link" tabindex="0" data-detail="article:${a.id}"><td>#${a.id}<small>${a.title}</small></td><td>摘要</td><td>${pill(a.status,a.status==='失败'?'bad':'warn')}</td><td>${a.status==='失败'?'示例：证据不足':'等待处理'}<small>历史尝试时间未记录</small></td></tr>`));
  return panel('运行与任务',tabs(['运行历史','待处理与失败','手动任务'])+`<div class="note">${state.tab==='待处理与失败'?'当前积压，不随日期查询变化。':'历史结束时间、阶段状态与耗时没有记录时，明确显示未记录。'}</div>`+body);
}
function configPage(){
  if(!['信息源配置','管线与预算','变更与操作记录'].includes(state.tab))state.tab='管线与预算';
  let body=state.tab==='信息源配置'?table(['来源','权重','抓取超时','启用'],sources.map(s=>`<tr class="row-link" tabindex="0" data-detail="source:${s.id}"><td>${s.name}</td><td class="num">${s.kind==='社区'?'0.3':'1.0'}</td><td class="num">${s.id==='nhk'?'60':'20'}s</td><td>${pill('启用','ok')}</td></tr>`)):state.tab==='变更与操作记录'?empty('尚无生产操作审计记录。M3-A 账务操作开始记录后可查；配置与任务审计在 M3-C 接入。'):table(['配置项','当前示例值','来源'],[['抓取间隔','30 分钟','仓库配置'],['日报时间','08:00 · Asia/Shanghai','仓库配置'],['摘要批次','50','仓库配置'],['模型月预算','$50.00','示例预算'],['审核限额','$0.40 / 滚动 24 小时','仓库配置'],['模型凭证','已配置（不显示明文）','部署环境']].map(x=>`<tr><td>${x[0]}</td><td class="num">${x[1]}</td><td>${x[2]}</td></tr>`));
  return panel('配置与操作记录',tabs(['信息源配置','管线与预算','变更与操作记录'])+body)+`<div class="note warning-border">查询版仅查看配置。长期修改走配置 PR，紧急停源／暂停付费处理采用有记录的临时覆盖，均在 M3-C 交付。</div>`;
}
function render(){
  $('title').textContent=pages[state.page][0];$('subtitle').textContent=pages[state.page][2];
  $('nav').innerHTML=Object.entries(pages).map(([id,p])=>`<a href="#${id}" class="${state.page===id?'active':''}"><span class="icon">${p[1]}</span>${p[0]}</a>`).join('');
  $('range-name').textContent=state.preset;
  $('range-label').textContent=dateISO(state.start)===dateISO(state.end-1)?dateISO(state.start):`${dateISO(state.start)} — ${dateISO(state.end-1)}`;
  $('range-trigger').title=`${dateISO(state.start)} ${date(state.start).split(' ')[1]} 至 ${dateISO(state.end)} ${date(state.end).split(' ')[1]}（截止不含）`;
  const scope=state.drillStart?`<div class="drill-context"><button data-return>← 返回总览</button><span>时段：${date(state.drillStart)} — ${date(state.drillEnd)}</span><button class="chip" data-clear-drill>清除时段 ×</button></div>`:'';
  $('content').innerHTML=scope+({overview,costs:costsPage,sources:sourcesPage,content:contentPage,runs:runsPage,config:configPage}[state.page])();
  document.querySelectorAll('#content .note').forEach(note=>{const d=document.createElement('details');d.className='explanation';const summary=document.createElement('summary');summary.textContent='口径与数据说明';d.append(summary);note.replaceWith(d);d.append(note);});
  saveURL();
}
function saveURL(){
  const params=new URLSearchParams({start:String(state.start),end:String(state.end),range:state.preset});
  for(const k of ['tab','q','sort','purpose','model','mode','source','articleBasis','health','pageNum','drillStart','drillEnd','chartType'])if(state[k])params.set(k,state[k]);
  history.replaceState(null,'',`${location.pathname}?${params}#${state.page}`);
}
const viewDefaults={tab:'',q:'',purpose:'全部用途',model:'全部模型',mode:'期间成本',pageNum:1,health:'全部状态',articleBasis:'入库时间',source:null,drillStart:null,drillEnd:null};
const viewStore={};
function rememberNavigation(){saveURL();history.pushState(null,'',location.href);}
function navigate(page,tab='',fresh=false,filters={}){
  viewStore[state.page]=Object.fromEntries(Object.keys(viewDefaults).map(k=>[k,state[k]]));
  rememberNavigation();state.page=pages[page]?page:'overview';
  Object.assign(state,viewDefaults,fresh?{}:viewStore[state.page]||{},filters);
  if(tab)state.tab=tab;
  render();window.scrollTo(0,0);
}
function restoreURL(){
  const q=new URLSearchParams(location.search);Object.assign(state,viewDefaults);
  state.page=pages[location.hash.slice(1)]?location.hash.slice(1):'overview';
  for(const k of ['tab','q','sort','purpose','model','mode','source','articleBasis','health','chartType'])if(q.has(k))state[k]=q.get(k);
  for(const k of ['start','end','pageNum','drillStart','drillEnd'])if(q.has(k))state[k]=Number(q.get(k));
  state.preset=q.get('range')||'今天';render();
}
function insideScoped(t){const n=Date.parse(t);return n>=Math.max(state.start,state.drillStart||state.start)&&n<Math.min(state.end,state.drillEnd||state.end);}
function preset(p){const map={'今天':['2026-10-12',asOf],'昨天':['2026-10-11',Date.parse('2026-10-12T00:00:00+08:00')],'本周':['2026-10-12',asOf],'上周':['2026-10-05',Date.parse('2026-10-12T00:00:00+08:00')],'本月':['2026-10-01',asOf],'上月':['2026-09-01',Date.parse('2026-10-01T00:00:00+08:00')],'今年':['2026-01-01',asOf]};rememberNavigation();delete state.drillStart;delete state.drillEnd;state.preset=p;if(p==='最近 24 小时'||p==='最近 7 天'){state.end=asOf;state.start=asOf-(p==='最近 24 小时'?1:7)*dayMs;}else{state.start=Date.parse(map[p][0]+'T00:00:00+08:00');state.end=map[p][1];}state.pageNum=1;render();}
function detail(key){
  const [type,id]=key.split(':');let title='',body='';
  if(type==='source'){
    const s=sources.find(x=>x.id===id),stat=sourceStats(s);title=s.name;
    const fs=fetches.filter(f=>f.source===id&&inside(f.time)).slice(-6).reverse();
    body=`<div class="detail-grid"><div><span>当前状态</span><strong>${s.bad?'最近超时':'正常'}</strong></div><div><span>所选期间产出</span><strong>${stat.articles} 篇</strong></div><div><span>地区 / 类型</span><strong>${s.region} / ${s.kind}</strong></div><div><span>抓取参数（当前）</span><strong>${s.bad?'60':'20'} 秒超时</strong></div></div><h3>最近抓取记录 · 所选期间</h3>`+(fs.length?table(['时间','结果','错误'],fs.map(f=>`<tr><td class="num">${date(f.time)}</td><td>${pill(f.status==='ok'?'成功':'失败',f.status==='ok'?'ok':'bad')}</td><td>${f.status==='ok'?'—':f.error}</td></tr>`)):empty())+`<button class="primary" data-source-articles="${id}">查看该源文章 ↗</button><div class="note">启停与重抓在 M3-C 加入；首版提供完整查询。</div>`;
  }else if(type==='article'){
    const a=articles.find(x=>x.id===Number(id));title=a.title;body=`<div class="detail-grid"><div><span>来源</span><strong>${sourceName(a.source)}</strong></div><div><span>状态</span><strong>${a.status} · ${a.quality}</strong></div><div><span>报道时间</span><strong>${date(a.published)}</strong></div><div><span>系统入库</span><strong>${date(a.time)}</strong></div></div><h3>中文摘要 · 示例</h3><p class="note">这是一条用于检查查询与证据展示的示例文章，不代表真实新闻内容。来源发布时间与入库时间分别保留。</p><h3>已提取原文依据</h3><p class="note">“示例原文片段：新数据与相关方法已经公布，仍需进一步研究。”</p><button data-detail="event:${a.event}">查看所属事件 ↗</button><div class="note">精选准入、实质进展尚未记录，随 M3-D/E 接入。</div>`;
  }else if(type==='event'){
    const xs=articles.filter(a=>a.event===Number(id)).sort((a,b)=>Date.parse(a.published)-Date.parse(b.published));title=stories[Number(id)];body=`<div class="detail-grid"><div><span>最早报道</span><strong>${date(xs[0].published)}</strong></div><div><span>最新报道</span><strong>${date(xs.at(-1).published)}</strong></div><div><span>文章 / 报道来源</span><strong>${xs.length} / ${new Set(xs.map(a=>a.source)).size}</strong></div><div><span>综合分（示例）</span><strong>${70+Number(id)*3}</strong></div></div><h3>来源报道时间线 · 最近 5 篇</h3><div class="timeline">${xs.slice(-5).map(a=>`<p><span>${date(a.published)} · ${sourceName(a.source)}</span><button data-detail="article:${a.id}">文章 #${a.id} ↗</button></p>`).join('')}</div><div class="note">来源时间线不等于实质进展。移动文章、合并／拆分在 M3-C 提供影响预览与操作记录。</div>`;
  }else if(type==='call'){
    const c=calls.find(x=>x.id===Number(id));title='调用 #'+id;body=`<div class="detail-grid"><div><span>用途 / 模型</span><strong>${c.purpose} / ${c.model}</strong></div><div><span>记录费用</span><strong>${usd(c.cost)}</strong></div><div><span>输入 / 输出 token</span><strong>${c.input} / ${c.output}</strong></div><div><span>调用时间</span><strong>${date(c.time)}</strong></div></div><div class="note">演示调用关联文章；旧生产记录没有关联信息时会显示“未记录”。供应商费用待确认时不显示为零。</div><button data-detail="article:${c.article}">查看关联文章 #${c.article} ↗</button>`;
  }else if(type==='run'){
    const r=runs.find(x=>x.id===Number(id));title='运行 #'+id;body=`<div class="detail-grid"><div><span>记录时间</span><strong>${date(r.time)}</strong></div><div><span>完成时间 / 耗时</span><strong>未记录 / 未记录</strong></div></div>`+table(['阶段','处理数量','阶段结果'],[['摘要',r.summarized],['embedding',r.embedded],['聚类',r.clustered],['评分',r.scored]].map(x=>`<tr><td>${x[0]}</td><td class="num">${x[1]}</td><td>未记录</td></tr>`))+`<div class="note">已有处理数量不证明整轮成功。真实阶段状态与任务恢复记录在 M3-C 扩展。</div>`;
  }
  $('detail-title').textContent=title;$('detail-body').innerHTML=body;if(!$('detail').open)$('detail').showModal();
}
function expenseForm(){ $('detail-title').textContent='新增费用 · 演示';$('detail-body').innerHTML=`<form id="expense-form"><label>名称<input name="name" required maxlength="60" placeholder="例如：VPS 年付套餐"></label><div class="form-row"><label>金额<input name="amount" type="number" min="0.01" step="0.01" required value="6"></label><label>币种<select name="currency"><option>USD</option><option>CNY</option></select></label></div><div class="form-row"><label>类别<select name="category"><option>服务器</option><option>域名</option><option>存储</option><option>其他</option><option>充值</option></select></label><label>周期<select name="cycle"><option>月付</option><option>年付</option><option>一次性</option></select></label></div><div class="form-row"><label>覆盖开始<input type="date" name="start" required value="2026-10-01"></label><label>覆盖结束<input type="date" name="end" required value="2026-10-31"></label></div><label>付款状态<select name="paid"><option value="">待付款</option><option value="2026-10-12">已确认付款（演示今日）</option></select></label><p class="note">仅模拟保存，不操作真实账目。周期续费规则的下一期从本期结束之后开始；提醒提前 7 天。</p><button class="primary">保存演示账目</button></form>`;$('detail').showModal();}
function toast(s){$('toast').textContent=s;$('toast').style.display='block';setTimeout(()=>$('toast').style.display='none',2600);}
function exportCSV(type){const xs=type==='calls'?filteredCalls:filteredArticles;const fields=type==='calls'?['id','time','purpose','model','cost']:['id','title','source','published','time','status'];const cell=(s)=>'"'+String(s??'').replace(/^[=+@-]/,"'$&").replace(/"/g,'""')+'"';const blob=new Blob(['\ufeff'+[fields,...xs.map(x=>fields.map(f=>x[f]))].map(row=>row.map(cell).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='unspun-demo-'+type+'.csv';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);toast('已导出当前筛选的示例记录');}
document.addEventListener('click',(e)=>{
  const el=e.target.closest('button,a,tr[data-detail],tr[data-purpose],rect[data-bucket]');if(!el)return;
  if(el.closest('#nav')&&el.matches('a')){e.preventDefault();navigate(el.hash.slice(1));return;}
  if(el.dataset.preset)preset(el.dataset.preset);
  else if(el.dataset.nav)navigate(el.dataset.nav,el.dataset.tab||'',true);
  else if(el.dataset.tabSwitch){state.tab=el.dataset.tabSwitch;state.q='';state.pageNum=1;render();}
  else if(el.dataset.detail)detail(el.dataset.detail);
  else if(el.dataset.mode){state.mode=el.dataset.mode;render();}
  else if(el.hasAttribute('data-clear')){state.q='';state.pageNum=1;render();}
  else if(el.dataset.page){state.pageNum+=el.dataset.page==='next'?1:-1;render();}
  else if(el.dataset.purpose){state.purpose=el.dataset.purpose;state.model='全部模型';state.q='';state.tab='调用明细';state.pageNum=1;render();}
  else if(el.dataset.bucket){navigate(el.dataset.bucketType==='cost'?'costs':'content',el.dataset.bucketType==='cost'?'调用明细':'文章',true,{drillStart:Number(el.dataset.bucket),drillEnd:Number(el.dataset.bucketEnd)});}
  else if(el.dataset.chartType){state.chartType=el.dataset.chartType;render();}
  else if(el.hasAttribute('data-clear-drill')){delete state.drillStart;delete state.drillEnd;state.pageNum=1;render();}
  else if(el.hasAttribute('data-return'))history.back();
  else if(el.dataset.sourceArticles){$('detail').close();navigate('content','文章',true,{source:el.dataset.sourceArticles});}
  else if(el.hasAttribute('data-clear-source')){delete state.source;render();}
  else if(el.hasAttribute('data-add-expense'))expenseForm();
  else if(el.dataset.pay){if(confirm('确认将这笔示例账目标为已付款？不会执行真实支付。')){expenses.find(x=>x.id===Number(el.dataset.pay)).paid='2026-10-12';render();toast('演示付款已记录 · 实际支出按付款日期统计');}}
  else if(el.dataset.export)exportCSV(el.dataset.export);
});
document.addEventListener('keydown',e=>{if(['Enter',' '].includes(e.key)&&e.target.matches('tr[data-detail],tr[data-purpose],rect[data-bucket]')){e.preventDefault();e.target.dispatchEvent(new MouseEvent('click',{bubbles:true}));}});
document.addEventListener('change',e=>{const map={purpose:'purpose',model:'model',sort:'sort',health:'health','content-sort':'articleBasis'};if(map[e.target.id]){state[map[e.target.id]]=e.target.value;state.pageNum=1;if(e.target.id==='sort')try{localStorage.setItem('unspun-prototype-source-sort',state.sort);}catch{}render();}});
document.addEventListener('submit',e=>{
  if(e.target.id==='search-form'){e.preventDefault();state.q=new FormData(e.target).get('q').trim();state.pageNum=1;render();}
  if(e.target.id==='expense-form'){e.preventDefault();const f=Object.fromEntries(new FormData(e.target));if(f.end<f.start){toast('覆盖结束不能早于开始');return;}if(f.paid&&f.paid>dateISO(asOf)){toast('不能确认未来付款');return;}const end=Date.parse(f.end+'T00:00:00+08:00')+dayMs;expenses.push({...f,id:expenses.length+1,amount:Number(f.amount),paid:f.paid||null,due:f.cycle==='一次性'?null:dateISO(end)});$('detail').close();state.tab='固定账目';render();toast('已保存演示账目 · 刷新后恢复示例');}
});
$('close').onclick=()=>$('detail').close();
$('detail').addEventListener('click',e=>{if(e.target===$('detail')){const r=$('detail').getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)$('detail').close();}});
$('theme').onclick=()=>{const current=getComputedStyle(document.documentElement).colorScheme;document.documentElement.dataset.theme=current.includes('dark')?'light':'dark';};
window.addEventListener('popstate',restoreURL);
document.addEventListener('pointerover',e=>{
  const bar=e.target.closest('rect[data-chart-value]');if(!bar)return;
  const tip=bar.closest('.chart-frame').querySelector('.chart-tooltip');tip.textContent=bar.dataset.chartValue;tip.classList.add('visible');
});
document.addEventListener('focusin',e=>{if(e.target.matches('rect[data-chart-value]')){const tip=e.target.closest('.chart-frame').querySelector('.chart-tooltip');tip.textContent=e.target.dataset.chartValue;tip.classList.add('visible');}});
document.addEventListener('pointerout',e=>{if(e.target.matches('rect[data-chart-value]'))e.target.closest('.chart-frame').querySelector('.chart-tooltip').classList.remove('visible');});
document.addEventListener('focusout',e=>{if(e.target.matches('rect[data-chart-value]'))e.target.closest('.chart-frame').querySelector('.chart-tooltip').classList.remove('visible');});
restoreURL();

matchMedia('(max-width:680px)').addEventListener('change',()=>render());
