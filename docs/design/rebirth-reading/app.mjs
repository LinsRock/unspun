const main = document.querySelector('#main');
const dialog = document.querySelector('#about-dialog');
const escape = value => String(value ?? '').replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character]));
const date = value => value ? value.slice(0, 10).replaceAll('-', '.') : '日期未标明';
const roleName = { report: '报道', analysis: '分析', background: '背景', duplicate: '同一进展报道', followup: '后续进展' };
const external = value => { try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? escape(url.href) : '#'; } catch { return '#'; } };
let catalog, feedback = {}, previousFeedback = {}, currentHash = '', requestId = 0, toastTimer;
const feeds = new Map();
const scrollPositions = new Map();
const pendingFeedback = new Set();
const feedbackPath = () => `/api/feedback/${encodeURIComponent(catalog.edition || 'v2')}`;
const editionLabel = () => catalog.label || '试读 02';
const timestamp = value => new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value));

async function api(path, options) {
  const result = await fetch(path, options);
  if (!result.ok) throw new Error(result.status === 409 ? '页面已经更新，请刷新后继续反馈' : `读取失败（${result.status}）`);
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
function card(item) {
  const event = item.type === 'event';
  const originDate = event ? item.developments.map(value => value.date).filter(Boolean).sort()[0] : item.publishedAt;
  return `<article class="reading-card">
    <div class="card-side"><span class="kind ${event ? 'kind-event' : ''}">${event ? '事件' : '文章'}</span><span>${escape(item.domain)}</span><time>${date(originDate)}</time></div>
    <div class="card-main"><h2><a href="${linkFor(item)}">${escape(item.title)}</a></h2><p class="card-summary">${escape(item.summary)}</p>
      <div class="card-footer"><span>${event ? `${item.materialIds.length} 份事件材料` : escape(item.source)}</span><a href="${linkFor(item)}">${event ? '读事件全貌' : '进入深读'} <span aria-hidden="true">→</span></a></div>
    </div></article>`;
}

async function feedView(type, token) {
  if (!['all', 'event', 'article'].includes(type)) type = 'all';
  let feed = feeds.get(type);
  if (!feed) { feed = await api(`/api/feed?type=${type}`); feeds.set(type, feed); }
  if (token !== requestId) return;
  main.innerHTML = `<div class="feed-heading"><h1>精选</h1><span>${catalog.counts.event} 个事件 · ${catalog.counts.article} 篇深读</span><a class="text-link" href="#/sources">材料记录 ↗</a></div>
    <section class="feed-column" aria-label="精选内容"><nav class="type-filters" aria-label="内容类型">${[['all', '全部'], ['event', '事件'], ['article', '文章']].map(([value, label]) => `<a href="#/curated?type=${value}" ${type === value ? 'aria-current="page"' : ''}>${label}<span>${catalog.counts[value]}</span></a>`).join('')}</nav>
    <div id="feed-list">${feed.items.map(card).join('')}</div><div class="feed-end">${feed.nextCursor ? '<button id="load-more" class="load-more">继续阅读 ↓</button>' : '<span>本次精选已读到末尾</span>'}</div></section>`;
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
  main.innerHTML = `<div class="feed-heading"><h1>热点</h1><span>${catalog.batch ? '本轮事件' : '事件阅读样张'}</span></div>
    <p class="sample-note">${catalog.batch ? '本轮事件保留来源日期，真实关注数据尚未接入，暂不显示热度排名。' : '以下保留原始事件日期。真实关注数据尚未接入，次序不代表热度排名。'}</p>
    <section class="feed-column">${hot.items.map(card).join('')}</section>`;
}

function feedbackControls(id) {
  const current = feedback[id] || {};
  const prior = previousFeedback[id];
  const disabled = pendingFeedback.has(id) ? ' disabled' : '';
  const button = (value, dimension, label) => `<button data-feedback="${value}" data-id="${escape(id)}" data-dimension="${dimension}" aria-pressed="${current[dimension] === value}"${disabled}>${current[dimension] === value ? '✓ ' : ''}${label}</button>`;
  return `<section class="feedback-box" aria-label="试读反馈"><h2>这次的内容和选题怎么样？</h2>
    <div class="feedback-row"><span>选题兴趣</span>${button('worthwhile', 'interest', '值得读')}${button('not_interested', 'interest', '不感兴趣')}</div>
    <div class="feedback-row"><span>阅读问题</span>${button('too_shallow', 'quality', '内容太浅')}${button('unclear', 'quality', '没讲明白')}${current.interest || current.quality ? `<button class="undo-feedback" data-feedback="" data-id="${escape(id)}" data-dimension="all"${disabled}>撤销本次反馈</button>` : ''}</div>
    <p class="feedback-note">${prior ? `初版记录：${prior.value === 'worthwhile' ? '值得读' : '没读懂'}。原记录保留，本版单独评价。` : '兴趣和阅读问题可以分别选择；再次点击可以撤销。'}</p></section>`;
}

function materialRow(item) {
  return `<a class="material-row" href="${item.reading ? `#/article/${encodeURIComponent(item.id)}` : external(item.url)}" ${item.reading ? '' : 'target="_blank" rel="noopener noreferrer"'}><span class="material-role">${roleName[item.role] || '文章'}</span><div><h3>${escape(item.title)}</h3><p>${escape(item.source)} · ${date(item.publishedAt)}${item.materialScope === 'metadata' ? ' · 正文未取得' : item.materialScope === 'excerpt' ? ' · 部分材料' : ''}</p></div><span aria-hidden="true">→</span></a>`;
}

function sourceLinks(reading, ids) {
  return ids.map(id => {
    const index = reading.references.findIndex(reference => reference.id === id);
    if (index < 0) return '';
    const reference = reading.references[index];
    return `<a href="${external(reference.url)}" target="_blank" rel="noopener noreferrer" aria-label="来源 ${index + 1}：${escape(reference.title)}">[${index + 1}] ${escape(reference.publisher || reference.title)}</a>`;
  }).join('');
}

function readingBody(reading) {
  return `<p class="reading-lead">${escape(reading.lead)}</p>
    ${reading.takeaways?.length ? `<details class="key-points"><summary>阅读提要 · ${reading.takeaways.length} 个要点</summary><ul>${reading.takeaways.map(value => `<li>${escape(value)}</li>`).join('')}</ul></details>` : ''}
    ${reading.sections.map((section, index) => `<section class="reading-section" id="section-${index}" tabindex="-1"><h2>${escape(section.title)}</h2>${section.paragraphs.map(value => `<p>${escape(value)}</p>`).join('')}<div class="section-sources">${sourceLinks(reading, section.sourceIds)}</div></section>`).join('')}
    <section class="reference-list" id="reading-references" tabindex="-1"><h2>来源与延伸阅读</h2><ol>${reading.references.map(reference => `<li><a href="${external(reference.url)}" target="_blank" rel="noopener noreferrer">${escape(reference.title)} ↗</a><span>${escape(reference.publisher)} · ${date(reference.publishedAt)}</span>${reference.scope ? `<details class="source-scope"><summary>引用范围</summary><p>${escape(reference.scope)}</p></details>` : ''}</li>`).join('')}</ol></section>`;
}

function detailView(kind, id) {
  const event = kind === 'event';
  const item = (event ? catalog.events : catalog.materials).find(value => value.id === id);
  if (!item) return notFound();
  const reading = item.reading;
  const unavailable = !event && item.materialScope === 'metadata';
  const related = event ? catalog.materials.filter(value => item.materialIds.includes(value.id)) : catalog.events.filter(value => item.eventIds.includes(value.id));
  const back = sessionStorage.getItem('unspun-rebirth-last-list') || '#/curated';
  const knownText = reading ? reading.sections.flatMap(section => section.paragraphs).join('') : '';
  main.innerHTML = `<div class="detail-shell"><a class="back-link" href="${escape(back)}">← 返回${back.startsWith('#/hot') ? '热点' : '精选'}</a>
    <header class="detail-header"><div class="detail-kicker"><span class="kind ${event ? 'kind-event' : ''}">${event ? '事件' : '文章'}</span><span>${escape(item.domain)}</span><span>${reading ? `来源整理 · ${escape(editionLabel())}` : '材料保留'}</span></div>
    <h1>${escape(item.title)}</h1><div class="detail-meta">${event ? 'Unspun 来源整理' : `${reading ? 'Unspun 编辑整理 · ' : ''}${escape(item.source)}${!reading && item.author ? ` · ${escape(item.author)}` : ''} · 来源日期 ${date(item.publishedAt)}`}${reading ? ` · 约 ${Math.max(2, Math.ceil(knownText.length / 400))} 分钟` : ''}${!event ? ` <a href="${external(item.url)}" target="_blank" rel="noopener noreferrer">原始出处 ↗</a>` : ''}</div></header>
    <div class="detail-grid"><article class="detail-body">${reading ? readingBody(reading) : `<p class="sample-note">${unavailable ? '这份材料尚未取得正文，保留来源线索。' : catalog.batch ? '这是本轮事件的来源记录，完整整理见下方相关事件。' : '这是第一版的简短材料记录，暂未补写深读，不在本版精选中。'}</p><div class="prose">${item.paragraphs.map(value => `<p>${escape(value)}</p>`).join('')}</div>${!event ? `<a class="primary-link" href="${external(item.url)}" target="_blank" rel="noopener noreferrer">前往原文 ↗</a>` : ''}`}
      ${event ? `<details class="supporting-materials"><summary>相关原始材料（${related.length}）</summary>${related.map(materialRow).join('')}</details>` : `<details class="material-note"><summary>材料核对记录</summary><p>${escape(item.verification.note)}</p></details>`}
      <div id="feedback-region" data-item-id="${escape(item.id)}">${reading ? feedbackControls(item.id) : ''}</div>
      ${!event && related.length ? `<section class="related-links"><h2>相关事件</h2>${related.map(value => `<a href="#/event/${encodeURIComponent(value.id)}">${escape(value.title)} →</a>`).join('')}</section>` : ''}
    </article>${reading ? `<aside class="contents"><h2>本篇内容</h2>${reading.sections.map((section, index) => `<button data-scroll-to="section-${index}">${escape(section.title)}</button>`).join('')}<button data-scroll-to="reading-references">来源与延伸阅读</button><p>${reading.references.length} 个引用来源<br>保留各来源日期与观点归属</p></aside>` : ''}</div></div>`;
  bindFeedback();
  document.querySelectorAll('[data-scroll-to]').forEach(button => button.addEventListener('click', () => {
    const section = document.getElementById(button.dataset.scrollTo);
    section?.scrollIntoView({ block: 'start' });
    section?.focus({ preventScroll: true });
  }));
}

function bindFeedback() {
  document.querySelectorAll('[data-feedback]').forEach(button => button.addEventListener('click', async () => {
    const id = button.dataset.id;
    if (pendingFeedback.has(id)) return;
    const dimension = button.dataset.dimension;
    const current = feedback[id]?.[dimension];
    const value = button.dataset.feedback === current ? null : button.dataset.feedback || null;
    pendingFeedback.add(id);
    document.querySelectorAll('[data-feedback]').forEach(target => { target.disabled = true; });
    try {
      const saved = await api(feedbackPath(), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ itemId: id, dimension, value, ...(catalog.batch ? { revision: catalog.revision } : {}) }) });
      if (saved[id]) feedback[id] = saved[id];
      else delete feedback[id];
      toast(value ? '已保存本次反馈' : '已撤销本次选择');
    } catch (error) { toast(error.message); }
    finally {
      pendingFeedback.delete(id);
      const region = document.querySelector('#feedback-region');
      if (region?.dataset.itemId === id) { region.innerHTML = feedbackControls(id); bindFeedback(); }
    }
  }));
}

