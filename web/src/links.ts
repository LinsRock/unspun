// Scraped source URLs are untrusted; only http(s) can become clickable links.
export function safeHref(url: string): string | undefined {
  try {
    const parsed = new URL(url)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:'
      ? url
      : undefined
  } catch {
    return undefined
  }
}
