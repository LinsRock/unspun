import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import test from 'node:test';
import { createHash } from 'node:crypto';
import {
  EMPTY_REVIEW, canonicalCandidate, entryFor, entryPublication, exportFeedback,
  feedEntries, freshFeedback, hasReview, publicationKey, publicationLabel, restoreFeedback,
} from './model.mjs';

const raw = readFileSync(new URL('../../research/r0-2026-10-15/candidates.json', import.meta.url));
const dataset = JSON.parse(raw);
const fingerprint = createHash('sha256').update(raw).digest('hex');
const manifest = JSON.parse(readFileSync(new URL('./manifest.json', import.meta.url)));
const byId = Object.fromEntries(dataset.candidates.map(candidate => [candidate.id, candidate]));
const ids = Object.keys(byId);
const topics = manifest.topics.map(topic => topic.id);

test('the original 43 human labels remain empty; a layout never becomes human approval', () => {
  assert.equal(ids.length, 43);
  assert.ok(dataset.candidates.every(candidate => Object.values(candidate.human_review).every(value => value === null)));
  const feedback = freshFeedback(fingerprint);
  const exported = exportFeedback(feedback, dataset.candidates, manifest, 'early');
  assert.equal(exported.reviewed_content_count, 0);
  assert.ok(exported.candidates.every(candidate => !hasReview(candidate.human_review)));
  assert.equal(createHash('sha256').update(raw).digest('hex'), fingerprint);
});

test('late discovery, feed modification, reprint and question times do not become first publication', () => {
  assert.equal(publicationLabel(byId.C35, true), '2026-10-15 04:17');
  assert.equal(publicationKey(byId.C35).time, Date.parse(byId.C35.publication.value));
  assert.equal(canonicalCandidate(byId.C41, byId).id, 'C21');
  assert.equal(entryPublication(entryFor('C41', byId, manifest), byId).time, Date.parse(byId.C21.publication.value));
  assert.match(publicationLabel(byId.C41), /^本页转载 /);
  assert.match(publicationLabel(byId.C24), /^日报选编 /);
  assert.match(publicationLabel(byId.C28), /^问题创建 /);
  assert.equal(publicationKey(byId.C12).time, null);
  assert.match(publicationLabel(byId.C12), /仅日期$/);
});

test('latest uses publication day and precision, keeps knowledge old and omits old-news controls', () => {
  const entries = feedEntries(byId, manifest, { sort: 'latest' });
  const keys = entries.map(entry => entryPublication(entry, byId));
  for (let index = 1; index < keys.length; index++) {
    const previous = keys[index - 1];
    const current = keys[index];
    assert.ok(previous.day >= current.day);
    if (previous.day === current.day && previous.time === null) assert.equal(current.time, null);
    if (previous.day === current.day && previous.time !== null && current.time !== null) assert.ok(previous.time >= current.time);
  }
  assert.equal(entries.at(-1).id, 'C29');
  assert.ok(!entries.some(entry => ['C11', 'C19', 'C41'].includes(entry.id)));
  assert.equal(canonicalCandidate(byId.C42, byId).id, 'C42');
});

test('version replay changes only indexed market materials and does not invent a new article or score', () => {
  const early = entryFor('market', byId, manifest, 'early');
  const updated = entryFor('market', byId, manifest, 'updated');
  assert.deepEqual(early.members.map(candidate => candidate.id), ['C01', 'C28']);
  assert.deepEqual(updated.members.map(candidate => candidate.id), ['C01', 'C05', 'C28']);
  assert.equal(entryPublication(early, byId).time, Date.parse(byId.C01.publication.value));
  assert.equal(entryPublication(updated, byId).time, Date.parse(byId.C05.publication.value));
  assert.ok(!updated.members.some(candidate => 'score' in candidate));
});

test('category filtering includes topic matches and returns a recoverable empty result', () => {
  const entries = feedEntries(byId, manifest, { category: '知识与文化' });
  assert.ok(entries.some(entry => entry.id === 'C24'));
  assert.ok(entries.every(entry => entry.kind === 'content' && manifest.categories['知识与文化'].includes(entry.id)));
  assert.deepEqual(feedEntries(byId, manifest, { category: 'missing' }), []);
});

test('feedback restores only the matching dataset and valid explicit dimensions', () => {
  const value = freshFeedback(fingerprint);
  value.contents.C14 = { ...EMPTY_REVIEW, interest: 'yes', importance_1_to_5: 3 };
  value.contents.C07 = { interest_1_to_5: 7, worth_reading_now: 'maybe' };
  value.contents.C99 = { interest: 'yes' };
  value.topics.market = { interest: 'no' };
  value.experience.selection_limit = 4;
  value.experience.other = 'ignore';
  const restored = restoreFeedback(JSON.stringify(value), fingerprint, ids, topics);
  assert.equal(restored.contents.C14.importance_1_to_5, 3);
  assert.equal(restored.contents.C14.interest_1_to_5, null);
  assert.equal(restored.contents.C14.worth_reading_now, null);
  assert.equal(restored.contents.C07, undefined);
  assert.equal(restored.contents.C99, undefined);
  assert.equal(restored.topics.market.interest, 'no');
  assert.equal(restored.experience.selection_limit, 4);
  assert.equal(restored.experience.other, undefined);
  for (const rawValue of ['null', '{', '[]', JSON.stringify({ ...value, dataset_sha256: 'different' })]) {
    assert.deepEqual(restoreFeedback(rawValue, fingerprint, ids, topics), freshFeedback(fingerprint));
  }
});

test('export retains unknowns, exact original provenance, separate topic and experience feedback', () => {
  const value = freshFeedback(fingerprint);
  value.contents.C07 = { ...EMPTY_REVIEW, place: 'defer', reason: 'Only a preview.' };
  value.topics.market = { ...EMPTY_REVIEW, worth_reading_now: 'yes' };
  value.experience.missing = 'Community answers';
  const result = exportFeedback(value, dataset.candidates, manifest, 'updated');
  assert.equal(result.reviewed_content_count, 1);
  assert.equal(result.topics.market.worth_reading_now, 'yes');
  assert.equal(result.experience.missing, 'Community answers');
  assert.equal(result.dataset_sha256, fingerprint);
  assert.deepEqual(result.candidates.find(candidate => candidate.id === 'C07').publication, byId.C07.publication);
  assert.equal(result.candidates.find(candidate => candidate.id === 'C07').human_review.importance_1_to_5, null);
  assert.equal(result.candidates.find(candidate => candidate.id === 'C14').human_review.worth_reading_now, null);
  assert.equal(byId.C07.human_review.place, null);
});

test('every displayed local paragraph belongs to the fingerprinted source unit', {
  skip: !existsSync(new URL('./materials.local.json', import.meta.url)),
}, () => {
  const pack = JSON.parse(readFileSync(new URL('./materials.local.json', import.meta.url)));
  assert.equal(pack.dataset_sha256, fingerprint);
  assert.equal(Object.keys(pack.materials).length, 39);
  for (const [id, material] of Object.entries(pack.materials)) {
    assert.equal(createHash('sha256').update(material.text).digest('hex'), byId[id].material_sha256);
    assert.equal(material.paragraphs.join('').replace(/\s+/g, ''), material.text.replace(/\s+/g, ''));
    assert.equal(material.material_status, byId[id].material_status);
  }
});
