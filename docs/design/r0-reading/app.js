import {
  EMPTY_REVIEW, MATERIAL_LABELS, entryFor, entryPublication, exportFeedback, feedEntries,
  hasReview, publicationLabel, restoreFeedback, topicMembers,
} from './model.mjs';

const app = document.querySelector('#app');
const icons = {
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>',
  feed: '<path d="M4 5h16M4 12h16M4 19h10"/>',
  review: '<path d="M9 4H5v17h14V4h-4M9 3h6v4H9zM8 12h8m-8 4h5"/>',
  arrow: '<path d="M5 12h14m-5-5 5 5-5 5"/>',
  external: '<path d="M14 3h7v7m0-7L10 14M10 3H3v18h18v-7"/>',
  back: '<path d="m10 5-7 7 7 7M3 12h18"/>',
  moon: '<path d="M21 13A9 9 0 0 1 11 3a9 9 0 1 0 10 10Z"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  book: '<path d="M12 5v16M3 3c4 0 6 0 9 2 3-2 5-2 9-2v16c-4 0-6 0-9 2-3-2-5-2-9-2Z"/>',
  play: '<path d="m9 5 11 7-11 7Z"/>',
  download: '<path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/>',
};
const icon = name => `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[name] || icons.book}</svg>`;
const escape = value => String(value ?? '').replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[character]);
const link = (url, label, className = '') => `<a class="${className}" href="${escape(url)}" target="_blank" rel="noopener noreferrer">${label}${icon('external')}</a>`;
const contentLink = (id, text, className = '') => `<a class="detail-link ${className}" href="#/content/${id}">${text}</a>`;
let dataset, manifest, materials, fingerprint, byId, feedback, storageKey;
let version = 'early';
let saveFailed = false;
let materialWarning = false;
let toastTimer;
let experienceDraft = null;
const scrollPositions = new Map();
const returnTargets = new Map();
const draftReviews = new Map();

function readStorage(key) {
  try { return localStorage.getItem(key); } catch { saveFailed = true; return null; }
}
function store(key, value) {
  try { localStorage.setItem(key, value); saveFailed = false; return true; }
  catch { saveFailed = true; return false; }
}
function saveFeedback() {
  feedback.updated_at = new Date().toISOString();
  store(storageKey, JSON.stringify(feedback));
  updateReviewCount();
}
function toast(message) {
  const element = document.querySelector('#toast');
  element.textContent = message;
  element.classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => element.classList.remove('visible'), 3200);
}
function reviewCount() { return Object.values(feedback.contents).filter(hasReview).length; }
function updateReviewCount() {
  document.querySelectorAll('[data-review-count]').forEach(element => { element.textContent = reviewCount(); });
  document.querySelectorAll('[data-storage-status]').forEach(element => { element.textContent = saveFailed ? '本地保存失败，请导出保留' : '反馈仅保存在此浏览器'; });
}
function route() { return new URL(location.hash.slice(1) || '/today', location.origin); }
function routeLink(pathname, parameters = {}) {
  const query = new URLSearchParams(Object.entries(parameters).filter(([, value]) => value && value !== '全部'));
  return `#${pathname}${query.size ? `?${query}` : ''}`;
}
function reviewValue(kind, id) { return { ...EMPTY_REVIEW, ...feedback[kind][id] }; }
function sourceText(candidate) {
  return candidate.publisher === candidate.requested_source ? candidate.publisher : `${candidate.publisher} · 经${candidate.requested_source}`;
}
function materialBadge(candidate) {
  const limited = !['open_article_text', 'daily_edited_text', 'brief_text'].includes(candidate.material_status);
  return `<span class="material-badge ${limited ? 'limited' : ''}">${MATERIAL_LABELS[candidate.material_status]}</span>`;
}
function quickFeedback(kind, id) {
  const value = reviewValue(kind, id).interest;
  return `<div class="quick-feedback" aria-label="兴趣反馈">
    <button type="button" data-interest="yes" data-kind="${kind}" data-id="${id}" aria-pressed="${value === 'yes'}">感兴趣${value === 'yes' ? ' ✓' : ''}</button>
    <button type="button" data-interest="no" data-kind="${kind}" data-id="${id}" aria-pressed="${value === 'no'}">不感兴趣${value === 'no' ? ' ✓' : ''}</button>
  </div>`;
}
function entryCard(entry, { featured = false, index = null, compact = false } = {}) {
  if (entry.kind === 'topic') {
    const publication = entryPublication(entry, byId);
    const reading = entry.members.filter(candidate => candidate.material_status !== 'question_context_only');
    return `<article class="story-card topic-card ${featured ? 'featured' : ''} ${compact ? 'compact' : ''}" data-entry="${entry.id}">
      <div class="eyebrow"><span class="topic-label">${icon('feed')}话题</span><span>${entry.topic.category}</span>${index !== null ? `<span class="story-number">0${index + 1}</span>` : ''}</div>
      <h${featured ? '2' : '3'}><a class="detail-link" href="#/topic/${entry.id}">${entry.topic.title}</a></h${featured ? '2' : '3'}>
      <p class="story-cue">${escape(reading[0].reading_cue_zh)}</p>
      ${featured ? `<div class="topic-material-preview">${reading.map(candidate => `<div><span class="reference">${candidate.id}</span><span>${escape(candidate.reading_cue_zh)}</span></div>`).join('')}</div>` : ''}
      <div class="story-meta">${reading.map(candidate => escape(candidate.publisher)).filter((value, position, values) => values.indexOf(value) === position).join(' / ')}<span>·</span>${entry.members.length} 份材料<span>·</span>最近材料 ${publication.day.slice(5)} ${publication.time ? new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Shanghai', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(publication.time) : '仅日期'}</div>
      <div class="card-footer"><a class="detail-link read-link" href="#/topic/${entry.id}">阅读话题 ${icon('arrow')}</a>${quickFeedback('topics', entry.id)}</div>
    </article>`;
  }
  const candidate = entry.candidate;
  return `<article class="story-card ${featured ? 'featured' : ''} ${compact ? 'compact' : ''}" data-entry="${candidate.id}">
    <div class="eyebrow"><span>${candidate.genre === '视频' ? icon('play') : ''}${escape(candidate.genre)}</span><span>${escape(candidate.topic)}</span>${index !== null ? `<span class="story-number">0${index + 1}</span>` : ''}</div>
    <h${featured ? '2' : '3'}>${contentLink(candidate.id, escape(candidate.title))}</h${featured ? '2' : '3'}>
    <p class="story-cue">${escape(candidate.reading_cue_zh)}</p>
    <div class="story-meta">${escape(sourceText(candidate))}<span>·</span>${escape(publicationLabel(candidate))}${candidate.video_duration ? `<span>·</span>${candidate.video_duration}` : ''}</div>
    <div class="material-row">${materialBadge(candidate)}${manifest.reasons[candidate.id] ? `<span>${escape(manifest.reasons[candidate.id])}</span>` : ''}</div>
    <div class="card-footer">${contentLink(candidate.id, `打开阅读 ${icon('arrow')}`, 'read-link')}${quickFeedback('contents', candidate.id)}</div>
  </article>`;
}

