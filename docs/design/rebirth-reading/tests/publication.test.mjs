import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { readFile, writeFile, mkdir, mkdtemp, rm, symlink, readdir } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { buildPublication, loadPublication } from '../loop/publication.mjs';
import { createCatalog, getFeed, getHot } from '../read-model.mjs';

const execute = promisify(execFile);
const cli = fileURLToPath(new URL('../loop/publication.mjs', import.meta.url));
const bodies = {
  article: 'Original article text describes a concrete mechanism and its limitations. 原文包含补充证据 🧪。',
  support: 'The supporting report describes the actual change, its source, and the conditions attached to it.',
};
const sha = value => createHash('sha256').update(value).digest('hex');
const hashObject = value => sha(JSON.stringify(value, (_, item) => item && typeof item === 'object' && !Array.isArray(item)
  ? Object.fromEntries(Object.keys(item).sort().map(key => [key, item[key]])) : item));
const clone = value => JSON.parse(JSON.stringify(value));

function fixture() {
  const candidate = (id, title, day) => ({
    id, sourceId: 'source-a', sourceName: 'Public source', domain: 'Technology', url: `https://example.org/${id}`,
    title, author: 'Original author', publishedAt: `${day}T08:00:00Z`, rawPublishedAt: `${day} 08:00 UTC`,
    discoveredAt: '2026-11-04T09:00:00Z', disposition: 'recent', bodyStatus: 'readable',
    bodyPath: `materials/${id}/versions/${sha(bodies[id])}/body.txt`, contentHash: sha(bodies[id]),
    materialScope: 'body', bodyChars: [...bodies[id]].length,
  });
  const first = candidate('article', 'Original article title', '2026-11-03');
  const second = candidate('support', 'Original supporting report', '2026-11-04');
  const failed = { ...first, id: 'failed', url: 'https://example.org/failed', title: 'Unresolved candidate',
    publishedAt: null, rawPublishedAt: 'unknown', disposition: 'unknown-date', bodyStatus: 'failed',
    contentHash: null, bodyChars: 0, bodyPath: null, materialScope: 'metadata' };
  const manifest = {
    schemaVersion: 1, runId: 'run-1', startedAt: '2026-11-04T09:00:00Z', updatedAt: '2026-11-04T09:05:00Z',
    sources: [
      { phaseId: 'discover-1', sourceId: 'source-a', sourceName: 'Public source', url: 'https://example.org/feed', status: 'ok',
        rawPath: '/private/tmp/source.xml', httpStatus: 200, candidateCount: 3 },
      { phaseId: 'discover-1', sourceId: 'blocked', sourceName: 'Blocked source', url: 'https://blocked.example.org/feed',
        status: 'failed', errorType: 'InvalidFeed', error: 'Bad feed saved at /private/tmp/source.html', httpStatus: 200 },
    ],
    candidates: [first, second, failed], usage: { requestCount: 5, elapsedMs: 250, modelCalls: 0, modelCost: null },
    phases: [{ id: 'discover-1', kind: 'collect', startedAt: '2026-11-04T09:00:00Z', completedAt: '2026-11-04T09:03:00Z', status: 'completed', windowDays: 14 },
      { id: 'hydrate-2', kind: 'hydrate', startedAt: '2026-11-04T09:03:00Z', completedAt: '2026-11-04T09:05:00Z', status: 'completed' }],
  };
  const reading = (source, id) => ({
    lead: `This ${id} reading explains the mechanism and the remaining uncertainty beyond its short card.`,
    takeaways: ['The reported result depends on the original source conditions.'],
    sections: [{ id: 'mechanism', title: 'How the change works',
      paragraphs: [
        `The ${id} changes a specific part of the workflow, as described in the source report and its concrete example.`,
        `That ${id} result does not establish a universal improvement; the source has not independently tested other settings.`,
      ], sourceIds: ['primary'] }],
    references: [{ id: 'primary', title: source.title, url: source.url, publisher: source.sourceName,
      publishedAt: source.publishedAt.slice(0, 10), scope: 'Public body; reported mechanism and limitations.' }],
  });
  const material = (source, selected, eventIds) => ({
    id: source.id, type: 'article', domain: source.domain, title: `Editorial guide to ${source.id}`, originalTitle: source.title,
    source: source.sourceName, sourceId: source.sourceId, author: 'Unspun editorial', publishedAt: source.publishedAt.slice(0, 10),
    url: source.url, materialScope: source.materialScope, summary: `A concise card about the ${source.id}.`,
    whyRead: 'Understand a concrete mechanism and its boundaries.', paragraphs: ['The card has a short contextual introduction.'],
    eventIds, role: 'analysis', selected, selectionReason: 'The source explains a mechanism relevant to this reading.',
    verification: { checkedAt: '2026-11-04', method: 'assistant-editorial', note: 'Read the collected public text and preserve its stated limits.' },
    ...(selected ? { reading: reading(source, source.id) } : {}),
  });
  const editorial = {
    schemaVersion: 1, runId: manifest.runId, edition: 'live-20261104-a', label: 'This round',
    startedAt: '2026-11-04T09:10:00Z', reviewedAt: '2026-11-04T09:20:00Z', method: 'assistant-editorial',
    decisions: [
      { candidateId: 'article', decision: 'selected', reason: 'The acquired body explains a specific mechanism and limitation.' },
      { candidateId: 'support', decision: 'supporting', reason: 'The acquired report provides the source evidence for the event.' },
      { candidateId: 'failed', decision: 'deferred', reason: 'The source publication date is unknown and the body could not be read.' },
    ],
    materials: [material(first, true, []), material(second, false, ['event-one'])],
    events: [{ id: 'event-one', domain: 'Technology', title: 'A reported change', summary: 'The event card states the reported change.',
      whyRead: 'Understand the reported change through its actual source.', paragraphs: ['The event has a short contextual introduction.'],
      developments: [{ date: '2026-11-04', title: 'Reported change', description: 'The publisher describes an actual development.', materialIds: ['support'] }],
      materialIds: ['support'], selected: true, attention: null, reading: reading(second, 'event') }],
    selectedIds: ['article', 'event-one'], supplementalSources: [],
  };
  return { manifest, editorial };
}

