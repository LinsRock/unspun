import { createHash } from 'node:crypto';

export function createCatalog(materials, events, curation = null) {
  const edition = curation?.edition || 'v1';
  if (curation) {
    const current = new Set(curation.selectedIds);
    materials = materials.map(item => ({ ...item, selected: current.has(item.id), previouslySelected: item.selected }));
    events = events.map(item => ({ ...item, selected: current.has(item.id) }));
  }
  const revision = createHash('sha256').update(JSON.stringify([materials, events, curation])).digest('hex').slice(0, 12);
  const eligible = materials.filter(item => item.selected && item.role !== 'duplicate');
  const articles = [...eligible.filter(item => item.eventIds.length === 0), ...eligible.filter(item => item.eventIds.length > 0)];
  const selectedEvents = events.filter(item => item.selected);
  const selections = [];
  for (let index = 0; index < Math.max(articles.length, selectedEvents.length); index++) {
    if (selectedEvents[index]) selections.push({ ...selectedEvents[index], type: 'event' });
    if (articles[index]) selections.push(articles[index]);
  }
  if (curation) selections.sort((a, b) => curation.selectedIds.indexOf(a.id) - curation.selectedIds.indexOf(b.id));
  return { revision, edition, materials, events, selections, mode: 'dated-reading-sample',
    counts: { all: selections.length, event: selectedEvents.length, article: articles.length },
    hasVideo: false };
}

export function getFeed(catalog, type = 'all', cursor = '', limit = 8) {
  if (!['all', 'event', 'article'].includes(type)) throw new Error('Invalid content type');
  let offset = 0;
  if (cursor) {
    let parsed;
    try { parsed = JSON.parse(Buffer.from(cursor, 'base64url').toString()); }
    catch { throw new Error('Invalid cursor'); }
    if (parsed.type !== type || parsed.revision !== catalog.revision ||
        !Number.isInteger(parsed.offset) || parsed.offset < 0) throw new Error('Stale or incompatible cursor');
    offset = parsed.offset;
  }
  const items = catalog.selections.filter(item => type === 'all' || item.type === type);
  if (offset > items.length) throw new Error('Invalid cursor offset');
  const nextOffset = offset + limit;
  return { items: items.slice(offset, nextOffset), total: items.length,
    nextCursor: nextOffset < items.length ? Buffer.from(JSON.stringify({ type, revision: catalog.revision, offset: nextOffset })).toString('base64url') : null };
}

export function getHot(catalog) {
  return { status: 'attention-unmeasured', ranked: false,
    items: catalog.events.filter(item => item.selected).map(item => ({ ...item, type: 'event', attention: null })) };
}
