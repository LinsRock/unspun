export function contentQualityLabel(quality?: string | null): string | null {
  if (quality === 'limited') return '信息有限'
  if (quality === 'review_limited') return '摘要审核因预算延期'
  return null
}

export function readingReasonLabel(reason?: string | null): string {
  return ({ review_budget: '摘要审核因预算延期，额度恢复后继续', review_pending: '尚未完成发布审核', title_unverified: '中文标题未通过审核', language_invalid: '中文内容不完整，等待重新处理', no_added_facts: '仅有标题信息，保留为消息线索' } as Record<string, string>)[reason ?? ''] ?? '尚未达到发布标准'
}
