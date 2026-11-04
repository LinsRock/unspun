const main = document.querySelector('#main');
const dialog = document.querySelector('#about-dialog');
const escape = value => String(value ?? '').replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]));
const date = value => value ? value.slice(0, 10).replaceAll('-', '.') : '原发日期待核';
const roleName = { report: '报道', analysis: '分析', background: '背景', duplicate: '同一进展报道', followup: '后续进展' };
const external = value => { try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? escape(url.href) : '#'; } catch { return '#'; } };
let catalog, feedback = {}, currentHash = '', requestId = 0, toastTimer;
const feeds = new Map();
const scrollPositions = new Map();

async function api(path, options) {
  const result = await fetch(path, options);
  if (!result.ok) throw new Error(`读取失败（${result.status}）`);
  return result.json();
}

function toast(message) {
  const target = document.querySelector('#toast');
  target.textContent = message;
  target.classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => target.classList.remove('visible'), 2400);
}

const linkFor = item => `#/${item.type === 'event' ? 'event' : 'article'}/${encodeURIComponent(item.id)}`;
function card(item, compact = false) {
  const event = item.type === 'event';
  const count = event ? item.materialIds.length : 0;
  const dates = event ? item.developments.map(value => value.date).filter(Boolean).sort() : [];
  return `<article class="reading-card ${event ? 'event-card' : ''} ${compact ? 'compact-card' : ''}">
    <div class="card-topline"><span class="kind ${event ? 'kind-event' : ''}">${event ? '事件' : '文章'}</span><span>${escape(item.domain)}</span>${event ? `<span class="source-count">${count} 份相关材料</span>` : ''}</div>
    <h2><a href="${linkFor(item)}">${escape(item.title)}<span class="card-arrow" aria-hidden="true">↗</span></a></h2>
    <p class="card-summary">${escape(item.summary)}</p>
    ${item.whyRead ? `<p class="card-reason"><span>${event ? '值得关注' : '为什么读'}</span>${escape(item.whyRead)}</p>` : ''}
    <div class="card-footer"><span>${event ? '多份材料，一起读' : escape(item.source)}</span><span>${event ? `${date(dates[0])} 起` : date(item.publishedAt)}</span></div>
  </article>`;
}

function sidebar() {
  const events = catalog.events.filter(item => item.selected);
  return `<aside class="sidebar">
    <div class="side-note"><p class="eyebrow">THE READING ROOM</p><h2>看见发生，<br>也留一点好奇。</h2><p>重要的事放在一起。<br>好文章，也值得单独读。</p><div class="note-line"></div><span>一份关于阅读的试作</span></div>
    <section class="side-events"><h2>从一件事开始 <span aria-hidden="true">↘</span></h2>${events.map((item, index) => `<a href="#/event/${encodeURIComponent(item.id)}"><span class="side-index">${String(index + 1).padStart(2, '0')}</span><span>${escape(item.title)}<small>${escape(item.domain)}</small></span></a>`).join('')}</section>
    <p class="side-footnote">所有条目保留原始出处与日期。<br>这是一组历史材料阅读样张。</p>
  </aside>`;
}

async function feedView(type, token) {
  if (!['all', 'event', 'article'].includes(type)) type = 'all';
  let feed = feeds.get(type);
  if (!feed) { feed = await api(`/api/feed?type=${type}`); feeds.set(type, feed); }
  if (token !== requestId) return;
  main.innerHTML = `<div class="page-heading"><div><p class="eyebrow">LESS NOISE, MORE UNDERSTANDING</p><h1>值得读的，放在一起<span>。</span></h1><p class="page-subtitle">跟上重要的事，也遇见意料之外的好内容。</p></div><div class="edition-mark"><span>UNSPUN</span><strong>01</strong><span>READING EDITION</span></div></div>
    <div class="reading-layout"><section class="feed-column" aria-label="精选内容">
      <div class="filter-row"><nav class="type-filters" aria-label="内容类型">${[['all', '全部'], ['event', '事件'], ['article', '文章']].map(([value, label]) => `<a href="#/curated?type=${value}" ${type === value ? 'aria-current="page"' : ''}>${label}<span>${catalog.counts[value]}</span></a>`).join('')}</nav><span class="filter-hint">精选样张</span></div>
      <div id="feed-list">${feed.items.map(item => card(item)).join('')}</div>
      <div class="feed-end">${feed.nextCursor ? '<button id="load-more" class="load-more">再读几篇 <span aria-hidden="true">↓</span></button>' : '<span class="end-line"></span><p>读到这里，刚刚好。</p><small>这是本次试读的全部精选。</small>'}</div>
    </section>${sidebar()}</div>`;
  document.querySelector('#load-more')?.addEventListener('click', async event => {
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = '正在展开…';
    try {
      const next = await api(`/api/feed?type=${type}&cursor=${encodeURIComponent(feed.nextCursor)}`);
      feed = { ...next, items: [...feed.items, ...next.items] };
      feeds.set(type, feed);
      const position = scrollY;
      await feedView(type, token);
      if (token === requestId) scrollTo(0, position);
    } catch (error) { button.disabled = false; button.textContent = '重试'; toast(error.message); }
  });
}