function shell(content, active) {
  const count = reviewCount();
  app.innerHTML = `<div class="workspace">
    <aside class="sidebar">
      <a href="#/today" class="brand" aria-label="Unspun 首页"><span class="brand-mark">u<span>•</span></span><span>unspun<small>留意世界，也留意兴趣</small></span></a>
      <div class="sidebar-caption">你的阅读空间</div>
      <nav aria-label="主导航">
        <a class="${active === 'today' ? 'active' : ''}" href="#/today" ${active === 'today' ? 'aria-current="page"' : ''}>${icon('sun')}当天精选<span class="nav-dot"></span></a>
        <a class="${active === 'feed' ? 'active' : ''}" href="#/feed" ${active === 'feed' ? 'aria-current="page"' : ''}>${icon('feed')}信息流</a>
        <a class="${active === 'review' ? 'active' : ''}" href="#/review" ${active === 'review' ? 'aria-current="page"' : ''}>${icon('review')}选材评审<span class="nav-count" data-review-count>${count}</span></a>
      </nav>
      <div class="sidebar-context"><span class="tiny-label">这一轮，先读真实材料</span><p>新闻、好文章与视频，<br>都可以有自己的位置。</p><a href="#/review">43 个候选，等你判断 ${icon('arrow')}</a></div>
      <div class="sidebar-footer"><span class="prototype-label">R0 · 阅读原型</span><p data-storage-status>${saveFailed ? '本地保存失败，请导出保留' : '反馈仅保存在此浏览器'}</p><button class="theme-button" data-action="theme" aria-label="切换深浅主题">${icon('moon')}<span>切换外观</span></button></div>
    </aside>
    <div class="main-shell"><header class="topbar"><span>阅读 / ${active === 'today' ? '当天精选' : active === 'feed' ? '持续发现' : active === 'review' ? '选材评审' : '详情'}</span><div><span class="snapshot-dot"></span>2026.10.15 真实样本<span class="topbar-divider"></span><button data-action="export">${icon('download')}导出反馈</button></div></header>
      <main id="main" tabindex="-1">${content}</main>
      <footer class="page-footer"><span>Unspun · 为值得看的内容留出注意力</span><span>真实候选试排 · 选材与参数待评审</span></footer>
    </div>
  </div>`;
  document.documentElement.dataset.density = feedback.experience.density || 'comfortable';
}

