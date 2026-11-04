import { createHash, randomUUID } from 'node:crypto';
import { readFile, mkdir, open, link, unlink, realpath } from 'node:fs/promises';
import { dirname, isAbsolute, join, resolve, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const hashPattern = /^[a-f0-9]{64}$/;
const scopes = new Set(['body', 'excerpt', 'partial', 'metadata']);
const acceptedDecisions = new Set(['selected', 'supporting']);
const pick = (value, keys) => Object.fromEntries(keys.filter(key => value[key] !== undefined).map(key => [key, value[key]]));
const canonical = value => JSON.stringify(value, (_, item) => item && typeof item === 'object' && !Array.isArray(item)
  ? Object.fromEntries(Object.keys(item).sort().map(key => [key, item[key]])) : item);
const digest = value => createHash('sha256').update(canonical(value)).digest('hex');
const fail = message => { throw new Error(`Invalid publication: ${message}`); };
const object = (value, name) => { if (!value || typeof value !== 'object' || Array.isArray(value)) fail(`${name} must be an object`); };
const text = (value, name) => { if (typeof value !== 'string' || !value.trim()) fail(`${name} must be nonempty text`); };
const optionalText = (value, name) => { if (value !== null && value !== undefined) text(value, name); };
const nonnegative = (value, name) => { if (!Number.isInteger(value) || value < 0) fail(`${name} must be a nonnegative integer`); };
const array = (value, name) => { if (!Array.isArray(value)) fail(`${name} must be an array`); };
const unique = (values, name) => { if (new Set(values).size !== values.length) fail(`${name} contains duplicates`); };
const timestamp = (value, name) => {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)
      || !Number.isFinite(Date.parse(value))) fail(`${name} must be an ISO timestamp`);
  date(value.slice(0, 10), name);
};
const date = (value, name) => {
  if (value === null) return;
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value) || !Number.isFinite(Date.parse(`${value}T00:00:00Z`))
      || new Date(`${value}T00:00:00Z`).toISOString().slice(0, 10) !== value) fail(`${name} must be an original date or null`);
};
const url = (value, name) => {
  try { const parsed = new URL(value); if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password) throw new Error(); }
  catch { fail(`${name} must be a public HTTP URL`); }
};
const strings = (value, name, minimum = 0) => {
  array(value, name);
  if (value.length < minimum) fail(`${name} needs at least ${minimum} entries`);
  value.forEach(item => text(item, name));
  unique(value, name);
};
const keyed = (values, name) => {
  array(values, name);
  const result = new Map();
  for (const item of values) {
    object(item, name); text(item.id, `${name}.id`);
    if (result.has(item.id)) fail(`${name} contains duplicate id ${item.id}`);
    result.set(item.id, item);
  }
  return result;
};

function publicCandidate(candidate) {
  return pick(candidate, ['id', 'sourceId', 'sourceName', 'domain', 'url', 'title', 'author', 'publishedAt',
    'rawPublishedAt', 'discoveredAt', 'disposition', 'bodyStatus', 'contentHash', 'materialScope', 'bodyChars', 'dateIssue', 'bodyFetchedAt']);
}

function publicSource(source) {
  const result = pick(source, ['phaseId', 'sourceId', 'sourceName', 'url', 'attemptedAt', 'completedAt', 'requestedUrl',
    'finalUrl', 'httpStatus', 'downloadedBytes', 'contentType', 'status', 'errorType', 'candidateCount']);
  if (source.redirects) result.redirects = source.redirects.map(item => pick(item, ['from', 'to', 'status']));
  if (source.rejectedEntries) result.rejectedEntries = source.rejectedEntries.map(item => pick(item, ['url', 'reason']));
  return result;
}

function publicPhase(phase) {
  return pick(phase, ['id', 'kind', 'startedAt', 'completedAt', 'status', 'windowDays', 'sourceAttempts', 'candidateCount']);
}

function publicReading(reading) {
  if (!reading) return reading;
  object(reading, 'reading'); array(reading.sections, 'reading.sections'); array(reading.references, 'reading.references');
  return { ...pick(reading, ['lead', 'takeaways']),
    sections: reading.sections.map(section => pick(section, ['id', 'title', 'paragraphs', 'sourceIds'])),
    references: reading.references.map(reference => pick(reference, ['id', 'title', 'url', 'publisher', 'publishedAt', 'scope'])) };
}