async function hotView(token) {
  const hot = await api('/api/hot');
  if (token !== requestId) return;
  main.innerHTML = `<div class="page-heading"><div><p class="eyebrow">FOLLOW THE STORY</p><h1>一件事，放回它的来龙去脉<span>。</span></h1><p class="page-subtitle">从发生了什么，到后来怎样，再读不同的解释。</p></div></div>
    <div class="hot-notice"><span class="notice-symbol" aria-hidden="true">◌</span><div><strong>热点阅读样张</strong><p>以下为历史事件示例，尚未接入真实热度；展示次序不代表热度排名。</p></div></div>
    <div class="hot-grid">${hot.items.map(item => `<div class="hot-story">${card(item, true)}<div class="hot-developments"><p class="small-label">沿着进展读</p>${item.developments.slice(0, 3).map(value => `<a href="#/event/${encodeURIComponent(item.id)}"><time>${date(value.date)}</time><span>${escape(value.title)}</span></a>`).join('')}<a class="text-link" href="#/event/${encodeURIComponent(item.id)}">进入事件 <span aria-hidden="true">→</span></a></div></div>`).join('')}</div>`;
}

function feedbackControls(id) {
  const value = feedback[id]?.value;
  return `<section class="feedback-box" aria-label="试读反馈"><div><h2>这篇整理，读起来怎么样？</h2><p>记下这次感受，帮助下一版更好读。</p></div><div class="feedback-actions"><button data-feedback="worthwhile" data-id="${escape(id)}" aria-pressed="${value === 'worthwhile'}">${value === 'worthwhile' ? '✓ ' : ''}值得读</button><button data-feedback="unclear" data-id="${escape(id)}" aria-pressed="${value === 'unclear'}">${value === 'unclear' ? '✓ ' : ''}没读懂</button>${value ? `<button class="undo-feedback" data-feedback="" data-id="${escape(id)}">撤销</button>` : ''}</div></section>`;
}

function materialRow(item) {
  return `<a class="material-row" href="#/article/${encodeURIComponent(item.id)}"><div><span class="material-role">${roleName[item.role] || '文章'}${item.materialScope === 'metadata' ? ' · 正文未取得' : item.materialScope === 'excerpt' ? ' · 部分材料' : ''}</span><h3>${escape(item.title)}</h3><p>${escape(item.source)} <span>·</span> ${date(item.publishedAt)}</p></div><span aria-hidden="true">↗</span></a>`;
}