function todayPage() {
  const maximum = Number(feedback.experience.selection_limit || 6);
  const entries = manifest.selection.slice(0, maximum).map(id => entryFor(id, byId, manifest, version));
  const featured = entries[0];
  shell(`<div class="page-heading"><div><div class="kicker">THURSDAY, OCTOBER 15</div><h1>今天，值得留意的</h1><p>跟上重要动态，也发现一篇想读的好内容。</p></div><div class="date-stamp"><span>10 / 2026</span><strong>15</strong><small>星期四</small></div></div>
    <div class="sample-notice"><span class="notice-mark">R0</span><p>以下是 <strong>10 月 15 日验证样本的人工试排</strong>。材料提示沿用来源报告，尚未作为审核通过的 AI 导读；旧文保留原日期。</p></div>
    <button class="mobile-update" data-action="version"><span>${version === 'early' ? '模拟精选更新 · 加入 C05' : '已加入 C05 · 返回前一模拟版'}</span>${icon('arrow')}</button>
    <div class="home-columns"><div>
      <section aria-labelledby="selection-title"><div class="section-heading"><div><span class="section-index">01</span><h2 id="selection-title">当天精选</h2><span class="subtle">${entries.length} 条 · ${manifest.selection_versions[version].label}</span></div><a href="#/feed">继续发现 ${icon('arrow')}</a></div>
      <div class="today-lead">${entryCard(featured, { featured: true, index: 0 })}</div>
      <div class="selection-grid">${entries.slice(1).map((entry, position) => entryCard(entry, { index: position + 1 })).join('')}</div></section>
      <section class="continue-section"><div class="section-heading"><div><span class="section-index">02</span><h2>再往下读</h2></div><a href="#/feed">打开信息流 ${icon('arrow')}</a></div>${entryCard(entryFor('C16', byId, manifest, version), { compact: true })}${entryCard(entryFor('C29', byId, manifest, version), { compact: true })}</section>
    </div><aside class="reading-rail">
      <section class="rail-card update-card"><span class="tiny-label">随重要新增，适度更新</span><h3>${version === 'early' ? '有一份新材料可加入' : '已载入后一版样本'}</h3><p>18:33 模拟版在市场话题中加入 <strong>C05 · IMF 亚太经济展望</strong>，其原始发布为 18:32。其他精选保留。</p><button class="primary-button" data-action="version">${version === 'early' ? '查看 18:33 模拟版' : '返回 18:32 模拟版'} ${icon('arrow')}</button><small>使用已有候选模拟更新，非历史版本。<br>“重要新增”的判断仍待你评价。</small>${version === 'updated' ? `<a class="text-link" href="#/review#experience">评价这次更新 ${icon('arrow')}</a>` : ''}</section>
      <section class="rail-card"><span class="tiny-label">阅读节奏 · 供体验</span><label class="control-label" for="selection-limit">精选条数上限</label><select id="selection-limit" data-experience="selection_limit">${[4, 6, 8].map(number => `<option value="${number}" ${maximum === number ? 'selected' : ''}>最多 ${number} 条</option>`).join('')}</select><p class="help-text">这一版只选了 6 条；上限是 8 条时也不凑数。</p><label class="control-label" for="density">阅读密度</label>${densityControl()}</section>
      <section class="rail-card review-invitation"><div class="rail-icon">${icon('review')}</div><h3>这些，值得选进来吗？</h3><p>重要性、个人兴趣和现在是否值得看，分别留下判断。</p><a class="text-link" href="#/review">开始选材评审 ${icon('arrow')}</a><div class="review-progress"><strong data-review-count>${reviewCount()}</strong><span>/ 43 个已反馈</span></div></section>
      <div class="rail-footnote">本轮仍缺雪球、微博帖子，<br>以及视频字幕与社区回答正文。<br><a href="#/review?filter=gaps">查看覆盖缺口 ${icon('arrow')}</a></div>
    </aside></div>`, 'today');
}

function densityControl() {
  const density = feedback.experience.density || 'comfortable';
  return `<div class="segmented density-control" role="group" aria-label="阅读密度"><button data-density="comfortable" aria-pressed="${density === 'comfortable'}">舒展</button><button data-density="compact" aria-pressed="${density === 'compact'}">紧凑</button></div>`;
}

function feedPage(currentRoute) {
  const sort = currentRoute.searchParams.get('sort') === 'latest' ? 'latest' : 'recommended';
  const requested = currentRoute.searchParams.get('category') || '全部';
  const category = requested in manifest.categories ? requested : '全部';
  const entries = feedEntries(byId, manifest, { sort, category, version });
  let previousGroup = '';
  const cards = entries.map(entry => {
    const publication = entryPublication(entry, byId);
    const group = `${publication.day}${publication.time === null ? '-unknown' : ''}`;
    let heading = '';
    if (sort === 'latest' && previousGroup !== group) heading = `<div class="feed-date">${publication.day || '日期未知'}${publication.time === null ? ' · 仅精确到日，不参与时分排序' : ' · 北京时间'}</div>`;
    previousGroup = group;
    return heading + entryCard(entry, { compact: true });
  }).join('');
  shell(`<div class="page-heading simple"><div><div class="kicker">A LITTLE MORE TO DISCOVER</div><h1>持续发现</h1><p>话题和独立内容，都可以从这里开始读。</p></div>${densityControl()}</div>
    <div class="feed-toolbar"><div class="segmented" aria-label="信息流排序"><a href="${routeLink('/feed', { sort: 'recommended', category })}" class="${sort === 'recommended' ? 'selected' : ''}" ${sort === 'recommended' ? 'aria-current="page"' : ''}>推荐</a><a href="${routeLink('/feed', { sort: 'latest', category })}" class="${sort === 'latest' ? 'selected' : ''}" ${sort === 'latest' ? 'aria-current="page"' : ''}>最新</a></div><span>${entries.length} 条试排内容</span></div>
    <nav class="filter-chips" aria-label="领域筛选">${['全部', ...Object.keys(manifest.categories)].map(item => `<a href="${routeLink('/feed', { sort, category: item })}" class="${category === item ? 'selected' : ''}" ${category === item ? 'aria-current="true"' : ''}>${item}</a>`).join('')}</nav>
    <div class="feed-explanation">${sort === 'recommended' ? '推荐为人工试排，供评选材与阅读密度；没有自动推荐分数。' : '按原始材料发布时间排序；日期精度不足的单列。新抓取、转载和新写提示不刷新首发时间。'}<span>样本范围：2026-10-15 · 非实时流</span></div>
    <div class="feed-layout"><section class="feed-list" aria-label="信息流内容">${cards || '<div class="empty-state">当前领域没有试排内容，可切换“全部”或查看所有候选。</div>'}</section><aside class="reading-rail"><section class="rail-card"><span class="tiny-label">从这里接着读</span><h3>不要把新发现<br>误当成新发布</h3><p>几天前的长文仍可推荐。日报选编、问题创建、转载与原作时间，各自保留。</p><a href="#/review?filter=boundaries" class="text-link">查看边界样本 ${icon('arrow')}</a></section><section class="rail-card"><h3>未入选，也需要评价</h3><p>这里只展示 18 个阅读入口。全部 43 个候选，包括旧闻、受限材料和转载，都在评审区。</p><a href="#/review" class="text-link">查看所有候选 ${icon('arrow')}</a></section></aside></div>`, 'feed');
}

