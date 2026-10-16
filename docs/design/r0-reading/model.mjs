export const REVIEW_SCHEMA = 'unspun-r0-reading-feedback-v1';
export const MATERIAL_LABELS = {
  open_article_text: '开放正文', daily_edited_text: '日报编辑版', brief_text: '完整短讯',
  partial_preview: '部分预览', question_context_only: '仅问题描述',
  video_description_only: '仅视频简介', podcast_description_only: '仅播客简介',
  feed_summary_only: '仅 RSS 简介',
};
export const EMPTY_REVIEW = {
  worth_reading_now: null, importance_1_to_5: null, interest_1_to_5: null,
  place: null, reason: null, interest: null,
};

export function publicationLabel(candidate, full = false) {
  const publication = candidate.publication;
  if (!publication.value) return '发布时间未知';
  const prefix = candidate.material_status === 'daily_edited_text' ? '日报选编 '
    : candidate.material_status === 'question_context_only' ? '问题创建 '
      : publication.basis.includes('reprint') ? '本页转载 ' : '';
  if (publication.precision === 'day') return `${prefix}${publication.value} · 仅日期`;
  const date = new Date(publication.value);
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
  }).formatToParts(date).map(part => [part.type, part.value]));
  const day = full ? `${parts.year}-${parts.month}-${parts.day}` : `${parts.month}-${parts.day}`;
  return `${prefix}${day} ${parts.hour}:${parts.minute}`;
}

export function publicationKey(candidate) {
  if (!candidate.publication.value) return { day: '', time: null };
  if (candidate.publication.precision === 'day') return { day: candidate.publication.value, time: null };
  const date = new Date(candidate.publication.value);
  return { day: new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai' }).format(date), time: date.getTime() };
}

export function canonicalCandidate(candidate, byId) {
  return candidate.id === 'C41' ? byId.C21 : candidate;
}

export function topicMembers(topic, manifest, version) {
  return topic.id === 'market' ? manifest.selection_versions[version].market_members : topic.members;
}

export function entryFor(id, byId, manifest, version = 'early') {
  if (byId[id]) return { kind: 'content', id, candidate: byId[id] };
  const topic = manifest.topics.find(item => item.id === id);
  return topic ? { kind: 'topic', id, topic, members: topicMembers(topic, manifest, version).map(key => byId[key]) } : null;
}

export function entryPublication(entry, byId) {
  if (entry.kind === 'content') return publicationKey(canonicalCandidate(entry.candidate, byId));
  const materials = entry.members.filter(item => item.material_status !== 'question_context_only');
  return materials.map(item => publicationKey(canonicalCandidate(item, byId))).sort(comparePublication)[0] || { day: '', time: null };
}

function comparePublication(a, b) {
  return b.day.localeCompare(a.day) || (b.time === null ? 0 : 1) - (a.time === null ? 0 : 1) || (b.time || 0) - (a.time || 0);
}

export function feedEntries(byId, manifest, { version = 'early', sort = 'recommended', category = '全部' } = {}) {
  let entries = manifest.recommended.map(id => entryFor(id, byId, manifest, version));
  if (category !== '全部') {
    const allowed = new Set(manifest.categories[category] || []);
    entries = entries.filter(entry => entry.kind === 'content' ? allowed.has(entry.id) : entry.members.some(item => allowed.has(item.id)));
  }
  if (sort === 'latest') entries.sort((a, b) => comparePublication(entryPublication(a, byId), entryPublication(b, byId)));
  return entries;
}

export function freshFeedback(fingerprint) {
  return { schema_version: REVIEW_SCHEMA, dataset_sha256: fingerprint, contents: {}, topics: {}, experience: {}, updated_at: null };
}

function validReview(review) {
  if (!review || typeof review !== 'object' || Array.isArray(review)) return null;
  const result = { ...EMPTY_REVIEW };
  if (['yes', 'no', 'unknown'].includes(review.worth_reading_now)) result.worth_reading_now = review.worth_reading_now;
  for (const field of ['importance_1_to_5', 'interest_1_to_5']) {
    if (Number.isInteger(review[field]) && review[field] >= 1 && review[field] <= 5) result[field] = review[field];
  }
  if (['selection', 'recommended', 'latest', 'exclude', 'defer'].includes(review.place)) result.place = review.place;
  if (['yes', 'no'].includes(review.interest)) result.interest = review.interest;
  if (typeof review.reason === 'string') result.reason = review.reason.slice(0, 4000);
  return result;
}

export function restoreFeedback(raw, fingerprint, allowedIds, topicIds) {
  const clean = freshFeedback(fingerprint);
  if (!raw) return clean;
  let value;
  try { value = JSON.parse(raw); } catch { return clean; }
  if (!value || value.schema_version !== REVIEW_SCHEMA || value.dataset_sha256 !== fingerprint) return clean;
  for (const [field, ids] of [['contents', allowedIds], ['topics', topicIds]]) {
    for (const id of ids) {
      const review = validReview(value[field]?.[id]);
      if (review && hasReview(review)) clean[field][id] = review;
    }
  }
  if (value.experience && typeof value.experience === 'object') {
    for (const [key, entry] of Object.entries(value.experience)) {
      if (['density', 'selection_limit', 'refresh_preference', 'notes', 'missing', 'update_assessment'].includes(key) && ['string', 'number'].includes(typeof entry)) clean.experience[key] = entry;
    }
  }
  clean.updated_at = typeof value.updated_at === 'string' ? value.updated_at : null;
  return clean;
}

export function hasReview(review) {
  return review && Object.values(review).some(value => value !== null && value !== undefined && value !== '');
}

export function exportFeedback(feedback, candidates, manifest, version) {
  return {
    ...feedback,
    exported_at: new Date().toISOString(),
    reference_date: manifest.reference_date,
    layout_schema: manifest.schema_version,
    selection_version: version,
    ranking_method: 'manual_layout_for_review_not_algorithm_evaluation',
    reviewed_content_count: Object.values(feedback.contents).filter(hasReview).length,
    candidates: candidates.map(candidate => ({
      id: candidate.id, title: candidate.title, url: candidate.url,
      publication: candidate.publication, material_status: candidate.material_status,
      material_sha256: candidate.material_sha256,
      human_review: { ...EMPTY_REVIEW, ...feedback.contents[candidate.id] },
    })),
  };
}