function publicMaterial(material) {
  const result = pick(material, ['id', 'type', 'domain', 'title', 'originalTitle', 'source', 'sourceId', 'author',
    'publishedAt', 'url', 'materialScope', 'summary', 'whyRead', 'paragraphs', 'eventIds', 'role', 'selected',
    'selectionReason', 'storedForm', 'contentHash']);
  if (material.verification) result.verification = pick(material.verification, ['checkedAt', 'method', 'note']);
  if (material.reading) result.reading = publicReading(material.reading);
  return result;
}

function publicEvent(event) {
  const result = pick(event, ['id', 'domain', 'title', 'summary', 'whyRead', 'paragraphs', 'materialIds', 'selected', 'attention']);
  if (event.developments) result.developments = event.developments.map(item => pick(item, ['date', 'title', 'description', 'materialIds']));
  if (event.reading) result.reading = publicReading(event.reading);
  return result;
}

function validateCandidate(candidate) {
  for (const field of ['id', 'sourceId', 'sourceName', 'domain', 'title']) text(candidate[field], `candidate.${field}`);
  url(candidate.url, 'candidate.url'); timestamp(candidate.discoveredAt, 'candidate.discoveredAt');
  if (candidate.publishedAt !== null) timestamp(candidate.publishedAt, 'candidate.publishedAt');
  if (!['recent', 'outside-window', 'unknown-date'].includes(candidate.disposition)) fail('candidate.disposition is unknown');
  if (!['pending', 'readable', 'failed'].includes(candidate.bodyStatus)) fail('candidate.bodyStatus is unknown');
  if (!['body', 'excerpt', 'metadata'].includes(candidate.materialScope)) fail('candidate.materialScope is unknown');
  if (candidate.disposition !== 'unknown-date' && candidate.publishedAt === null) fail('candidate has no source publication date');
  for (const field of ['author', 'rawPublishedAt', 'dateIssue']) optionalText(candidate[field], `candidate.${field}`);
  if (candidate.bodyFetchedAt !== undefined) timestamp(candidate.bodyFetchedAt, 'candidate.bodyFetchedAt');
  if (candidate.contentHash !== null && !hashPattern.test(candidate.contentHash)) fail('candidate.contentHash is invalid');
  nonnegative(candidate.bodyChars, 'candidate.bodyChars');
}

function requireReadable(candidate, decision, reviewedAt) {
  if (!acceptedDecisions.has(decision?.decision)) fail(`candidate ${candidate.id} lacks an approved editorial decision`);
  if (candidate.bodyStatus !== 'readable' || candidate.materialScope === 'metadata' || !hashPattern.test(candidate.contentHash)
      || !Number.isInteger(candidate.bodyChars) || candidate.bodyChars <= 0) fail(`candidate ${candidate.id} has no readable, hashed body`);
  if (candidate.publishedAt && (Date.parse(candidate.publishedAt) > Date.parse(candidate.discoveredAt)
      || Date.parse(candidate.publishedAt) > Date.parse(reviewedAt))) fail(`candidate ${candidate.id} has a future source publication date`);
}

function validateScope(scope, candidate) {
  text(scope, 'reference.scope');
  if (candidate.materialScope === 'excerpt' && (!/(excerpt|partial|摘要|节选|摘录|部分)/i.test(scope)
      || /((full|complete|entire)[- ]?(page|text|body|article|content)|全文|完整(正文|文章|内容)|全部(正文|文章|内容))/i.test(scope))) fail(`reference upgrades excerpt scope for ${candidate.id}`);
}