function feedbackForm(kind, id) {
  const value = draftReviews.get(`${kind}:${id}`) || reviewValue(kind, id);
  const group = (name, title, options) => `<fieldset><legend>${title}</legend><div class="choice-row">${options.map(([key, label]) => `<label class="choice"><input type="radio" name="${name}" value="${key}" ${String(value[name]) === String(key) ? 'checked' : ''}/><span>${label}</span></label>`).join('')}</div></fieldset>`;
  return `<section class="feedback-panel" aria-labelledby="feedback-title"><div class="section-heading"><div><span class="section-index">你的判断</span><h2 id="feedback-title">${kind === 'topics' ? '这个话题该怎样选？' : '这篇内容，值得看吗？'}</h2><span class="save-state" data-save-state>${hasReview(feedback[kind][id]) ? '已留下反馈，可修改' : '还没有评价'}</span></div></div><form id="review-form" data-kind="${kind}" data-id="${id}">
    ${group('worth_reading_now', '现在是否值得看', [['yes', '值得看'], ['no', '不值得看'], ['unknown', '还无法判断']])}
    <div class="rating-columns">${group('interest_1_to_5', '个人兴趣 · 1 低 → 5 高', [1, 2, 3, 4, 5].map(number => [number, number]))}${group('importance_1_to_5', '重要性 · 1 低 → 5 高', [1, 2, 3, 4, 5].map(number => [number, number]))}</div>
    ${group('place', '你会把它放在哪里', [['selection', '当天精选'], ['recommended', '推荐流'], ['latest', '仅最新'], ['exclude', '不入选'], ['defer', '材料不足待补']])}
    <label class="control-label" for="review-reason">理由或建议 <span class="optional">选填</span></label><textarea id="review-reason" name="reason" rows="3" maxlength="4000" placeholder="例如：题材想看，但只有预览；这两篇放在一个话题里合适吗？">${escape(value.reason || '')}</textarea>
    <div class="form-footer"><button class="primary-button" type="submit">保存评价 ${icon('check')}</button><button type="button" class="quiet-button" data-action="clear-review" data-kind="${kind}" data-id="${id}">撤销本条反馈</button><span>未填写的项目保留未知</span></div>
  </form></section>`;
}

function provenance(candidate, material) {
  return `<details class="provenance"><summary>材料出处与核对记录 <span>${candidate.id}</span></summary><dl>
    <div><dt>发现渠道</dt><dd>${escape(candidate.requested_source)}</dd></div><div><dt>原始发布方</dt><dd>${escape(candidate.publisher)}</dd></div><div><dt>作者</dt><dd>${escape(candidate.author || '未取得个人署名')}</dd></div>
    <div><dt>原页时间</dt><dd>${escape(publicationLabel(candidate, true))}<small>${escape(candidate.publication.basis)}</small></dd></div>
    ${candidate.publication.modified_at ? `<div><dt>原页修改</dt><dd>${escape(candidate.publication.modified_at)}<small>修改时间不替代首发时间。</small></dd></div>` : ''}
    <div><dt>材料范围</dt><dd>${escape(candidate.material_status_label)}${candidate.material_chars ? ` · ${candidate.material_chars.toLocaleString()} 个文本字符` : ''}<small>仅指核对的公开文本单元，不包含未取得的图片排版、付费版本或音视频。</small></dd></div>
    <div><dt>观测时间</dt><dd>${escape(candidate.observed_at)}<small>观测时间用于追溯，不用作新闻发布时间。</small></dd></div>
    <div><dt>正文指纹</dt><dd class="fingerprint">${escape(candidate.material_sha256 || '本轮未保存正文指纹')}${material ? '<small>本地材料与候选指纹一致</small>' : ''}</dd></div>
    <div><dt>观测引用</dt><dd>${candidate.observations.map(item => `<code>${escape(item)}</code>`).join(' ')}</dd></div>
    ${material?.extraction_observation_id ? `<div><dt>文本提取自</dt><dd><code>${escape(material.extraction_observation_id)}</code><small>按原记录选择公开文章、RSS 文本或列表简介，提取后核对候选正文指纹。</small></dd></div>` : ''}
    <div><dt>原内容</dt><dd>${link(candidate.url, '打开原发布页')}</dd></div>
    </dl><p>${link('/evidence/observations.json', '结构化来源证据')} ${link('/evidence/source-validation.md', '来源验证报告')}</p></details>`;
}

function backButton() {
  return `<button class="back-link" data-action="back">${icon('back')}${returnTargets.get(location.hash)?.hash?.includes('/topic/') ? '返回话题' : returnTargets.get(location.hash)?.hash?.includes('/review') ? '返回选材评审' : returnTargets.get(location.hash)?.hash?.includes('/today') ? '返回当天精选' : '返回信息流'}</button>`;
}

function rememberReturnTarget(destination) {
  const current = location.hash || '#/today';
  const visited = new Set();
  let ancestor = current;
  while (ancestor && !visited.has(ancestor)) {
    // Revisiting a parent must preserve its original route back to the list.
    if (ancestor === destination) return;
    visited.add(ancestor);
    ancestor = returnTargets.get(ancestor)?.hash;
  }
  returnTargets.set(destination, { hash: current, scroll: window.scrollY });
}