function invalid(change, pattern) {
  const value = fixture();
  change(value.manifest, value.editorial);
  assert.throws(() => buildPublication(value.manifest, value.editorial), pattern);
}

async function workspace(context) {
  const dir = await mkdtemp(join(tmpdir(), 'unspun-publication-'));
  context.after(() => rm(dir, { recursive: true, force: true }));
  const value = fixture();
  const manifestPath = join(dir, 'runs', value.manifest.runId, 'manifest.json');
  const editorialPath = join(dir, 'editorial.json');
  const outputPath = join(dir, 'published.json');
  await mkdir(dirname(manifestPath), { recursive: true });
  for (const candidate of value.manifest.candidates.filter(item => item.bodyStatus === 'readable')) {
    const bodyPath = join(dir, candidate.bodyPath);
    await mkdir(dirname(bodyPath), { recursive: true });
    await writeFile(bodyPath, bodies[candidate.id]);
  }
  const save = async () => {
    await writeFile(manifestPath, JSON.stringify(value.manifest));
    await writeFile(editorialPath, JSON.stringify(value.editorial));
  };
  await save();
  return { ...value, dir, manifestPath, editorialPath, outputPath, save,
    run: output => execute(process.execPath, [cli, '--manifest', manifestPath, '--editorial', editorialPath, '--output', output || outputPath]) };
}

