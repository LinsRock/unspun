export function contentQualityLabel(quality?: string | null): string | null {
  if (quality === 'limited') return '信息有限'
  if (quality === 'review_limited') return '未完成审核'
  return null
}
