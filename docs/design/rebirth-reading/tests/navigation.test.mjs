import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const source = await readFile(new URL('../app.mjs', import.meta.url), 'utf8');
const bootstrap = source.indexOf('\ndocument.addEventListener(');
assert.ok(bootstrap > 0, 'The app bootstrap boundary must remain identifiable');
const materials = JSON.parse(await readFile(new URL('../data/article-materials.json', import.meta.url), 'utf8')).slice(0, 2);

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function harness(fetch) {
  let html = '', region = null, buttons = [];
  const element = { setAttribute() {}, removeAttribute() {} };
  const toast = { textContent: '', classList: { add() {}, remove() {} } };
  const storage = new Map();
  const main = {
    get innerHTML() { return html; },
    set innerHTML(value) {
      html = value;
      buttons = [];
      const match = value.match(/id="feedback-region" data-item-id="([^"]*)">([\s\S]*?)<\/section><\/div>/);
      region = match ? {
        dataset: { itemId: match[1] },
        get innerHTML() { return this.content; },
        set innerHTML(content) {
          this.content = content;
          buttons = [...content.matchAll(/<button[^>]*data-feedback="([^"]*)" data-id="([^"]*)"[^>]*>/g)].map(button => ({
            dataset: { feedback: button[1], id: button[2] },
            disabled: false,
            addEventListener(_event, callback) { this.click = callback; },
          }));
        },
      } : null;
      if (region) region.innerHTML = `${match[2]}</section>`;
    },
    querySelector() { return { textContent: html.match(/<h1>(.*?)<\/h1>/)?.[1] || '' }; },
    focus() {},
  };
  const context = vm.createContext({
    URL, URLSearchParams,
    fetch,
    location: { hash: '' },
    sessionStorage: { getItem: key => storage.get(key), setItem: (key, value) => storage.set(key, value) },
    setTimeout: () => 0, clearTimeout() {}, requestAnimationFrame: callback => callback(), scrollTo() {},
    document: {
      querySelector: selector => ({ '#main': main, '#feedback-region': region, '#toast': toast })[selector] ?? element,
      querySelectorAll: selector => selector === '[data-feedback]' ? buttons : [],
    },
    fixtureCatalog: { materials, events: [], counts: { all: 2, event: 0, article: 2 } },
  });
  // Execute the actual view and request handlers, excluding only browser startup.
  vm.runInContext(source.slice(0, bootstrap), context);
  vm.runInContext('catalog = fixtureCatalog', context);
  return {
    main, toast,
    get region() { return region; },
    get buttons() { return buttons; },
    navigate(hash) { context.location.hash = hash; return vm.runInContext('render()', context); },
  };
}

test('a delayed feedback response cannot replace another article controls', async () => {
  const response = deferred();
  const requests = [];
  const app = harness((path, options) => { requests.push({ path, ...JSON.parse(options.body) }); return response.promise; });
  await app.navigate(`#/article/${materials[0].id}`);
  const saving = app.buttons[0].click();
  await app.navigate(`#/article/${materials[1].id}`);
  const before = app.region.innerHTML;
  response.resolve({ ok: true, json: async () => ({ [materials[0].id]: { value: 'worthwhile' } }) });
  await saving;
  assert.equal(app.region.dataset.itemId, materials[1].id);
  assert.equal(app.region.innerHTML, before);
  assert.ok(app.buttons.every(button => button.dataset.id === materials[1].id));
  assert.deepEqual(requests, [{ path: '/api/feedback', itemId: materials[0].id, value: 'worthwhile' }]);
});

test('feedback still updates controls when the reader remains on the article', async () => {
  const response = deferred();
  const app = harness(() => response.promise);
  await app.navigate(`#/article/${materials[0].id}`);
  const saving = app.buttons[0].click();
  response.resolve({ ok: true, json: async () => ({ [materials[0].id]: { value: 'worthwhile' } }) });
  await saving;
  assert.match(app.region.innerHTML, /data-feedback="worthwhile"[^>]*aria-pressed="true"/);
  assert.ok(app.buttons.some(button => button.dataset.feedback === ''));
});

for (const route of ['#/curated', '#/hot']) {
  test(`a late failure from ${route} cannot replace a newer article`, async () => {
    const response = deferred();
    const app = harness(() => response.promise);
    const loading = app.navigate(route);
    await app.navigate(`#/article/${materials[1].id}`);
    const before = app.main.innerHTML;
    response.reject(new Error('Delayed source failure'));
    await loading;
    assert.equal(app.main.innerHTML, before);
    assert.equal(app.region.dataset.itemId, materials[1].id);
  });
}