function sourcesView() {
  if (catalog.batch) {
    const batch = catalog.batch;
    const names = { selected: '入选文章', supporting: '事件材料', rejected: '未入选', deferred: '待处理' };
    main.innerHTML = `<div class="feed-heading"><h1>材料与选编记录</h1><span>更新于 ${escape(timestamp(batch.publishedAt))}</span></div>
      <p class="sample-note">本轮自动发现与获取材料，由会话编辑选编和整理。以下保留全部候选及原因，来源获取成功不等于入选；补充核对的出处不计入自动发现覆盖。</p>
      <details class="supporting-materials"><summary>来源获取记录 · ${batch.sources.filter(source => source.status === 'ok').length}/${batch.sources.length} 个来源取得候选</summary><div class="source-attempts">${batch.sources.map(source => `<p><strong>${escape(source.sourceName)}</strong> · ${source.status === 'ok' ? `取得 ${source.candidateCount} 条候选` : '未取得可用订阅内容'}${source.httpStatus ? ` · HTTP ${source.httpStatus}` : ''}</p>`).join('')}</div></details>
      <div class="sources-list">${batch.decisions.map(decision => {
        const candidate = batch.candidates.find(item => item.id === decision.candidateId);
        const material = catalog.materials.find(item => item.id === decision.candidateId);
        const href = material?.reading ? `#/article/${encodeURIComponent(material.id)}` : external(candidate.url);
        return `<article><span class="source-status ${decision.decision === 'selected' ? 'selected' : ''}">${names[decision.decision]}</span><div><h2><a href="${href}" ${material?.reading ? '' : 'target="_blank" rel="noopener noreferrer"'}>${escape(candidate.title)}</a></h2><p>${escape(candidate.sourceName)} · ${date(candidate.publishedAt)}${candidate.materialScope === 'excerpt' ? ' · 部分材料' : candidate.bodyStatus !== 'readable' ? ' · 正文未取得' : ''}</p><p>${escape(decision.reason)}</p></div><a class="text-link" href="${external(candidate.url)}" target="_blank" rel="noopener noreferrer">原文 ↗</a></article>`;
      }).join('')}</div>`;
    return;
  }
  main.innerHTML = `<div class="feed-heading"><h1>材料与选编记录</h1><span>初版材料保留，反馈不改写</span></div><div class="sources-list">${catalog.materials.map(item => `<article><span class="source-status ${item.selected ? 'selected' : ''}">${item.selected ? '本版精选' : '材料保留'}</span><div><h2><a href="#/article/${encodeURIComponent(item.id)}">${escape(item.title)}</a></h2><p>${escape(item.source)} · ${date(item.publishedAt)} · ${escape(item.domain)}</p><p>${item.selected ? escape(item.selectionReason) : '保留原材料与初版选编记录；本次试读暂未纳入精选。'}</p></div><a class="text-link" href="${external(item.url)}" target="_blank" rel="noopener noreferrer">原文 ↗</a></article>`).join('')}</div>`;
}

function notFound() { main.innerHTML = '<div class="empty-state"><h1>这份样张里还没有这一页。</h1><a class="primary-link" href="#/curated">回到精选</a></div>'; }

async function render() {
  const token = ++requestId;
  currentHash = location.hash || '#/curated';
  const [path, query = ''] = currentHash.slice(1).split('?');
  const [, kind, encodedId] = path.split('/');
  document.querySelectorAll('header nav a').forEach(link => link.removeAttribute('aria-current'));
  document.querySelector(kind === 'hot' ? '#nav-hot' : '#nav-curated').setAttribute('aria-current', 'page');
  try {
    if (kind === 'curated' || !kind) { sessionStorage.setItem('unspun-rebirth-last-list', currentHash); await feedView(new URLSearchParams(query).get('type') || 'all', token); }
    else if (kind === 'hot') { sessionStorage.setItem('unspun-rebirth-last-list', currentHash); await hotView(token); }
    else if (['event', 'article'].includes(kind)) detailView(kind, decodeURIComponent(encodedId || ''));
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
  catalog = await api('/api/catalog');
  [feedback, previousFeedback] = await Promise.all([api(feedbackPath()), api('/api/feedback/v1')]);
  document.querySelector('#sample-strip').innerHTML = catalog.batch
    ? `<strong>${escape(editionLabel())}</strong> 更新于 ${escape(timestamp(catalog.batch.publishedAt))} · 保留来源日期`
    : '<strong>试读 02</strong> 内容样张 · 保留来源日期 · 非实时信息流';
  document.querySelector('#about-title').textContent = catalog.batch ? '从新材料到这一轮精选' : '第二版：让详情真正有内容可读。';
  document.querySelector('#about-description').innerHTML = catalog.batch
    ? '<p>本轮从公开 RSS 发现近期材料，再获取正文、选编并整理。采集由程序完成，选编与写作由本次会话完成；尚未验证无人值守自动写作。</p><p>延续已获认可的第二版阅读方式，正文与来源日期分开，热点暂不显示无依据的排名。全部候选和来源失败可在材料记录中查看。</p><p>当前内容版本单独保存反馈，旧版评价保留。兴趣和阅读问题可以分别选择、撤销。</p>'
    : '<p>首轮反馈指出选题兴趣不符、详情信息不足。第二版收敛了选题、展开正文并压缩留白，整体阅读方向已获认可。</p><p>这组样张保留原始日期；真实热度与自动持续更新未接入。当前版本单独记录兴趣和阅读问题，旧版评价保留。</p>';
  document.querySelector('#sample-counts').textContent = `${catalog.counts.all} 项精选 · ${catalog.counts.event} 个事件 · ${catalog.counts.article} 篇深读文章`;
  await render();
} catch {
  main.innerHTML = '<div class="empty-state"><h1>试读服务暂时不可用。</h1><p>请确认本机预览服务仍在运行，再刷新页面。</p><a class="primary-link" href="/">重新打开</a></div>';
}