function detailView(kind, id) {
  const event = kind === 'event';
  const item = (event ? catalog.events : catalog.materials).find(value => value.id === id);
  if (!item) return notFound();
  const unavailable = !event && item.materialScope === 'metadata';
  const related = event ? catalog.materials.filter(value => item.materialIds.includes(value.id)) : catalog.events.filter(value => item.eventIds.includes(value.id));
  const back = currentHash.includes('event') && sessionStorage.getItem('unspun-rebirth-last-list') === '#/hot' ? '#/hot' : (sessionStorage.getItem('unspun-rebirth-last-list') || '#/curated');
  main.innerHTML = `<div class="detail-shell"><a class="back-link" href="${escape(back)}">← 返回${back.startsWith('#/hot') ? '热点' : '精选'}</a>
    <header class="detail-header"><div class="card-topline"><span class="kind ${event ? 'kind-event' : ''}">${event ? '事件' : '文章'}</span><span>${escape(item.domain)}</span><span class="sample-tag">历史材料</span></div><h1>${escape(item.title)}</h1><p class="detail-deck">${escape(item.summary)}</p><div class="detail-meta">${event ? `${item.materialIds.length} 份材料 · ${item.developments.length} 条进展` : `${escape(item.source)}${item.author ? ` · ${escape(item.author)}` : ''} · ${date(item.publishedAt)}`}</div></header>
    <div class="detail-grid"><article class="detail-body"><div class="editorial-label"><span class="tiny-mark" aria-hidden="true">u.</span> ${unavailable ? '材料线索' : '导读整理'} <span>${unavailable ? '原文正文未取得' : !event && item.materialScope === 'excerpt' ? '依据部分材料整理' : '依据下方原始材料'}</span></div>
      ${unavailable ? '<div class="hot-notice"><p>目前只核对了标题或公开摘要，尚无完整导读。这份材料未独立入选，也不作为事件进展的依据。</p></div>' : ''}
      <div class="prose">${item.paragraphs.map(value => `<p>${escape(value)}</p>`).join('')}</div>
      ${item.whyRead ? `<blockquote class="why-read"><span>${event ? '值得关注' : '为什么读这篇'}</span><p>${escape(item.whyRead)}</p></blockquote>` : ''}
      ${event ? `<section class="timeline"><h2>事情是怎样发展的</h2>${item.developments.map(value => `<div class="timeline-item"><time>${date(value.date)}</time><h3>${escape(value.title)}</h3><p>${escape(value.description)}</p><div class="timeline-sources">${value.materialIds.map(materialId => { const source = catalog.materials.find(material => material.id === materialId); return source ? `<a href="#/article/${encodeURIComponent(source.id)}">${escape(source.source)} ↗</a>` : ''; }).join('')}</div></div>`).join('')}</section>` : `<section class="original-box"><div><span class="small-label">继续读原文</span><h2>${escape(item.source)}</h2><p>${unavailable ? '正文尚未取得，可尝试访问原始出处。' : '这里展示导读整理，完整论述以原文为准。'}</p></div><a class="primary-link" href="${external(item.url)}" target="_blank" rel="noopener noreferrer">打开原文 ↗</a></section><details class="material-note"><summary>关于这份材料</summary><p>${escape(item.verification.note)}</p><p>核对日期：${date(item.verification.checkedAt)}。本页文案用于试读，不是自动处理结果。</p></details>`}
      <div id="feedback-region" data-item-id="${escape(item.id)}">${unavailable ? '' : feedbackControls(item.id)}</div>
      ${event ? `<section class="related-materials"><div class="section-heading"><h2>接着读，换一个角度</h2><span>${related.length} 份材料</span></div>${related.map(materialRow).join('')}</section>` : related.length ? `<section class="related-events"><h2>放进这件事里读</h2>${related.map(value => card({ ...value, type: 'event' }, true)).join('')}</section>` : '<p class="standalone-note">好内容，也可以独立成立。<br><span>这篇文章未归入事件。</span></p>'}
    </article><aside class="detail-aside"><p class="eyebrow">READ WITH CONTEXT</p><p>${event ? '同一件事，<br>不必反复读。' : '读完一篇，<br>带走一点新理解。'}</p><div class="note-line"></div><a href="#/curated">回到精选 →</a>${event ? '<a href="#/hot">浏览事件样张 →</a>' : `<a href="${external(item.url)}" target="_blank" rel="noopener noreferrer">查看原始出处 ↗</a>`}</aside></div></div>`;
  bindFeedback();
}

function bindFeedback() {
  document.querySelectorAll('[data-feedback]').forEach(button => button.addEventListener('click', async () => {
    const id = button.dataset.id;
    const routeToken = requestId;
    const current = feedback[id]?.value;
    const value = button.dataset.feedback === current ? null : button.dataset.feedback || null;
    document.querySelectorAll('[data-feedback]').forEach(target => { target.disabled = true; });
    try {
      feedback = await api('/api/feedback', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ itemId: id, value }) });
      const region = document.querySelector('#feedback-region');
      if (routeToken === requestId && region?.dataset.itemId === id) {
        region.innerHTML = feedbackControls(id);
        bindFeedback();
      }
      toast(value ? '已记下这次试读感受' : '已撤销反馈');
    } catch (error) { toast(error.message); if (routeToken === requestId) document.querySelectorAll('[data-feedback]').forEach(target => { target.disabled = false; }); }
  }));
}