function validateReading(item, candidatesByUrl, decisions, supplementals, reviewedAt) {
  const reading = item.reading;
  object(reading, `${item.id}.reading`); text(reading.lead, 'reading.lead');
  if (reading.lead.trim() === item.summary.trim()) fail(`${item.id} reading repeats its card summary`);
  strings(reading.takeaways, 'reading.takeaways', 1);
  const references = keyed(reading.references, 'reading.references');
  if (!references.size) fail(`${item.id} has no references`);
  unique(reading.references.map(reference => reference.url), 'reading reference URLs');
  for (const reference of references.values()) {
    for (const field of ['title', 'publisher', 'scope']) text(reference[field], `reference.${field}`);
    url(reference.url, 'reference.url'); date(reference.publishedAt, 'reference.publishedAt');
    const candidate = candidatesByUrl.get(reference.url);
    if (candidate) {
      requireReadable(candidate, decisions.get(candidate.id), reviewedAt);
      if (reference.publisher !== candidate.sourceName || reference.publishedAt !== (candidate.publishedAt?.slice(0, 10) ?? null)) fail(`reference metadata differs from candidate ${candidate.id}`);
      validateScope(reference.scope, candidate);
    } else {
      const supplemental = supplementals.get(reference.url);
      if (!supplemental) fail(`unregistered reference URL ${reference.url}`);
      for (const field of ['title', 'publisher', 'publishedAt', 'scope']) if (reference[field] !== supplemental[field]) fail(`supplemental reference ${field} changed`);
    }
  }
  const sections = keyed(reading.sections, 'reading.sections');
  if (!sections.size) fail(`${item.id} has no reading sections`);
  const paragraphs = [];
  const usedReferences = new Set();
  for (const section of sections.values()) {
    text(section.title, 'section.title'); strings(section.paragraphs, 'section.paragraphs', 2);
    strings(section.sourceIds, 'section.sourceIds', 1);
    for (const id of section.sourceIds) {
      if (!references.has(id)) fail(`section references missing source ${id}`);
      usedReferences.add(id);
    }
    for (const paragraph of section.paragraphs) {
      if (paragraph.replace(/\s/g, '').length < 12 || paragraph.trim() === item.summary.trim()
          || paragraph.trim() === section.title.trim()) fail(`${item.id} has empty or card-only detail`);
      paragraphs.push(paragraph.trim());
    }
  }
  unique(paragraphs, 'reading paragraphs');
  if (paragraphs.every(paragraph => item.paragraphs?.some(card => card.trim() === paragraph))) fail(`${item.id} detail only duplicates card paragraphs`);
  if (usedReferences.size !== references.size) fail(`${item.id} has unused references`);
}

