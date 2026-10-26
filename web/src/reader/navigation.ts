export function readingReturn(value: unknown, fallback = '/discover'): string {
  return typeof value === 'string' && /^\/(?:discover|reading|interests|topics\/[a-f0-9-]+)(?:\?[^#]*)?$/.test(value) ? value : fallback
}
export const readingPositions = new Map<string, number>()