function bodyContent(candidate, material) {
  const status = candidate.material_status;
  const title = {
    open_article_text: '公开文章正文', daily_edited_text: '日报编辑版正文', brief_text: '短讯正文',
    partial_preview: '公开预览 · 到此为止', question_context_only: '问题描述 · 不含回答',
    video_description_only: '发布页视频简介', podcast_description_only: '播客简介与发布方章节点',
    feed_summary_only: '原文入口',
  }[status];
  return `<section class="body-section"><div class="section-heading"><div><span class="section-index">原材料</span><h2>${title}</h2></div><span>${material ? '已核对的文本快照' : '本地没有可读正文'}</span></div>
    ${status === 'video_description_only' ? `<div class="media-placeholder">${icon('play')}<div><strong>前往原平台观看${candidate.video_duration ? ` · ${candidate.video_duration}` : ''}</strong><span>本轮只有简介，没有字幕或全片导读。</span></div>${link(candidate.url, '打开视频', 'text-link')}</div>` : ''}
    ${status === 'podcast_description_only' ? '<div class="scope-note">以下章节点由发布方提供；本轮没有音频逐字稿。</div>' : ''}
    ${status === 'daily_edited_text' ? '<div class="scope-note">可读的是日报选编版本。原回答的全文与首发时间尚未核验。</div>' : ''}
    ${material ? `<div class="article-body">${material.paragraphs.map(paragraph => `<p>${escape(paragraph)}</p>`).join('')}</div>` : `<div class="empty-material"><h3>${status === 'feed_summary_only' ? '仅有 RSS 阅读入口' : '这份文本快照当前未载入'}</h3><p>${status === 'feed_summary_only' ? '候选文件保存了阅读提示，没有保存可展示的原始导语或正文。请到原平台阅读。' : '来源核对记录仍保留，可打开原文；不会根据标题补写缺失正文。'}</p>${link(candidate.url, '去原平台阅读', 'primary-link')}</div>`}
    ${status === 'partial_preview' ? '<div class="preview-end"><span></span>公开预览结束 · 完整内容请到原平台阅读<span></span></div>' : ''}
    ${status === 'question_context_only' ? '<div class="preview-end">未取得回答正文与互动量；不据此概括“大家的观点”。</div>' : ''}
    <div class="original-footer"><span>${escape(candidate.publisher)} · ${escape(candidate.author || '个人署名未取得')}</span>${link(candidate.url, '阅读原内容', 'text-link')}</div>
  </section>`;
}

function contentPage(id) {
  const candidate = byId[id];
  if (!candidate) return notFound();
  const material = materials[id];
  const related = id === 'C20' ? ['C42'] : id === 'C42' ? ['C20'] : id === 'C21' ? ['C41', 'C12'] : id === 'C41' ? ['C21', 'C12'] : [];
  const topics = manifest.topics.filter(topic => [...topic.members, ...topic.related].includes(id));
  shell(`<div class="detail-top">${backButton()}<span class="reference">${id} · 独立内容</span></div>
    <div class="detail-layout"><article class="reader"><header class="article-heading"><div class="eyebrow"><span>${escape(candidate.genre)}</span><span>${escape(candidate.topic)}</span></div><h1>${escape(candidate.title)}</h1><div class="byline"><strong>${escape(candidate.author || '个人署名未取得')}</strong><span>${escape(sourceText(candidate))}</span></div><div class="article-time">${escape(publicationLabel(candidate, true))}<span>北京时间</span>${candidate.video_duration ? `<span>视频 ${candidate.video_duration}</span>` : ''}</div><div class="article-actions">${materialBadge(candidate)}${link(candidate.url, '打开原文', 'text-link')}${quickFeedback('contents', id)}</div></header>
      <section class="reading-cue"><span class="tiny-label">材料阅读提示</span><p>${escape(candidate.reading_cue_zh)}</p><small>沿用来源验证报告的阅读线索，未经独立事实审核；全文级 AI 导读待核验。</small></section>
      <div class="scope-note"><strong>阅读范围</strong><p>${escape(candidate.limitations_zh)}</p></div>
      ${bodyContent(candidate, material)}${provenance(candidate, material)}
      ${related.length ? `<section class="related-materials"><h2>转载与相关材料</h2><p class="help-text">${['C20', 'C42'].includes(id) ? '总述重叠，但完整页面包含的材料不同，保留独有阅读内容。' : 'C21 / C41 为同篇转载；C12 是另一篇评论，不一起误去重。'}</p>${related.map(key => `<div>${contentLink(key, `${key} · ${escape(byId[key].title)}`)}<small>${escape(sourceText(byId[key]))} · ${escape(publicationLabel(byId[key]))}</small></div>`).join('')}</section>` : ''}
      ${candidate.original_answer_urls.length ? `<div class="original-answer">${candidate.original_answer_urls.map(url => link(url, '原回答入口')).join('')}<span>原回答首发与全文未验证</span></div>` : ''}
      ${feedbackForm('contents', id)}
    </article><aside class="reading-rail detail-rail"><section class="rail-card"><span class="tiny-label">阅读这一篇</span><h3>${MATERIAL_LABELS[candidate.material_status]}</h3><p>${material ? '已载入上轮核对过的公开文本，完整度以这份材料的可读范围为准。' : '保留已知范围与出处，可从原平台继续阅读。'}</p><a href="#feedback-title" data-action="jump-feedback" class="text-link">留下选材判断 ${icon('arrow')}</a></section>${topics.map(topic => `<section class="rail-card"><span class="tiny-label">放在一起读</span><h3><a class="detail-link" href="#/topic/${topic.id}">${topic.title}</a></h3><a class="detail-link text-link" href="#/topic/${topic.id}">打开话题 ${icon('arrow')}</a></section>`).join('')}<div class="rail-footnote">喜欢一篇文章，<br>不等于认可其中的每个观点。</div></aside></div>`, 'detail');
}