function validateProjection(publication) {
  object(publication, 'publication');
  if (publication.schemaVersion !== 1) fail('unsupported schemaVersion');
  for (const field of ['edition', 'label', 'runId']) text(publication[field], field);
  if (!/^[a-zA-Z0-9][a-zA-Z0-9_-]*$/.test(publication.edition)) fail('edition must be a safe identifier');
  for (const field of ['manifestHash', 'editorialHash']) if (!hashPattern.test(publication[field])) fail(`${field} is invalid`);
  timestamp(publication.publishedAt, 'publishedAt');
  object(publication.provenance, 'provenance');
  const { processing, usage } = publication.provenance;
  object(processing, 'processing'); object(usage, 'usage');
  if (processing.method !== 'assistant-editorial') fail('processing method must disclose assistant-editorial');
  timestamp(processing.startedAt, 'processing.startedAt'); timestamp(processing.reviewedAt, 'processing.reviewedAt');
  if (Date.parse(processing.startedAt) > Date.parse(processing.reviewedAt) || processing.reviewedAt !== publication.publishedAt) fail('processing dates are inconsistent');
  if (usage.modelCalls !== 0 || usage.modelCost !== null || !Number.isInteger(usage.requestCount) || usage.requestCount < 0
      || !Number.isFinite(usage.elapsedMs) || usage.elapsedMs < 0) fail('usage must preserve the no-paid-model pilot boundary');
  if (usage.bytesDownloaded !== undefined) nonnegative(usage.bytesDownloaded, 'usage.bytesDownloaded');
  const phases = keyed(publication.provenance.phases, 'provenance.phases');
  if (!phases.size) fail('collection phases are required');
  for (const phase of phases.values()) {
    if (!['collect', 'hydrate'].includes(phase.kind) || !['completed', 'failed'].includes(phase.status)) fail('collection phase must have finished');
    timestamp(phase.startedAt, 'phase.startedAt'); timestamp(phase.completedAt, 'phase.completedAt');
    if (Date.parse(phase.startedAt) > Date.parse(phase.completedAt) || Date.parse(phase.completedAt) > Date.parse(processing.reviewedAt)) fail('collection phase dates are inconsistent');
    if (phase.kind === 'collect' && (!Number.isInteger(phase.windowDays) || phase.windowDays < 1 || phase.windowDays > 90)) fail('collection phase has no bounded windowDays');
    for (const field of ['sourceAttempts', 'candidateCount']) if (phase[field] !== undefined) nonnegative(phase[field], `phase.${field}`);
  }
  array(publication.provenance.sources, 'provenance.sources');
  for (const source of publication.provenance.sources) {
    object(source, 'source'); text(source.sourceId, 'source.sourceId'); text(source.sourceName, 'source.sourceName');
    url(source.url, 'source.url');
    if (!['ok', 'failed'].includes(source.status)) fail('source.status is unknown');
    if (phases.get(source.phaseId)?.kind !== 'collect') fail('source attempt has no collection phase');
    for (const field of ['contentType', 'errorType']) optionalText(source[field], `source.${field}`);
    for (const field of ['requestedUrl', 'finalUrl']) if (source[field] !== undefined && source[field] !== null) url(source[field], `source.${field}`);
    for (const field of ['attemptedAt', 'completedAt']) if (source[field] !== undefined) timestamp(source[field], `source.${field}`);
    for (const field of ['downloadedBytes', 'candidateCount']) if (source[field] !== undefined) nonnegative(source[field], `source.${field}`);
    if (source.httpStatus !== null && source.httpStatus !== undefined && (!Number.isInteger(source.httpStatus) || source.httpStatus < 100 || source.httpStatus > 599)) fail('source.httpStatus is invalid');
    if (source.redirects !== undefined) {
      array(source.redirects, 'source.redirects');
      for (const redirect of source.redirects) {
        url(redirect.from, 'redirect.from'); url(redirect.to, 'redirect.to');
        if (!Number.isInteger(redirect.status) || redirect.status < 300 || redirect.status > 399) fail('redirect.status is invalid');
      }
    }
    if (source.rejectedEntries !== undefined) {
      array(source.rejectedEntries, 'source.rejectedEntries');
      for (const entry of source.rejectedEntries) { optionalText(entry.url, 'rejectedEntry.url'); text(entry.reason, 'rejectedEntry.reason'); }
    }
  }
  const candidates = keyed(publication.provenance.candidates, 'provenance.candidates');
  const candidatesByUrl = new Map();
  for (const candidate of candidates.values()) {
    validateCandidate(candidate);
    if (candidatesByUrl.has(candidate.url)) fail('candidate URLs contain duplicates');
    candidatesByUrl.set(candidate.url, candidate);
    if (!publication.provenance.sources.some(source => source.sourceId === candidate.sourceId && source.sourceName === candidate.sourceName && source.status === 'ok')) fail(`candidate ${candidate.id} lacks a successful source attempt`);
  }
  array(publication.provenance.decisions, 'provenance.decisions');
  const decisions = new Map();
  for (const decision of publication.provenance.decisions) {
    object(decision, 'decision'); text(decision.reason, 'decision.reason');
    if (decision.reason.trim().length < 8) fail('decision reason must explain the actual editorial judgment');
    const candidate = candidates.get(decision.candidateId);
    if (!candidate || decisions.has(decision.candidateId)) fail('decisions must identify each candidate exactly once');
    if (!['selected', 'supporting', 'rejected', 'deferred'].includes(decision.decision)) fail('unknown editorial decision');
    if ((candidate.bodyStatus === 'failed' || candidate.disposition === 'unknown-date') && decision.decision !== 'deferred') fail(`failed or unknown candidate ${candidate.id} must be deferred`);
    if (acceptedDecisions.has(decision.decision)) requireReadable(candidate, decision, processing.reviewedAt);
    if (decision.decision === 'selected' && (candidate.disposition !== 'recent' || !candidate.publishedAt)) fail(`selected candidate ${candidate.id} needs a recent source publication date`);
    if (decision.decision === 'selected') {
      const source = publication.provenance.sources.findLast(item => item.sourceId === candidate.sourceId && item.status === 'ok');
      const windowDays = phases.get(source.phaseId).windowDays;
      if (Date.parse(processing.reviewedAt) - Date.parse(candidate.publishedAt) > windowDays * 86_400_000) fail(`selected candidate ${candidate.id} is outside the collection recency window`);
    }
    decisions.set(decision.candidateId, decision);
  }
  if (decisions.size !== candidates.size) fail('every candidate needs exactly one editorial decision');
  const supplementals = new Map();
  array(publication.provenance.supplementalSources, 'supplementalSources');
  for (const source of publication.provenance.supplementalSources) {
    object(source, 'supplemental source'); url(source.url, 'supplemental.url');
    for (const field of ['title', 'publisher', 'scope', 'reason']) text(source[field], `supplemental.${field}`);
    date(source.publishedAt, 'supplemental.publishedAt'); timestamp(source.checkedAt, 'supplemental.checkedAt');
    if (source.method !== 'web-read' || Date.parse(source.checkedAt) > Date.parse(processing.reviewedAt)) fail('supplemental source must have been read before review');
    if (supplementals.has(source.url) || candidatesByUrl.has(source.url)) fail('duplicate supplemental URL');
    supplementals.set(source.url, source);
  }
  const materials = keyed(publication.materials, 'materials');
  const events = keyed(publication.events, 'events');
  object(publication.curation, 'curation'); strings(publication.curation.selectedIds, 'curation.selectedIds', 1);
  if (publication.curation.edition !== publication.edition) fail('curation edition differs');
  const selected = new Set(publication.curation.selectedIds);
  for (const id of selected) if (!materials.has(id) && !events.has(id)) fail(`selected id ${id} does not exist`);
  for (const material of materials.values()) {
    const candidate = candidates.get(material.id);
    if (!candidate || events.has(material.id)) fail(`material ${material.id} has no unique candidate identity`);
    requireReadable(candidate, decisions.get(material.id), processing.reviewedAt);
    for (const field of ['domain', 'title', 'source', 'originalTitle', 'summary', 'whyRead', 'role', 'selectionReason']) text(material[field], `material.${field}`);
    if (material.type !== 'article' || material.role === 'duplicate') fail('only distinct articles can be published');
    optionalText(material.author, 'material.author'); optionalText(material.storedForm, 'material.storedForm');
    if (material.url !== candidate.url || material.originalTitle !== candidate.title || material.source !== candidate.sourceName
        || material.publishedAt !== (candidate.publishedAt?.slice(0, 10) ?? null) || (material.sourceId !== undefined && material.sourceId !== candidate.sourceId)
        || (material.contentHash !== undefined && material.contentHash !== candidate.contentHash)) fail(`material ${material.id} metadata differs from collector`);
    if (!scopes.has(material.materialScope) || material.materialScope === 'metadata'
        || (candidate.materialScope === 'excerpt' && !['excerpt', 'partial'].includes(material.materialScope))) fail(`material ${material.id} upgrades its collected scope`);
    if (material.selected !== selected.has(material.id) || material.selected !== (decisions.get(material.id).decision === 'selected')) fail(`material ${material.id} selection contradicts editorial decision`);
    strings(material.paragraphs, 'material.paragraphs', 1); strings(material.eventIds, 'material.eventIds');
    object(material.verification, 'material.verification');
    for (const field of ['checkedAt', 'method', 'note']) text(material.verification[field], `verification.${field}`);
    if (material.verification.checkedAt.includes('T')) timestamp(material.verification.checkedAt, 'verification.checkedAt');
    else date(material.verification.checkedAt, 'verification.checkedAt');
    if (Date.parse(material.verification.checkedAt) > Date.parse(processing.reviewedAt)) fail('material verification postdates editorial review');
    for (const eventId of material.eventIds) if (!events.get(eventId)?.materialIds.includes(material.id)) fail('material/event cross-link is inconsistent');
    if (material.selected || material.reading) validateReading(material, candidatesByUrl, decisions, supplementals, processing.reviewedAt);
  }
  for (const [id, decision] of decisions) if (decision.decision === 'selected' && !materials.has(id)) fail(`selected candidate ${id} has no published article`);
  for (const event of events.values()) {
    for (const field of ['domain', 'title', 'summary', 'whyRead']) text(event[field], `event.${field}`);
    if (event.selected !== selected.has(event.id) || event.attention !== null) fail('event selection or unmeasured attention is inconsistent');
    strings(event.paragraphs, 'event.paragraphs', 1); strings(event.materialIds, 'event.materialIds', 1);
    for (const id of event.materialIds) if (!materials.get(id)?.eventIds.includes(event.id)) fail('event/material cross-link is inconsistent');
    array(event.developments, 'event.developments');
    if (!event.developments.length) fail('event needs evidenced developments');
    for (const development of event.developments) {
      date(development.date, 'development.date'); text(development.title, 'development.title'); text(development.description, 'development.description');
      if (development.date && development.date > processing.reviewedAt.slice(0, 10)) fail('event development postdates editorial review');
      strings(development.materialIds, 'development.materialIds', 1);
      if (development.materialIds.some(id => !event.materialIds.includes(id))) fail('development uses material outside its event');
    }
    if (event.selected || event.reading) validateReading(event, candidatesByUrl, decisions, supplementals, processing.reviewedAt);
  }
  return publication;
}