function sourcesView() {
  main.innerHTML = `<div class="page-heading"><div><p class="eyebrow">BEHIND THE SELECTION</p><h1>每一份整理，都有来处<span>。</span></h1><p class="page-subtitle">${catalog.materials.length} 份真实材料。重复报道保留在事件里，独立好文章单独入选。</p></div></div><div class="sources-list">${catalog.materials.map(item => `<article><div class="source-status ${item.selected ? 'selected' : ''}">${item.selected ? '独立精选' : item.role === 'duplicate' ? '归入事件' : '材料保留'}</div><div><h2><a href="#/article/${encodeURIComponent(item.id)}">${escape(item.title)}</a></h2><p>${escape(item.source)} · ${date(item.publishedAt)} · ${escape(item.domain)}</p><p>${escape(item.selectionReason)}</p></div><a class="text-link" href="${external(item.url)}" target="_blank" rel="noopener noreferrer">原文 ↗</a></article>`).join('')}</div>`;
}

function notFound() { main.innerHTML = '<div class="empty-state"><p class="eyebrow">NOT IN THIS EDITION</p><h1>这份样张里还没有这一页。</h1><a class="primary-link" href="#/curated">回到精选</a></div>'; }

async function render() {
  const token = ++requestId;
  currentHash = location.hash || '#/curated';
  const [path, query = ''] = currentHash.slice(1).split('?');
  const [, kind, encodedId] = path.split('/');
  document.querySelectorAll('header nav a').forEach(link => link.removeAttribute('aria-current'));
  const nav = kind === 'hot' ? '#nav-hot' : '#nav-curated';
  document.querySelector(nav).setAttribute('aria-current', 'page');
  try {
    if (kind === 'curated' || !kind) {
      sessionStorage.setItem('unspun-rebirth-last-list', currentHash);
      await feedView(new URLSearchParams(query).get('type') || 'all', token);
    } else if (kind === 'hot') {
      sessionStorage.setItem('unspun-rebirth-last-list', currentHash);
      await hotView(token);
    } else if (['event', 'article'].includes(kind)) detailView(kind, decodeURIComponent(encodedId || ''));
    else if (kind === 'sources') sourcesView();
    else notFound();
    if (token !== requestId) return;
    document.title = `${main.querySelector('h1')?.textContent || '精选'} · Unspun`;
    main.focus({ preventScroll: true });
    requestAnimationFrame(() => scrollTo(0, scrollPositions.get(currentHash) || 0));
  } catch (error) { if (token !== requestId) return; main.innerHTML = `<div class="empty-state"><h1>暂时没能展开内容。</h1><p>${escape(error.message)}</p><button id="retry">重新读取</button></div>`; document.querySelector('#retry').onclick = render; }
}

document.addEventListener('click', event => {
  const link = event.target.closest('a[href^="#/"]');
  if (link) { scrollPositions.set(currentHash, scrollY); if (dialog.open) dialog.close(); }
});
window.addEventListener('hashchange', render);
document.querySelector('.skip-link').onclick = event => { event.preventDefault(); main.focus(); main.scrollIntoView(); };
document.querySelector('#about-open').onclick = () => dialog.showModal();
document.querySelector('#about-close').onclick = () => dialog.close();
dialog.addEventListener('click', event => { if (event.target === dialog && (event.clientX < dialog.getBoundingClientRect().left || event.clientX > dialog.getBoundingClientRect().right || event.clientY < dialog.getBoundingClientRect().top || event.clientY > dialog.getBoundingClientRect().bottom)) dialog.close(); });

try {
  [catalog, feedback] = await Promise.all([api('/api/catalog'), api('/api/feedback')]);
  document.querySelector('#sample-counts').textContent = `${catalog.materials.length} 份真实材料 · ${catalog.events.length} 组事件 · ${catalog.counts.article} 篇独立精选`;
  await render();
} catch {
  main.innerHTML = '<div class="empty-state"><h1>试读服务暂时不可用。</h1><p>请确认本机预览服务仍在运行，再刷新页面。</p><a class="primary-link" href="/">重新打开</a></div>';
}