test('publication includes only approved materials while preserving every candidate decision and real failures', () => {
  const { manifest, editorial } = fixture();
  const original = clone({ manifest, editorial });
  editorial.materials[0].bodyPath = '/private/editorial/body.txt';
  editorial.materials[0].reading.sections[0].localPath = '/private/editorial/source';
  const publication = buildPublication(manifest, editorial);
  assert.deepEqual(publication.materials.map(item => item.id), ['article', 'support']);
  assert.equal(publication.provenance.candidates.length, 3);
  assert.equal(publication.provenance.decisions.length, 3);
  assert.equal(publication.provenance.sources[1].status, 'failed');
  assert.equal(publication.provenance.sources[1].errorType, 'InvalidFeed');
  assert.equal(publication.provenance.processing.method, 'assistant-editorial');
  assert.deepEqual(publication.provenance.usage, manifest.usage);
  assert.doesNotMatch(JSON.stringify(publication), /bodyPath|rawPath|localPath|\/private\//);
  assert.deepEqual(manifest, original.manifest);
  assert.equal(publication.materials[0].publishedAt, '2026-11-03');
  assert.equal(publication.provenance.candidates[0].discoveredAt, '2026-11-04T09:00:00Z');
  assert.match(publication.publicationHash, /^[a-f0-9]{64}$/);
  const catalog = createCatalog(publication.materials, publication.events, publication.curation);
  assert.deepEqual(getFeed(catalog).items.map(item => item.id), ['article', 'event-one']);
  assert.deepEqual(getHot(catalog).items.map(item => item.id), ['event-one']);
  assert.equal(getHot(catalog).ranked, false);
  assert.equal(publication.materials[0].reading.references.length, 1);
});

test('every candidate gets exactly one substantive editorial decision', () => {
  invalid((_, editorial) => editorial.decisions.pop(), /every candidate/);
  invalid((_, editorial) => editorial.decisions.push(clone(editorial.decisions[0])), /exactly once/);
  invalid((_, editorial) => { editorial.decisions[0].candidateId = 'absent'; }, /exactly once/);
  invalid((_, editorial) => { editorial.decisions[0].reason = 'good'; }, /actual editorial judgment/);
  invalid((_, editorial) => { editorial.decisions[2].decision = 'rejected'; }, /must be deferred/);
  invalid((manifest, editorial) => {
    manifest.candidates[2].publishedAt = '2026-11-04T08:00:00Z'; manifest.candidates[2].disposition = 'recent';
    editorial.decisions[2].decision = 'rejected';
  }, /must be deferred/);
});

test('unfetched, metadata-only, unhashed and failed evidence cannot enter a reading', () => {
  invalid(manifest => { manifest.candidates[0].bodyStatus = 'pending'; }, /no readable/);
  invalid(manifest => { manifest.candidates[1].bodyStatus = 'pending'; }, /no readable/);
  invalid(manifest => { manifest.candidates[0].materialScope = 'metadata'; }, /no readable/);
  invalid(manifest => { manifest.candidates[0].contentHash = 'not-a-hash'; }, /contentHash is invalid/);
  invalid(manifest => { manifest.candidates[0].bodyChars = 0; }, /no readable/);
  invalid(manifest => { manifest.sources[0].status = 'failed'; }, /successful source/);
});

test('original collector identity and date cannot be replaced by editorial or discovery metadata', () => {
  for (const [field, value] of [['originalTitle', 'Changed original'], ['source', 'Different publisher'],
    ['sourceId', 'other'], ['url', 'https://example.org/other'], ['publishedAt', '2026-11-04'], ['contentHash', '0'.repeat(64)]]) {
    invalid((_, editorial) => { editorial.materials[0][field] = value; }, /metadata differs/);
  }
  invalid((_, editorial) => { editorial.runId = 'another-run'; }, /runId/);
  invalid((_, editorial) => { editorial.reviewedAt = '2026-11-04T09:01:00Z'; }, /predates/);
  invalid(manifest => { manifest.candidates[0].disposition = 'outside-window'; }, /recent source publication/);
  invalid(manifest => { manifest.candidates[0].publishedAt = '2026-11-05T08:00:00Z'; }, /future source publication/);
  invalid(manifest => { manifest.candidates[0].publishedAt = null; }, /source publication date/);
  invalid(manifest => { manifest.candidates[1].publishedAt = null; manifest.candidates[1].disposition = 'outside-window'; }, /source publication date/);
  invalid(manifest => { manifest.candidates[0].publishedAt = '2000-01-01T08:00:00Z'; }, /recency window/);
});

test('references require unique registered sources, original metadata and resolvable section citations', () => {
  invalid((_, editorial) => { editorial.materials[0].reading.references[0].url = 'https://unread.example.org/new'; }, /unregistered reference/);
  invalid((_, editorial) => { editorial.materials[0].reading.references[0].publishedAt = '2026-11-04'; }, /reference metadata/);
  invalid((_, editorial) => { editorial.materials[0].reading.references[0].publisher = 'Other source'; }, /reference metadata/);
  invalid((_, editorial) => { editorial.materials[0].reading.sections[0].sourceIds = ['missing']; }, /missing source/);
  invalid((_, editorial) => editorial.materials[0].reading.references.push(clone(editorial.materials[0].reading.references[0])), /duplicate id/);
  invalid((_, editorial) => editorial.materials[0].reading.references.push({ ...editorial.materials[0].reading.references[0], id: 'other' }), /URLs contains duplicates/);
  invalid((_, editorial) => editorial.materials[0].reading.sections.push(clone(editorial.materials[0].reading.sections[0])), /duplicate id/);
  invalid((_, editorial) => { editorial.materials[0].reading.references = []; }, /no references/);
});

test('excerpt scope remains explicit in material and every reference', () => {
  invalid(manifest => { manifest.candidates[0].materialScope = 'excerpt'; }, /upgrades excerpt|upgrades its collected/);
  const { manifest, editorial } = fixture();
  manifest.candidates[0].materialScope = 'excerpt'; editorial.materials[0].materialScope = 'excerpt';
  editorial.materials[0].reading.references[0].scope = 'Excerpt only; the full text was not obtained.';
  assert.throws(() => buildPublication(manifest, editorial), /upgrades excerpt/);
  editorial.materials[0].reading.references[0].scope = 'Full article; excerpt extracted from the introduction.';
  assert.throws(() => buildPublication(manifest, editorial), /upgrades excerpt/);
  editorial.materials[0].reading.references[0].scope = 'Excerpt only; the acquired passage describes the mechanism.';
  assert.equal(buildPublication(manifest, editorial).materials[0].materialScope, 'excerpt');
});

test('an extracted article body cannot be promoted to full-page or full scope', () => {
  for (const scope of ['full-page', 'full']) {
    invalid((_, editorial) => { editorial.materials[0].materialScope = scope; }, /upgrades its collected scope/);
  }
  const { manifest, editorial } = fixture();
  assert.equal(buildPublication(manifest, editorial).materials[0].materialScope, 'body');
});

test('a supplemental web-read source must be registered with the exact citation scope and review timing', () => {
  const { manifest, editorial } = fixture();
  const reference = { id: 'additional', title: 'Original technical documentation', url: 'https://docs.example.org/mechanism',
    publisher: 'Documentation publisher', publishedAt: null, scope: 'Public documentation; read the mechanism section.' };
  editorial.materials[0].reading.references.push(reference);
  editorial.materials[0].reading.sections[0].sourceIds.push(reference.id);
  editorial.supplementalSources.push({ ...reference, checkedAt: '2026-11-04T09:15:00Z', method: 'web-read', reason: 'Resolve the mechanism from original documentation.' });
  assert.equal(buildPublication(manifest, editorial).provenance.supplementalSources.length, 1);
  reference.scope = 'The entire original document.';
  assert.throws(() => buildPublication(manifest, editorial), /supplemental reference scope changed/);
  reference.scope = editorial.supplementalSources[0].scope;
  editorial.supplementalSources[0].checkedAt = '2026-11-05T09:15:00Z';
  assert.throws(() => buildPublication(manifest, editorial), /before review/);
});

test('card-only or empty reading detail does not pass structural publication checks', () => {
  invalid((_, editorial) => { editorial.materials[0].reading.lead = editorial.materials[0].summary; }, /repeats its card/);
  invalid((_, editorial) => { editorial.materials[0].reading.sections[0].paragraphs = ['An empty detail.']; }, /at least 2/);
  invalid((_, editorial) => { editorial.materials[0].reading.sections[0].paragraphs[0] = ' '; }, /nonempty/);
  invalid((_, editorial) => { editorial.materials[0].reading.sections[0].paragraphs[0] = editorial.materials[0].summary; }, /card-only/);
  invalid((_, editorial) => { editorial.materials[0].paragraphs = clone(editorial.materials[0].reading.sections[0].paragraphs); }, /duplicates card/);
  invalid((_, editorial) => { editorial.materials[0].reading.takeaways = []; }, /at least 1/);
});

test('event links and selected item identities agree in both directions', () => {
  invalid((_, editorial) => { editorial.events[0].materialIds = ['missing']; }, /cross-link/);
  invalid((_, editorial) => { editorial.materials[1].eventIds = []; }, /cross-link/);
  invalid((_, editorial) => { editorial.events[0].developments[0].materialIds = ['article']; }, /outside its event/);
  invalid((_, editorial) => { editorial.events[0].attention = 10; }, /unmeasured attention/);
  invalid((_, editorial) => editorial.selectedIds.push('failed'), /does not exist/);
  invalid((_, editorial) => editorial.selectedIds.push('support'), /selection contradicts/);
  invalid((_, editorial) => editorial.selectedIds.push('article'), /duplicates/);
  invalid((_, editorial) => editorial.materials.push(clone(editorial.materials[0])), /duplicate id/);
});

test('event developments cannot be dated after the editorial review date', () => {
  invalid((_, editorial) => { editorial.events[0].developments[0].date = '2030-01-01'; }, /development postdates editorial review/);
  invalid((_, editorial) => { editorial.events[0].developments[0].date = '2026-11-05'; }, /development postdates editorial review/);
  const { manifest, editorial } = fixture();
  assert.equal(buildPublication(manifest, editorial).events[0].developments[0].date, '2026-11-04');
});

test('pilot usage discloses zero model calls and unknown cost rather than invented free-model accounting', () => {
  invalid(manifest => { manifest.usage.modelCalls = 1; }, /no-paid-model/);
  invalid(manifest => { manifest.usage.modelCost = 0; }, /no-paid-model/);
});

test('load validates integrity and also rejects malformed references even with a recomputed hash', async context => {
  const { manifest, editorial } = fixture();
  const dir = await mkdtemp(join(tmpdir(), 'unspun-publication-load-'));
  context.after(() => rm(dir, { recursive: true, force: true }));
  const path = join(dir, 'publication.json');
  const publication = buildPublication(manifest, editorial);
  await writeFile(path, JSON.stringify(publication));
  assert.deepEqual(await loadPublication(path), publication);
  publication.materials[0].publishedAt = '2026-11-04';
  await writeFile(path, JSON.stringify(publication));
  await assert.rejects(loadPublication(path), /integrity/);
  const { publicationHash: _, ...payload } = publication;
  publication.publicationHash = hashObject(payload);
  await writeFile(path, JSON.stringify(publication));
  await assert.rejects(loadPublication(path), /metadata differs/);
});

test('load refuses local or unknown structured fields even with an otherwise valid hash', async context => {
  const { manifest, editorial } = fixture();
  const dir = await mkdtemp(join(tmpdir(), 'unspun-publication-private-'));
  context.after(() => rm(dir, { recursive: true, force: true }));
  const path = join(dir, 'publication.json');
  for (const mutate of [value => { value.bodyPath = '/private/body'; },
    value => { value.provenance.candidates[0].bodyPath = '/private/body'; },
    value => { value.provenance.usage.rawPath = '/private/body'; }]) {
    const publication = buildPublication(manifest, editorial);
    mutate(publication);
    const { publicationHash: _, ...payload } = publication;
    publication.publicationHash = hashObject(payload);
    await writeFile(path, JSON.stringify(publication));
    await assert.rejects(loadPublication(path), /unrecognized private fields/);
  }
  for (const mutate of [value => { value.materials[0].storedForm = { bodyPath: '/private/body' }; },
    value => { value.provenance.candidates[0].rawPublishedAt = { localPath: '/private/source' }; },
    value => { value.provenance.sources[0].errorType = { localPath: '/private/source' }; }]) {
    const publication = buildPublication(manifest, editorial);
    mutate(publication);
    const { publicationHash: _, ...payload } = publication;
    publication.publicationHash = hashObject(payload);
    await writeFile(path, JSON.stringify(publication));
    await assert.rejects(loadPublication(path), /must be nonempty text/);
  }
});

test('CLI verifies immutable bodies, publishes atomically, replays identical output and refuses overwrite', async context => {
  const state = await workspace(context);
  await state.run();
  const original = await readFile(state.outputPath, 'utf8');
  assert.equal((await loadPublication(state.outputPath)).edition, state.editorial.edition);
  await state.run();
  assert.equal(await readFile(state.outputPath, 'utf8'), original);
  state.editorial.label = 'A different editorial publication';
  await state.save();
  await assert.rejects(state.run(), /Refusing to overwrite/);
  assert.equal(await readFile(state.outputPath, 'utf8'), original);
  assert.deepEqual((await readdir(state.dir)).filter(name => name.endsWith('.publication.tmp')), []);
});

test('two CLI writers may only commit identical output and never replace a different edition', async context => {
  const state = await workspace(context);
  await Promise.all([state.run(), state.run()]);
  const publication = await loadPublication(state.outputPath);
  assert.equal(publication.runId, state.manifest.runId);
  assert.deepEqual((await readdir(state.dir)).filter(name => name.endsWith('.publication.tmp')), []);
});

test('CLI refuses changed body bytes and incorrect body character accounting', async context => {
  const state = await workspace(context);
  await writeFile(join(state.dir, state.manifest.candidates[0].bodyPath), 'Changed original body');
  await assert.rejects(state.run(), /body hash does not match/);
  await assert.rejects(readFile(state.outputPath), { code: 'ENOENT' });
  await writeFile(join(state.dir, state.manifest.candidates[0].bodyPath), bodies.article);
  state.manifest.candidates[0].bodyChars += 1;
  await state.save();
  await assert.rejects(state.run(), /body character count/);
});

test('CLI refuses body paths outside collector state, including symlink escapes', async context => {
  const state = await workspace(context);
  const outside = await mkdtemp(join(tmpdir(), 'unspun-publication-outside-'));
  context.after(() => rm(outside, { recursive: true, force: true }));
  await writeFile(join(outside, 'body.txt'), bodies.article);
  await symlink(outside, join(state.dir, 'external'));
  state.manifest.candidates[0].bodyPath = 'external/body.txt';
  await state.save();
  await assert.rejects(state.run(), /escapes collector state/);
  state.manifest.candidates[0].bodyPath = join(outside, 'body.txt');
  await state.save();
  await assert.rejects(state.run(), /relative bodyPath/);
});