export function buildPublication(manifest, editorial) {
  object(manifest, 'manifest'); object(editorial, 'editorial');
  if (manifest.schemaVersion !== 1 || editorial.schemaVersion !== 1) fail('unsupported input schemaVersion');
  text(manifest.runId, 'manifest.runId');
  if (editorial.runId !== manifest.runId) fail('editorial runId does not match manifest');
  timestamp(manifest.startedAt, 'manifest.startedAt'); timestamp(manifest.updatedAt, 'manifest.updatedAt');
  timestamp(editorial.reviewedAt, 'editorial.reviewedAt');
  if (Date.parse(editorial.reviewedAt) < Date.parse(manifest.updatedAt)) fail('editorial review predates the current manifest');
  if (editorial.manifestHash !== undefined && editorial.manifestHash !== digest(manifest)) fail('editorial manifestHash differs');
  array(manifest.candidates, 'manifest.candidates'); array(manifest.sources, 'manifest.sources'); array(manifest.phases, 'manifest.phases');
  array(editorial.materials, 'editorial.materials'); array(editorial.events, 'editorial.events');
  array(editorial.decisions, 'editorial.decisions'); array(editorial.supplementalSources, 'editorial.supplementalSources');
  const publication = {
    schemaVersion: 1, edition: editorial.edition, label: editorial.label, runId: manifest.runId,
    publishedAt: editorial.reviewedAt, manifestHash: digest(manifest), editorialHash: digest(editorial),
    materials: editorial.materials.map(publicMaterial), events: editorial.events.map(publicEvent),
    curation: { edition: editorial.edition, selectedIds: editorial.selectedIds },
    provenance: {
      sources: manifest.sources.map(publicSource), candidates: manifest.candidates.map(publicCandidate), phases: manifest.phases.map(publicPhase),
      decisions: editorial.decisions.map(item => pick(item, ['candidateId', 'decision', 'reason'])),
      usage: pick(manifest.usage, ['requestCount', 'bytesDownloaded', 'elapsedMs', 'modelCalls', 'modelCost']),
      processing: pick(editorial, ['method', 'startedAt', 'reviewedAt']),
      supplementalSources: editorial.supplementalSources.map(item => pick(item, ['url', 'title', 'publisher', 'publishedAt', 'scope', 'checkedAt', 'method', 'reason'])),
    },
  };
  validateProjection(publication);
  return JSON.parse(JSON.stringify({ ...publication, publicationHash: digest(publication) }));
}

