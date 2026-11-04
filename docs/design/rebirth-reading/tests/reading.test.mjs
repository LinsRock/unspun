import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createCatalog, getFeed, getHot } from '../read-model.mjs';
import { startServer } from '../server.mjs';

const data = await Promise.all(['event-materials', 'article-materials', 'events'].map(name => readFile(new URL(`../data/${name}.json`, import.meta.url), 'utf8').then(JSON.parse)));
const catalog = createCatalog([...data[0], ...data[1]], data[2]);

test('sample provenance, source eligibility and event evidence stay consistent', () => {
  assert.equal(catalog.materials.length, 24);
  const ids = new Set(catalog.materials.map(item => item.id));
  assert.equal(ids.size, catalog.materials.length);
  assert.equal(new Set(catalog.materials.map(item => item.url)).size, 24);
  assert.ok(new Set(catalog.materials.map(item => item.domain)).size >= 3);
  for (const item of catalog.materials) {
    assert.match(item.url, /^https?:\/\//);
    assert.ok(item.publishedAt === null || /^\d{4}-\d{2}-\d{2}$/.test(item.publishedAt));
    assert.ok(item.summary.length <= 120, item.id);
    assert.ok(item.verification.note.length > 0, item.id);
    if (item.materialScope === 'metadata' || item.role === 'duplicate') assert.equal(item.selected, false, item.id);
    for (const id of item.eventIds) assert.ok(catalog.events.some(event => event.id === id && event.materialIds.includes(item.id)), item.id);
  }
  for (const event of catalog.events) {
    assert.equal(event.attention, null);
    for (const id of event.materialIds) assert.ok(ids.has(id), id);
    for (const development of event.developments) {
      assert.ok(development.materialIds.length);
      for (const id of development.materialIds) {
        assert.ok(event.materialIds.includes(id), id);
        assert.notEqual(catalog.materials.find(item => item.id === id).materialScope, 'metadata', id);
      }
    }
  }
});

test('every filter paginates before slicing without duplicates, omissions or raw pool leaks', () => {
  for (const type of ['all', 'event', 'article']) {
    const received = [];
    let cursor = '';
    do {
      const page = getFeed(catalog, type, cursor, 2);
      received.push(...page.items);
      cursor = page.nextCursor;
    } while (cursor);
    const expected = catalog.selections.filter(item => type === 'all' || item.type === type);
    assert.deepEqual(received.map(item => item.id), expected.map(item => item.id));
    assert.equal(new Set(received.map(item => item.id)).size, received.length);
    assert.ok(received.every(item => item.selected && item.role !== 'duplicate'));
  }
  const cursor = getFeed(catalog, 'all', '', 2).nextCursor;
  assert.throws(() => getFeed(catalog, 'article', cursor), /incompatible/);
  assert.throws(() => getFeed({ ...catalog, revision: 'changed' }, 'all', cursor), /Stale/);
  assert.throws(() => getFeed(catalog, 'all', 'garbage'), /cursor/);
  assert.throws(() => getFeed(catalog, 'video'), /type/);
});

test('a selected independent article remains readable without grouping or an event', () => {
  const article = catalog.materials.find(item => item.selected && !item.eventIds.length);
  assert.ok(article);
  const independent = createCatalog([{ ...article, groupingStatus: 'pending' }], []);
  const feed = getFeed(independent, 'article');
  assert.equal(feed.items[0].id, article.id);
  assert.deepEqual(feed.items[0].eventIds, []);
  assert.equal(feed.items[0].groupingStatus, 'pending');
});

test('hot samples share event identity and disclose absent attention instead of synthetic ranks', () => {
  const hot = getHot(catalog);
  assert.equal(hot.ranked, false);
  assert.equal(hot.status, 'attention-unmeasured');
  assert.deepEqual(hot.items.map(item => item.id), getFeed(catalog, 'event').items.map(item => item.id));
  assert.ok(hot.items.every(item => item.attention === null && !('rank' in item)));
});

test('real HTTP feedback is shared, reversible, restart-persistent and not changed by reads', async () => {
  const stateDir = await mkdtemp(join(tmpdir(), 'unspun-rebirth-test-'));
  let running = await startServer({ port: 0, stateDir });
  const close = () => new Promise(resolve => running.server.close(resolve));
  const request = (path, body, origin = running.url) => fetch(`${running.url}${path}`, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json', Origin: origin }, body: JSON.stringify(body),
  });
  try {
    assert.equal((await request('/')).status, 200);
    assert.equal((await request('/api/catalog')).status, 200);
    const before = await (await request('/api/feed')).json();
    assert.deepEqual(await (await request('/api/feedback')).json(), {});
    const [first, second] = catalog.selections;
    await Promise.all([request('/api/feedback', { itemId: first.id, value: 'worthwhile' }), request('/api/feedback', { itemId: second.id, value: 'unclear' })]);
    const otherClient = await (await fetch(`${running.url}/api/feedback`)).json();
    assert.equal(otherClient[first.id].value, 'worthwhile');
    assert.equal(otherClient[second.id].value, 'unclear');
    assert.deepEqual(await (await request('/api/feed')).json(), before);
    assert.equal((await request('/api/feedback', { itemId: first.id, value: null }, 'https://example.com')).status, 403);
    assert.equal((await request('/api/feedback', { itemId: 'missing', value: 'unclear' })).status, 400);
    assert.equal((await request('/api/feed?type=unknown')).status, 400);
    assert.equal((await request('/server.mjs')).status, 404);
    await close();
    running = await startServer({ port: 0, stateDir });
    const persisted = await (await request('/api/feedback')).json();
    assert.equal(persisted[first.id].value, 'worthwhile');
    await request('/api/feedback', { itemId: first.id, value: null });
    const undone = await (await request('/api/feedback')).json();
    assert.ok(!(first.id in undone));
    assert.equal(undone[second.id].value, 'unclear');
    const written = JSON.parse(await readFile(running.statePath, 'utf8'));
    assert.deepEqual(written, undone);
  } finally { await close(); await rm(stateDir, { recursive: true, force: true }); }
});
