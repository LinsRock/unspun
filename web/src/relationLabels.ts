export const RELATION_LABELS: Record<string, string> = {
  factual_conflict: '事实冲突',
  viewpoint_difference: '观点差异',
  coverage_difference: '报道侧重',
  temporal_update: '时间进展',
  uncertain: '尚无法判断',
}

export function relationLabel(kind?: string | null) {
  return (kind && RELATION_LABELS[kind]) || '未分类差异'
}