function topicPage(id) {
  const topic = manifest.topics.find(item => item.id === id);
  if (!topic) return notFound();
  const members = topicMembers(topic, manifest, version).map(key => byId[key]);
  shell(`<div class="detail-top">${backButton()}<span class="reference">话题详情 · 人工关联试排</span></div><div class="detail-layout"><article class="reader topic-reader"><header class="article-heading"><div class="eyebrow"><span class="topic-label">${icon('feed')}话题</span><span>${topic.category}</span></div><h1>${topic.title}</h1><p class="topic-description">${topic.description}</p><div class="article-actions"><span>${members.length} 份材料${topic.related.length ? ` · 另有 ${topic.related.length} 个转载入口` : ''}</span>${quickFeedback('topics', id)}</div></header>
      <section class="topic-guide"><span class="tiny-label">先看材料，再作判断</span><h2>这组材料分别提供什么？</h2><p class="help-text">以下逐条沿用已核对的材料提示，没有补写话题级事实结论或整场讨论总结。</p>${members.map(candidate => `<div class="guide-item"><a class="reference detail-link" href="#/content/${candidate.id}">${candidate.id}</a><div><p>${escape(candidate.reading_cue_zh)}</p><span>${escape(sourceText(candidate))} · ${MATERIAL_LABELS[candidate.material_status]}</span></div></div>`).join('')}<div class="guide-status">AI 话题导读 · 待核验，未生成</div></section>
      <section class="topic-source-list"><div class="section-heading"><div><span class="section-index">逐篇阅读</span><h2>相关材料</h2></div></div>${members.map(candidate => `${entryCard(entryFor(candidate.id, byId, manifest, version), { compact: true })}<p class="member-limitation">${escape(candidate.limitations_zh)}</p>`).join('')}${topic.related.length ? `<div class="reprint-note"><strong>同篇转载 · 保留传播关系</strong>${topic.related.map(key => `<p>${contentLink(key, `${key} · ${escape(byId[key].requested_source)}转载`)}<span>原作材料 C21 发布于 10-14 12:35，转载不算新进展。</span></p>`).join('')}</div>` : ''}</section>
      ${feedbackForm('topics', id)}
    </article><aside class="reading-rail detail-rail"><section class="rail-card"><span class="tiny-label">话题组织评审</span><h3>放在一起，<br>是否更好读？</h3><p>可以评价应否组成话题、是否重复占位，以及有没有遗漏值得独立阅读的材料。</p><button class="text-link" data-action="jump-feedback">评价话题 ${icon('arrow')}</button></section><section class="rail-card"><h3>材料数量 ≠ 独立验证</h3><p>报道、转述、评论和问题描述保留各自身份。问题入口没有回答正文。</p></section></aside></div>`, 'detail');
}

function reviewPage(currentRoute) {
  const filter = currentRoute.searchParams.get('filter') || 'all';
  const query = currentRoute.searchParams.get('q') || '';
  const boundaryIds = ['C11', 'C19', 'C20', 'C21', 'C24', 'C25', 'C26', 'C27', 'C28', 'C30', 'C35', 'C38', 'C39', 'C40', 'C41', 'C42'];
  const candidates = dataset.candidates.filter(candidate => {
    if (filter === 'priority' && !manifest.priority_review.includes(candidate.id)) return false;
    if (filter === 'pending' && hasReview(feedback.contents[candidate.id])) return false;
    if (filter === 'reviewed' && !hasReview(feedback.contents[candidate.id])) return false;
    if (filter === 'boundaries' && !boundaryIds.includes(candidate.id)) return false;
    return `${candidate.id} ${candidate.title} ${candidate.publisher} ${candidate.requested_source} ${candidate.author || ''}`.toLowerCase().includes(query.toLowerCase());
  });
  const places = { selection: '当天精选', recommended: '推荐流', latest: '仅最新', exclude: '不入选', defer: '待补材料' };
  const worth = { yes: '值得看', no: '不值得看', unknown: '无法判断' };
  shell(`<div class="page-heading simple"><div><div class="kicker">YOUR TASTE, IN YOUR WORDS</div><h1>选材，由真实阅读来判断</h1><p>43 个真实候选 · 17 项来源。选进来的和暂未入选的，都可以评价。</p></div><button class="primary-button" data-action="export">${icon('download')}导出评审记录</button></div>
    <div class="review-overview"><div><strong data-review-count>${reviewCount()}</strong><span>/ 43 个候选已反馈</span></div><p>重要性、兴趣和现在是否值得看分别记录。<br>没读、打不开或材料不足，可以保留未知。</p><span data-storage-status>${saveFailed ? '本地保存失败，请导出保留' : '反馈仅保存在此浏览器'}</span></div>
    <div class="review-tabs" aria-label="候选范围">${[['all', '全部候选'], ['priority', '建议先评 · 16'], ['pending', '待反馈'], ['reviewed', '已反馈'], ['boundaries', '边界样本'], ['gaps', '覆盖缺口']].map(([key, label]) => `<a class="${filter === key ? 'selected' : ''}" href="${routeLink('/review', { filter: key, q: query })}">${label}</a>`).join('')}</div>
    ${filter === 'gaps' ? `<section class="gaps-list">${manifest.gaps.map(gap => `<article><span class="gap-dot"></span><div><h2>${gap.source}</h2><p>${gap.reason}</p></div><span>待补齐</span></article>`).join('')}<p class="help-text">来源数量不代表覆盖充分。医学研究、重大科学进展等仍需参考清单；本轮未恢复 worker 或接入新来源。</p>${link('/evidence/source-validation.md', '查看完整来源验证报告', 'text-link')}</section>` : `<form id="search-form" class="search-row"><label for="candidate-search">查找候选</label><input id="candidate-search" name="q" type="search" value="${escape(query)}" placeholder="标题、作者、来源或 C14"/><button type="submit" class="quiet-button">查找</button><span>${candidates.length} 个结果</span></form>
    <div class="candidate-list">${candidates.map(candidate => {
      const value = feedback.contents[candidate.id];
      const completed = hasReview(value);
      return `<article class="candidate-row" data-candidate="${candidate.id}"><span class="candidate-id">${candidate.id}</span><div class="candidate-main"><h2>${contentLink(candidate.id, escape(candidate.title))}</h2><div class="story-meta">${escape(sourceText(candidate))}<span>·</span>${escape(publicationLabel(candidate))}</div><p>${escape(candidate.reading_cue_zh)}</p><div class="material-row">${materialBadge(candidate)}${['C11', 'C19'].includes(candidate.id) ? '<span class="boundary-label">旧闻反例 · 未放入当前阅读流</span>' : ''}${candidate.reprint_group ? '<span class="boundary-label">同篇转载组 · 不刷新首发</span>' : ''}</div>${completed ? `<div class="saved-review">${value.worth_reading_now ? worth[value.worth_reading_now] : ''}${value.interest_1_to_5 ? ` · 兴趣 ${value.interest_1_to_5}/5` : ''}${value.importance_1_to_5 ? ` · 重要性 ${value.importance_1_to_5}/5` : ''}${value.place ? ` · ${places[value.place]}` : ''}${value.interest ? ` · ${value.interest === 'yes' ? '感兴趣' : '不感兴趣'}` : ''}${value.reason ? `<p>${escape(value.reason)}</p>` : ''}</div>` : ''}</div><div class="candidate-actions">${contentLink(candidate.id, completed ? '查看 / 修改' : '阅读并评价', 'review-link')}${quickFeedback('contents', candidate.id)}</div></article>`;
    }).join('') || '<div class="empty-state">没有符合条件的候选。可以切换“全部候选”继续阅读。</div>'}</div>`}
    ${experienceForm()}`, 'review');
}

