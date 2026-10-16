import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { webcrypto } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';
import test from 'node:test';

// Reuse the existing test dependency without changing the application dependencies.
const require = createRequire(new URL('../../../web/package.json', import.meta.url));
const { JSDOM } = require('jsdom');
const baseUrl = process.env.R0_PREVIEW_URL || 'http://127.0.0.1:4178';

test('reading and feedback paths work against the local server with no write API', async () => {
  const template = await readFile(new URL('./index.html', import.meta.url), 'utf8');
  const dom = new JSDOM(template, { url: baseUrl, pretendToBeVisual: true });
  const { window } = dom;
  let scrollY = 0;
  window.scrollTo = (_x, y) => { scrollY = y; };
  Object.defineProperty(window, 'scrollY', { get: () => scrollY });
  window.HTMLElement.prototype.scrollIntoView = () => {};
  const nativeFetch = globalThis.fetch;
  const withoutMaterials = process.env.R0_TEST_WITHOUT_MATERIALS === '1';
  const materialPack = withoutMaterials ? { materials: {} } : await (await nativeFetch(`${baseUrl}/data/materials.json`)).json();
  Object.assign(globalThis, {
    window, document: window.document, location: window.location,
    localStorage: window.localStorage, FormData: window.FormData,
    requestAnimationFrame: callback => { callback(); return 0; },
    fetch: resource => withoutMaterials && resource === '/data/materials.json'
      ? Promise.resolve(new Response(JSON.stringify({ materials: {}, archive_available: false })))
      : nativeFetch(new URL(resource, baseUrl)),
  });
  Object.defineProperty(globalThis, 'crypto', { value: webcrypto, configurable: true });
  const errors = [];
  const onError = event => errors.push(event.error || event.message);
  window.addEventListener('error', onError);

  const settle = async (predicate, label) => {
    for (let attempt = 0; attempt < 120; attempt++) {
      if (predicate()) return;
      await delay(20);
    }
    assert.fail(`DOM did not settle: ${label}`);
  };
  const go = async (hash, predicate) => {
    window.location.hash = hash;
    await settle(predicate, hash);
  };
  const click = element => {
    assert.ok(element, 'Expected clickable element');
    element.dispatchEvent(new window.MouseEvent('click', { bubbles: true, cancelable: true }));
  };
  const choose = (name, value) => {
    const input = window.document.querySelector(`input[name="${name}"][value="${value}"]`);
    assert.ok(input, `${name}=${value}`);
    input.checked = true;
    input.dispatchEvent(new window.Event('input', { bubbles: true }));
  };
  const submit = selector => window.document.querySelector(selector).dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true }));
  const contentText = () => window.document.querySelector('#main').textContent;
  try {
    await import(`./app.js?dom-test=${Date.now()}`);
    await settle(() => window.document.querySelector('.today-lead'), 'initial page');
    assert.equal(window.document.querySelectorAll('[data-entry]').length, 8);
    assert.equal(window.document.querySelector('.today-lead [data-entry]').dataset.entry, 'market');
    assert.ok(!contentText().includes('材料未通过'));
    assert.ok(!localStorage.getItem([...Array(localStorage.length)].map((_, index) => localStorage.key(index)).find(key => key?.includes('feedback'))));

    click(window.document.querySelector('[data-action="version"]'));
    assert.deepEqual(errors, []);
    assert.match(contentText(), /C05/);
    assert.match(window.document.querySelector('.today-lead').textContent, /3 份材料/);
    assert.equal(localStorage.getItem('unspun:r0:selection-version'), 'updated');

    click(window.document.querySelector('button[data-density="compact"]'));
    assert.equal(window.document.documentElement.dataset.density, 'compact');
    click(window.document.querySelector('button[data-density="comfortable"]'));
    const limit = window.document.querySelector('#selection-limit');
    limit.value = '4';
    limit.dispatchEvent(new window.Event('change', { bubbles: true }));
    assert.equal(window.document.querySelectorAll('.today-lead [data-entry], .selection-grid [data-entry]').length, 4);
    window.document.querySelector('#selection-limit').value = '8';
    window.document.querySelector('#selection-limit').dispatchEvent(new window.Event('change', { bubbles: true }));
    assert.equal(window.document.querySelectorAll('.today-lead [data-entry], .selection-grid [data-entry]').length, 6);
    click(window.document.querySelector('[data-action="theme"]'));
    assert.equal(window.document.documentElement.dataset.theme, 'dark');
    click(window.document.querySelector('[data-action="theme"]'));
    assert.equal(window.document.documentElement.dataset.theme, 'light');

    await go('#/feed', () => window.document.querySelector('.feed-list'));
    assert.equal(window.document.querySelectorAll('.feed-list [data-entry]').length, 18);
    assert.equal(window.document.querySelector('.segmented a.selected').textContent, '推荐');
    const recommended = [...window.document.querySelectorAll('.feed-list [data-entry]')].map(element => element.dataset.entry);
    await go('#/feed?sort=latest', () => window.document.querySelector('.segmented a.selected')?.textContent === '最新');
    const latest = [...window.document.querySelectorAll('.feed-list [data-entry]')].map(element => element.dataset.entry);
    assert.notDeepEqual(latest, recommended);
    assert.equal(latest.at(-1), 'C29');
    assert.ok(!latest.includes('C41'));

    window.scrollTo(0, 650);
    click(window.document.querySelector('[href="#/content/C14"]'));
    await settle(() => window.document.querySelector('#review-form')?.dataset.id === 'C14', 'content detail');
    assert.equal(window.scrollY, 0);
    if (materialPack.materials?.C14) assert.ok(window.document.querySelectorAll('.article-body p').length > 8);
    else {
      assert.ok(window.document.querySelector('.empty-material'));
      assert.equal(window.document.querySelector('.article-body'), null);
    }
    assert.match(contentText(), /2026-10-12 16:25/);
    assert.match(window.document.querySelector('.scope-note').textContent, /不据标题判断/);

    choose('worth_reading_now', 'yes');
    choose('interest_1_to_5', '5');
    choose('importance_1_to_5', '3');
    choose('place', 'recommended');
    const reason = window.document.querySelector('#review-reason');
    reason.value = 'DOM fixture: keep the source and the original date.';
    reason.dispatchEvent(new window.Event('input', { bubbles: true }));
    click(window.document.querySelector('.article-actions [data-interest="yes"]'));
    submit('#review-form');
    const key = Object.keys(localStorage).find(entry => entry.startsWith('unspun:r0:feedback:'));
    let saved = JSON.parse(localStorage.getItem(key));
    assert.equal(saved.contents.C14.interest_1_to_5, 5);
    assert.equal(saved.contents.C14.importance_1_to_5, 3);
    assert.equal(saved.contents.C14.worth_reading_now, 'yes');
    assert.equal(saved.contents.C14.interest, 'yes');
    assert.equal(window.document.querySelector('[data-review-count]').textContent, '1');
    click(window.document.querySelector('[data-action="back"]'));
    await settle(() => window.document.querySelector('.feed-list'), 'return to feed');
    assert.equal(window.location.hash, '#/feed?sort=latest');
    assert.equal(window.scrollY, 650);

    await go('#/topic/health', () => window.document.querySelector('.topic-reader'));
    assert.match(contentText(), /同篇转载/);
    assert.match(contentText(), /待核验，未生成/);
    assert.equal(window.document.querySelectorAll('.topic-source-list [data-entry]').length, 2);
    choose('worth_reading_now', 'yes');
    submit('#review-form');
    saved = JSON.parse(localStorage.getItem(key));
    assert.equal(saved.topics.health.worth_reading_now, 'yes');
    assert.equal(Object.keys(saved.contents).length, 1);

    await go('#/content/C07', () => window.document.querySelector('#review-form')?.dataset.id === 'C07');
    assert.match(contentText(), /公开预览结束/);
    if (materialPack.materials?.C07) assert.ok(window.document.querySelector('.article-body').textContent.length > 400);
    else assert.ok(window.document.querySelector('.empty-material'));
    await go('#/content/C03', () => window.document.querySelector('#review-form')?.dataset.id === 'C03');
    assert.match(contentText(), /没有字幕或全片导读/);
    assert.ok(window.document.querySelector('.media-placeholder'));
    assert.equal(window.document.querySelectorAll('video, iframe').length, 0);
    await go('#/content/C24', () => window.document.querySelector('#review-form')?.dataset.id === 'C24');
    assert.match(contentText(), /日报选编/);
    assert.match(contentText(), /原回答的全文与首发时间尚未核验/);
    await go('#/content/C27', () => window.document.querySelector('#review-form')?.dataset.id === 'C27');
    assert.match(contentText(), /不含回答/);
    await go('#/content/C39', () => window.document.querySelector('#review-form')?.dataset.id === 'C39');
    assert.ok(window.document.querySelector('.empty-material'));
    assert.equal(window.document.querySelector('.article-body'), null);

    await go('#/review', () => window.document.querySelector('.candidate-list'));
    assert.equal(window.document.querySelectorAll('[data-candidate]').length, 43);
    await go('#/review?filter=priority', () => window.document.querySelectorAll('[data-candidate]').length === 16);
    await go('#/review?filter=reviewed', () => window.document.querySelectorAll('[data-candidate]').length === 1);
    assert.equal(window.document.querySelector('[data-candidate]').dataset.candidate, 'C14');
    await go('#/review?filter=gaps', () => window.document.querySelector('.gaps-list'));
    assert.match(contentText(), /雪球/);
    assert.match(contentText(), /微博/);
    const experience = window.document.querySelector('#experience-form');
    experience.querySelector('[name="refresh_preference"]').value = '30_minutes';
    experience.querySelector('[name="update_assessment"]').value = 'wait';
    experience.querySelector('[name="missing"]').value = 'DOM fixture: missing community answers.';
    submit('#experience-form');

    const exportedBlobs = [];
    const originalCreate = URL.createObjectURL;
    const originalRevoke = URL.revokeObjectURL;
    const originalClick = window.HTMLAnchorElement.prototype.click;
    URL.createObjectURL = blob => { exportedBlobs.push(blob); return 'blob:r0-test'; };
    URL.revokeObjectURL = () => {};
    window.HTMLAnchorElement.prototype.click = function () { assert.match(this.download, /unspun-r0-feedback/); };
    click(window.document.querySelector('[data-action="export"]'));
    const exported = JSON.parse(await exportedBlobs[0].text());
    assert.equal(exported.candidates.length, 43);
    assert.equal(exported.reviewed_content_count, 1);
    assert.equal(exported.experience.refresh_preference, '30_minutes');
    assert.equal(exported.experience.update_assessment, 'wait');
    assert.equal(exported.candidates.find(candidate => candidate.id === 'C14').human_review.interest_1_to_5, 5);
    URL.createObjectURL = originalCreate;
    URL.revokeObjectURL = originalRevoke;
    window.HTMLAnchorElement.prototype.click = originalClick;

    await go('#/content/C14', () => window.document.querySelector('#review-form')?.dataset.id === 'C14');
    assert.ok(window.document.querySelector('input[name="interest_1_to_5"][value="5"]').checked);
    click(window.document.querySelector('[data-action="clear-review"]'));
    saved = JSON.parse(localStorage.getItem(key));
    assert.equal(saved.contents.C14, undefined);
    assert.equal(window.document.querySelector('[data-review-count]').textContent, '0');
    assert.equal(window.document.querySelectorAll('#review-form input:checked').length, 0);

    const setText = (selector, value) => {
      const element = window.document.querySelector(selector);
      element.value = value;
      element.dispatchEvent(new window.Event('input', { bubbles: true }));
    };
    setText('#review-reason', 'DOM fixture: a reason-only review.');
    submit('#review-form');
    assert.ok(JSON.parse(localStorage.getItem(key)).contents.C14.reason);
    setText('#review-reason', '');
    submit('#review-form');
    assert.equal(JSON.parse(localStorage.getItem(key)).contents.C14, undefined);
    await go('#/content/C07', () => window.document.querySelector('#review-form')?.dataset.id === 'C07');
    await go('#/content/C14', () => window.document.querySelector('#review-form')?.dataset.id === 'C14');
    assert.equal(window.document.querySelector('#review-reason').value, '');

    await go('#/review', () => window.document.querySelector('.candidate-list'));
    setText('#experience-notes', 'DOM fixture: an unsaved experience suggestion.');
    window.document.querySelector('[name="refresh_preference"]').value = '60_minutes';
    click(window.document.querySelector('[data-candidate="C01"] [data-interest="yes"]'));
    assert.equal(window.document.querySelector('#experience-notes').value, 'DOM fixture: an unsaved experience suggestion.');
    assert.equal(window.document.querySelector('[name="refresh_preference"]').value, '60_minutes');
    click(window.document.querySelector('[data-candidate="C01"] [data-interest="yes"]'));

    await go('#/feed?sort=latest', () => window.document.querySelector('.feed-list'));
    click(window.document.querySelector('[href="#/topic/health"]'));
    await settle(() => window.document.querySelector('.topic-reader'), 'feed to topic');
    click(window.document.querySelector('[href="#/content/C21"]'));
    await settle(() => window.document.querySelector('#review-form')?.dataset.id === 'C21', 'topic to member');
    click(window.document.querySelector('[href="#/topic/health"]'));
    await settle(() => window.document.querySelector('.topic-reader'), 'member to ancestor topic');
    click(window.document.querySelector('[data-action="back"]'));
    await settle(() => window.document.querySelector('.feed-list'), 'ancestor topic back to feed');
    assert.equal(window.location.hash, '#/feed?sort=latest');

    click(window.document.querySelector('.skip-link'));
    await delay(20);
    assert.equal(window.location.hash, '#/feed?sort=latest');
    assert.ok(window.document.querySelector('.feed-list'));
    assert.equal(window.document.activeElement.id, 'main');
    const denied = await nativeFetch(`${baseUrl}/api/feedback`, { method: 'POST', body: '{}' });
    assert.equal(denied.status, 405);
    const hidden = await nativeFetch(`${baseUrl}/.env`);
    assert.equal(hidden.status, 404);
    assert.deepEqual(errors, []);
  } finally {
    window.close();
    globalThis.fetch = nativeFetch;
  }
});