export async function loadPublication(path) {
  const publication = JSON.parse(await readFile(path, 'utf8'));
  object(publication, 'publication');
  const { publicationHash, ...payload } = publication;
  if (!hashPattern.test(publicationHash) || digest(payload) !== publicationHash) fail('publicationHash integrity check failed');
  validateProjection(publication);
  const projected = { ...pick(publication, ['schemaVersion', 'edition', 'label', 'runId', 'publishedAt', 'manifestHash', 'editorialHash', 'publicationHash']),
    materials: publication.materials.map(publicMaterial), events: publication.events.map(publicEvent),
    curation: pick(publication.curation, ['edition', 'selectedIds']),
    provenance: { sources: publication.provenance.sources.map(publicSource), candidates: publication.provenance.candidates.map(publicCandidate), phases: publication.provenance.phases.map(publicPhase),
      decisions: publication.provenance.decisions.map(item => pick(item, ['candidateId', 'decision', 'reason'])),
      usage: pick(publication.provenance.usage, ['requestCount', 'bytesDownloaded', 'elapsedMs', 'modelCalls', 'modelCost']),
      processing: pick(publication.provenance.processing, ['method', 'startedAt', 'reviewedAt']),
      supplementalSources: publication.provenance.supplementalSources.map(item => pick(item, ['url', 'title', 'publisher', 'publishedAt', 'scope', 'checkedAt', 'method', 'reason'])),
    } };
  if (canonical(projected) !== canonical(publication)) fail('publication contains unrecognized private fields');
  return publication;
}