function experienceForm() {
  const value = { ...feedback.experience, ...experienceDraft };
  return `<section class="experience-panel" id="experience"><div class="section-heading"><div><span class="section-index">页面与选编</span><h2>这套阅读方式，合适吗？</h2></div></div><form id="experience-form"><div class="experience-grid"><label class="control-label">重要新增出现后，你希望何时更新精选？<select name="refresh_preference"><option value="">尚未选择</option>${[['immediate', '有重要新增就更新'], ['30_minutes', '至少间隔 30 分钟'], ['60_minutes', '至少间隔 60 分钟'], ['unknown', '还需要继续体验']].map(([key, label]) => `<option value="${key}" ${value.refresh_preference === key ? 'selected' : ''}>${label}</option>`).join('')}</select></label><label class="control-label">18:33 模拟版的这次更新<select name="update_assessment"><option value="">尚未评价</option>${[['worth_updating', '值得更新'], ['wait', '可以等一等'], ['not_needed', '不必为此更新'], ['unknown', '还无法判断']].map(([key, label]) => `<option value="${key}" ${value.update_assessment === key ? 'selected' : ''}>${label}</option>`).join('')}</select></label></div><label class="control-label" for="missing-content">这批候选还遗漏了什么？</label><textarea id="missing-content" name="missing" rows="2" maxlength="4000" placeholder="具体内容、作者、事件或领域；只记录反馈，不假装已经接入。">${escape(value.missing || '')}</textarea><label class="control-label" for="experience-notes">阅读密度、卡片、话题组织或详情的建议</label><textarea id="experience-notes" name="notes" rows="2" maxlength="4000">${escape(value.notes || '')}</textarea><div class="form-footer"><button class="primary-button" type="submit">保存体验反馈 ${icon('check')}</button><span>参数用于 R0 评审，尚未固定为产品规则。</span></div></form></section>`;
}

function notFound() { shell('<div class="empty-state"><h1>没有这个阅读条目</h1><p>可以回到当天精选，或从全部真实候选开始。</p><a href="#/today">返回当天精选</a></div>', 'detail'); }

function render() {
  const experienceFormElement = document.querySelector('#experience-form');
  if (experienceFormElement) experienceDraft = Object.fromEntries(new FormData(experienceFormElement));
  const current = route();
  if (current.pathname === '/today' || current.pathname === '/') todayPage();
  else if (current.pathname === '/feed') feedPage(current);
  else if (current.pathname === '/review') reviewPage(current);
  else if (current.pathname.startsWith('/content/')) contentPage(current.pathname.split('/')[2]);
  else if (current.pathname.startsWith('/topic/')) topicPage(current.pathname.split('/')[2]);
  else notFound();
  updateReviewCount();
}

document.addEventListener('click', event => {
  if (event.target.closest('.skip-link')) {
    event.preventDefault();
    const main = document.querySelector('#main');
    main?.scrollIntoView();
    main?.focus({ preventScroll: true });
    return;
  }
  const navigation = event.target.closest('a[href^="#/"]');
  if (navigation) {
    scrollPositions.set(location.hash, window.scrollY);
    if (navigation.classList.contains('detail-link')) rememberReturnTarget(navigation.getAttribute('href'));
  }
  const interest = event.target.closest('[data-interest]');
  if (interest) {
    const { kind, id } = interest.dataset;
    const value = reviewValue(kind, id);
    value.interest = value.interest === interest.dataset.interest ? null : interest.dataset.interest;
    const draftKey = `${kind}:${id}`;
    if (draftReviews.has(draftKey)) draftReviews.set(draftKey, { ...draftReviews.get(draftKey), interest: value.interest });
    if (hasReview(value)) feedback[kind][id] = value;
    else delete feedback[kind][id];
    saveFeedback();
    const position = window.scrollY;
    render();
    window.scrollTo(0, position);
    toast(saveFailed ? '保存失败，请及时导出反馈。' : value.interest ? '已记录，可再次点击撤销。只针对这一条内容。' : '已撤销兴趣反馈。');
    return;
  }
  const density = event.target.closest('button[data-density]');
  if (density) {
    feedback.experience.density = density.dataset.density;
    saveFeedback(); render(); return;
  }
  const button = event.target.closest('[data-action]');
  if (!button) return;
  const { action } = button.dataset;
  if (action === 'theme') {
    const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    store('unspun:r0:theme', next);
  } else if (action === 'version') {
    version = version === 'early' ? 'updated' : 'early';
    store('unspun:r0:selection-version', version);
    render(); toast(`已载入 ${manifest.selection_versions[version].label}；这是已有材料的版本回放。`);
  } else if (action === 'back') {
    const target = returnTargets.get(location.hash);
    location.hash = target?.hash || '#/feed';
  } else if (action === 'jump-feedback') {
    event.preventDefault(); document.querySelector('#feedback-title')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    document.querySelector('#review-form input')?.focus({ preventScroll: true });
  } else if (action === 'clear-review') {
    delete feedback[button.dataset.kind][button.dataset.id];
    draftReviews.delete(`${button.dataset.kind}:${button.dataset.id}`);
    saveFeedback(); const position = window.scrollY; render(); window.scrollTo(0, position); toast('已撤销本条反馈，所有评价恢复未知。');
  } else if (action === 'export') {
    const result = exportFeedback(feedback, dataset.candidates, manifest, version);
    const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' }));
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = `unspun-r0-feedback-${manifest.reference_date}.json`; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    toast(`已导出 ${reviewCount()} 个候选反馈，以及话题和体验建议。`);
  }
});

