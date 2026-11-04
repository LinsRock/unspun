import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile, writeFile, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createCatalog, getFeed, getHot } from '../read-model.mjs';
import { loadCatalog, startServer } from '../server.mjs';

const data = await Promise.all(['event-materials', 'article-materials', 'events'].map(name => readFile(new URL(`../data/${name}.json`, import.meta.url), 'utf8').then(JSON.parse)));
const original = createCatalog([...data[0], ...data[1]], data[2]);
const catalog = await loadCatalog();

test('sample provenance, source eligibility and event evidence stay consistent', () => {
  assert.equal(original.materials.length, 24);
  assert.equal(catalog.materials.length, 27);
  const ids = new Set(catalog.materials.map(item => item.id));
  assert.equal(ids.size, catalog.materials.length);
  assert.equal(new Set(catalog.materials.map(item => item.url)).size, catalog.materials.length);
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

test('edition 2 curates complete readings without rewriting the original candidate records', () => {
  assert.equal(catalog.edition, 'v2');
  assert.equal(catalog.selections.length, 7);
  assert.equal(catalog.counts.article, 4);
  assert.equal(catalog.counts.event, 3);
  for (const old of original.materials) {
    const revised = catalog.materials.find(item => item.id === old.id);
    for (const field of ['title', 'url', 'publishedAt', 'paragraphs', 'verification', 'eventIds']) {
      assert.deepEqual(revised[field], old[field], `${old.id}: original ${field}`);
    }
    assert.equal(revised.previouslySelected, old.selected);
  }
  for (const item of catalog.selections) {
    const { reading } = item;
    assert.ok(reading, item.id);
    assert.ok(reading.sections.length >= 3, item.id);
    assert.ok(reading.references.length >= 3, item.id);
    assert.notEqual(reading.lead, item.summary, item.id);
    const sourceIds = new Set(reading.references.map(source => source.id));
    assert.equal(sourceIds.size, reading.references.length, item.id);
    for (const section of reading.sections) {
      assert.ok(section.paragraphs.length >= 2, item.id);
      assert.ok(section.sourceIds.length, item.id);
      for (const id of section.sourceIds) assert.ok(sourceIds.has(id), `${item.id}: ${id}`);
      assert.ok(section.paragraphs.every(paragraph => paragraph !== item.summary && !item.paragraphs?.includes(paragraph)), item.id);
    }
    for (const source of reading.references) {
      assert.match(source.url, /^https:\/\//, item.id);
      assert.ok(source.scope?.length > 0, item.id);
    }
  }
  assert.equal(catalog.materials.find(item => item.id === 'a-cooking-workdays').selected, false);
  assert.match(catalog.events.find(item => item.id === 'event-shenzhong').summary, /289/);
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
  assert.deepEqual(hot.items.map(item => item.id).sort(), getFeed(catalog, 'event').items.map(item => item.id).sort());
  assert.ok(hot.items.every(item => item.attention === null && !('rank' in item)));
});

test('v2 HTTP feedback preserves both dimensions and the exact original feedback across restarts', async () => {
  const stateDir = await mkdtemp(join(tmpdir(), 'unspun-rebirth-test-'));
  const legacy = '{\n  "event-deepseek-r1": {"value":"worthwhile","updatedAt":"2026-11-04T01:00:00Z"},\n  "a-cooking-workdays": {"value":"unclear"}\n}\n';
  await writeFile(join(stateDir, 'feedback.json'), legacy);
  let running = await startServer({ port: 0, stateDir });
  const close = () => new Promise(resolve => running.server.close(resolve));
  const request = (path, body, origin = running.url) => fetch(`${running.url}${path}`, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json', Origin: origin }, body: JSON.stringify(body),
  });
  try {
    assert.equal((await request('/')).status, 200);
    assert.equal((await request('/api/catalog')).status, 200);
    const before = await (await request('/api/feed')).json();
    assert.deepEqual(await (await request('/api/feedback/v1')).json(), JSON.parse(legacy));
    assert.deepEqual(await (await request('/api/feedback/v2')).json(), {});
    const [first, second] = catalog.selections;
    const writes = await Promise.all([
      request('/api/feedback/v2', { itemId: first.id, dimension: 'interest', value: 'worthwhile' }),
      request('/api/feedback/v2', { itemId: first.id, dimension: 'quality', value: 'too_shallow' }),
      request('/api/feedback/v2', { itemId: second.id, dimension: 'quality', value: 'unclear' }),
    ]);
    assert.ok(writes.every(response => response.status === 200));
    const otherClient = await (await fetch(`${running.url}/api/feedback/v2`)).json();
    assert.equal(otherClient[first.id].interest, 'worthwhile');
    assert.equal(otherClient[first.id].quality, 'too_shallow');
    assert.equal(otherClient[second.id].quality, 'unclear');
    assert.equal(otherClient[second.id].interest, null);
    assert.deepEqual(await (await request('/api/feed')).json(), before);
    assert.equal((await request('/api/feedback/v2', { itemId: first.id, dimension: 'all', value: null }, 'https://example.com')).status, 403);
    assert.equal((await request('/api/feedback/v2', { itemId: 'missing', dimension: 'quality', value: 'unclear' })).status, 400);
    assert.equal((await request('/api/feedback/v2', { itemId: first.id, dimension: 'interest', value: 'unclear' })).status, 400);
    assert.equal((await request('/api/feedback', { itemId: first.id, value: 'unclear' })).status, 409);
    assert.equal((await request('/api/feed?type=unknown')).status, 400);
    assert.equal((await request('/server.mjs')).status, 404);
    await close();
    running = await startServer({ port: 0, stateDir });
    const persisted = await (await request('/api/feedback/v2')).json();
    assert.deepEqual(persisted, otherClient);
    await request('/api/feedback/v2', { itemId: first.id, dimension: 'quality', value: null });
    const oneDimension = await (await request('/api/feedback/v2')).json();
    assert.equal(oneDimension[first.id].interest, 'worthwhile');
    assert.equal(oneDimension[first.id].quality, null);
    await request('/api/feedback/v2', { itemId: first.id, dimension: 'all', value: null });
    const undone = await (await request('/api/feedback/v2')).json();
    assert.ok(!(first.id in undone));
    assert.equal(undone[second.id].quality, 'unclear');
    const written = JSON.parse(await readFile(running.statePath, 'utf8'));
    assert.deepEqual(written, undone);
    assert.equal(await readFile(running.legacyPath, 'utf8'), legacy);
    assert.deepEqual(await (await request('/api/feedback')).json(), JSON.parse(legacy));
  } finally { await close(); await rm(stateDir, { recursive: true, force: true }); }
});
