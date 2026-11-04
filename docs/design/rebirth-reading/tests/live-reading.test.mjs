import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile, writeFile, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { buildPublication, loadPublication } from '../loop/publication.mjs';
import { loadCatalog, startServer } from '../server.mjs';

const publicationPath = new URL('../loop/published-batch-a.json', import.meta.url);

test('real batch serves only its selected readings and preserves the full discovery denominator', async () => {
  const catalog = await loadCatalog(publicationPath);
  assert.deepEqual(catalog.counts, { all: 4, event: 2, article: 2 });
  assert.equal(catalog.batch.candidates.length, 24);
  assert.equal(catalog.batch.decisions.length, 24);
  assert.equal(catalog.batch.sources.length, 4);
  assert.equal(catalog.batch.sources.filter(source => source.status === 'failed').length, 1);
  assert.equal(catalog.batch.processing.method, 'assistant-editorial');
  assert.equal(catalog.batch.usage.modelCost, null);
  for (const item of catalog.selections) {
    assert.ok(item.reading.sections.length >= 3);
    assert.notEqual(item.reading.lead, item.summary);
    assert.ok(item.summary.length <= 120);
  }
  assert.doesNotMatch(JSON.stringify(catalog), /bodyPath|rawPath|\/Users\//);
});

test('live feedback requires the current reading revision and preserves both earlier editions byte for byte', async () => {
  const stateDir = await mkdtemp(join(tmpdir(), 'unspun-live-test-'));
  const legacy = '{"old":{"value":"unclear"}}\n';
  const v2 = '{"second":{"interest":"worthwhile","quality":null}}\n';
  await writeFile(join(stateDir, 'feedback.json'), legacy);
  await writeFile(join(stateDir, 'feedback-v2.json'), v2);
  let running = await startServer({ port: 0, stateDir, publicationPath });
  const close = () => new Promise(resolve => running.server.close(resolve));
  const post = (route, body) => fetch(`${running.url}${route}`, {
    method: 'POST', headers: { Origin: running.url, 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  try {
    const catalog = await (await fetch(`${running.url}/api/catalog`)).json();
    const route = `/api/feedback/${catalog.edition}`;
    const body = { itemId: catalog.materials.find(item => item.selected).id, dimension: 'interest', value: 'worthwhile', revision: catalog.revision };
    assert.deepEqual(await (await fetch(`${running.url}${route}`)).json(), {});
    assert.equal((await post(route, { ...body, revision: 'stale' })).status, 409);
    assert.equal((await post('/api/feedback/v2', body)).status, 409);
    assert.equal((await post(route, null)).status, 400);
    assert.equal((await post(route, body)).status, 200);
    const originalStatePath = running.statePath;
    const saved = await readFile(originalStatePath, 'utf8');
    await close();
    running = await startServer({ port: 0, stateDir, publicationPath });
    assert.deepEqual(await (await fetch(`${running.url}${route}`)).json(), JSON.parse(saved));
    await close();

    const original = await loadPublication(publicationPath);
    const { provenance } = original;
    const editorial = JSON.parse(await readFile(new URL('../loop/editorial-batch-a.json', import.meta.url), 'utf8'));
    editorial.materials.find(item => item.selected).title += ' (revised test reading)';
    const revised = buildPublication({ schemaVersion: 1, runId: original.runId,
      startedAt: provenance.phases[0].startedAt, updatedAt: original.publishedAt,
      ...provenance }, editorial);
    const revisedPath = join(stateDir, 'revised.json');
    await writeFile(revisedPath, JSON.stringify(revised));
    running = await startServer({ port: 0, stateDir, publicationPath: revisedPath });
    assert.notEqual(running.statePath, originalStatePath);
    assert.deepEqual(await (await fetch(`${running.url}${route}`)).json(), {});
    assert.equal((await post(route, body)).status, 409);
    assert.equal(await readFile(originalStatePath, 'utf8'), saved);
    assert.equal(await readFile(join(stateDir, 'feedback.json'), 'utf8'), legacy);
    assert.equal(await readFile(join(stateDir, 'feedback-v2.json'), 'utf8'), v2);
  } finally { await close(); await rm(stateDir, { recursive: true, force: true }); }
});