document.addEventListener('input', event => {
  const form = event.target.closest('#review-form');
  if (form) {
    const data = new FormData(form);
    const value = reviewValue(form.dataset.kind, form.dataset.id);
    for (const field of ['worth_reading_now', 'place', 'reason']) value[field] = data.get(field) || null;
    for (const field of ['interest_1_to_5', 'importance_1_to_5']) value[field] = data.has(field) ? Number(data.get(field)) : null;
    draftReviews.set(`${form.dataset.kind}:${form.dataset.id}`, value);
    document.querySelector('[data-save-state]').textContent = '有未保存的修改';
  }
});

document.addEventListener('change', event => {
  if (event.target.matches('[data-experience="selection_limit"]')) {
    feedback.experience.selection_limit = Number(event.target.value);
    saveFeedback(); render();
  }
});

document.addEventListener('submit', event => {
  event.preventDefault();
  const form = event.target;
  const data = new FormData(form);
  if (form.id === 'review-form') {
    const { kind, id } = form.dataset;
    const value = draftReviews.get(`${kind}:${id}`) || reviewValue(kind, id);
    if (hasReview(value)) feedback[kind][id] = value;
    else delete feedback[kind][id];
    draftReviews.delete(`${kind}:${id}`);
    saveFeedback();
    document.querySelector('[data-save-state]').textContent = saveFailed ? '本地保存失败，请导出' : '已保存，可修改或撤销';
    toast(saveFailed ? '保存失败，请导出反馈保留。' : hasReview(value) ? '评价已保存。兴趣、重要性与当前阅读价值分别记录。' : '还没有填写评价，保留未知。');
  } else if (form.id === 'experience-form') {
    for (const field of ['refresh_preference', 'update_assessment', 'notes', 'missing']) {
      const value = data.get(field);
      if (value) feedback.experience[field] = value;
      else delete feedback.experience[field];
    }
    experienceDraft = null;
    saveFeedback(); toast(saveFailed ? '保存失败，请导出反馈保留。' : '体验建议已保存，导出时会一并带上。');
  } else if (form.id === 'search-form') {
    const current = route();
    location.hash = routeLink('/review', { filter: current.searchParams.get('filter') || 'all', q: data.get('q') });
  }
});

window.addEventListener('hashchange', () => {
  render();
  requestAnimationFrame(() => {
    if (route().hash === '#experience') document.querySelector('#experience')?.scrollIntoView();
    else window.scrollTo(0, scrollPositions.get(location.hash) || 0);
    document.querySelector('#main')?.focus({ preventScroll: true });
  });
});

async function start() {
  const resources = await Promise.all(['/data/candidates.json', '/data/manifest.json', '/data/materials.json', '/data/fingerprint.json'].map(async url => {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`Resource unavailable: ${url}`);
    return response.json();
  }));
  [dataset, manifest] = resources;
  fingerprint = resources[3].sha256;
  byId = Object.fromEntries(dataset.candidates.map(candidate => [candidate.id, candidate]));
  materials = {};
  const pack = resources[2];
  if (pack.dataset_sha256 === fingerprint) {
    for (const [id, material] of Object.entries(pack.materials)) {
      const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(material.text)))).map(value => value.toString(16).padStart(2, '0')).join('');
      if (hash === byId[id]?.material_sha256 && material.sha256 === hash && Array.isArray(material.paragraphs) && material.paragraphs.every(paragraph => typeof paragraph === 'string') && material.paragraphs.join('').replace(/\s+/g, '') === material.text.replace(/\s+/g, '')) materials[id] = material;
      else materialWarning = true;
    }
  } else if (pack.archive_available) materialWarning = true;
  storageKey = `unspun:r0:feedback:${fingerprint}`;
  feedback = restoreFeedback(readStorage(storageKey), fingerprint, Object.keys(byId), manifest.topics.map(topic => topic.id));
  document.documentElement.dataset.theme = readStorage('unspun:r0:theme') === 'dark' ? 'dark' : 'light';
  version = readStorage('unspun:r0:selection-version') === 'updated' ? 'updated' : 'early';
  render();
  if (materialWarning) toast('部分本地材料未通过指纹核对，已保留原文入口。');
}

start().catch(error => {
  console.error(error);
  app.innerHTML = '<div class="load-error"><h1>样本暂时没有载入</h1><p>请确认从本地预览服务打开此页，再刷新重试。</p><button id="reload">重新载入</button></div>';
  document.querySelector('#reload').addEventListener('click', () => location.reload());
});