async function publishFile(publication, output) {
  await mkdir(dirname(output), { recursive: true });
  const temporary = join(dirname(output), `.${randomUUID()}.publication.tmp`);
  try {
    const file = await open(temporary, 'wx', 0o600);
    try { await file.writeFile(`${JSON.stringify(publication, null, 2)}\n`); await file.sync(); }
    finally { await file.close(); }
    try { await link(temporary, output); }
    catch (error) {
      if (error.code !== 'EEXIST') throw error;
      const existing = await loadPublication(output);
      if (existing.publicationHash !== publication.publicationHash) throw new Error('Refusing to overwrite a different existing publication');
    }
  } finally { await unlink(temporary).catch(error => { if (error.code !== 'ENOENT') throw error; }); }
}

async function main(args) {
  const options = new Map();
  for (let index = 0; index < args.length; index += 2) {
    if (!['--manifest', '--editorial', '--output'].includes(args[index]) || options.has(args[index]) || !args[index + 1] || !isAbsolute(args[index + 1])) throw new Error('Use --manifest ABS_PATH --editorial ABS_PATH --output ABS_PATH');
    options.set(args[index], args[index + 1]);
  }
  if (options.size !== 3) throw new Error('Use --manifest ABS_PATH --editorial ABS_PATH --output ABS_PATH');
  const manifest = JSON.parse(await readFile(options.get('--manifest'), 'utf8'));
  const editorial = JSON.parse(await readFile(options.get('--editorial'), 'utf8'));
  const publication = buildPublication(manifest, editorial);
  const approved = new Set(editorial.decisions.filter(item => acceptedDecisions.has(item.decision)).map(item => item.candidateId));
  const stateDir = await realpath(resolve(dirname(options.get('--manifest')), '../..'));
  for (const candidate of manifest.candidates.filter(item => approved.has(item.id))) {
    if (typeof candidate.bodyPath !== 'string' || isAbsolute(candidate.bodyPath)) fail(`candidate ${candidate.id} has no relative bodyPath`);
    const bodyPath = resolve(stateDir, candidate.bodyPath);
    if (relative(stateDir, bodyPath).startsWith('..')) fail('bodyPath escapes collector state directory');
    const realBodyPath = await realpath(bodyPath);
    if (relative(stateDir, realBodyPath).startsWith('..')) fail('bodyPath escapes collector state directory');
    const body = await readFile(realBodyPath);
    if (createHash('sha256').update(body).digest('hex') !== candidate.contentHash) fail(`candidate ${candidate.id} body hash does not match`);
    if ([...body.toString('utf8')].length !== candidate.bodyChars) fail(`candidate ${candidate.id} body character count does not match`);
  }
  await publishFile(publication, options.get('--output'));
  console.log(JSON.stringify({ output: options.get('--output'), edition: publication.edition, publicationHash: publication.publicationHash }));
}

if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  main(process.argv.slice(2)).catch(error => { console.error(error.message); process.exitCode = 1; });
}
