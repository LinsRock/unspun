import assert from 'node:assert/strict'
import { chromium } from 'playwright'

// Run against a production preview; API fixtures are isolated to this browser context.
const baseURL = process.env.PWA_BASE_URL ?? 'http://localhost:4173'
const today = new Intl.DateTimeFormat('sv-SE', {
  timeZone: 'Asia/Shanghai',
}).format(new Date())
const intro = 'Offline digest verification'
const digest = {
  report_date: today,
  kind: 'daily',
  generated_at: new Date().toISOString(),
  payload: {
    intro,
    timezone: 'Asia/Shanghai',
    window_start: new Date(Date.now() - 86400000).toISOString(),
    window_end: new Date().toISOString(),
    events: [
      {
        id: 1,
        title: 'Offline snapshot event',
        summary_zh: 'Snapshot summary',
        score_final: 90,
        score_decayed: 80,
        score_breakdown: null,
        first_seen_at: new Date().toISOString(),
        changed_at: new Date().toISOString(),
        articles: [
          {
            id: 1,
            title: 'Source article',
            title_zh: null,
            url: 'https://example.com/article',
            source_id: 'test',
            source_name: 'Test source',
            published_at: null,
          },
        ],
        viewpoint: {
          claims: [{ article_id: 1, claim: 'Snapshot viewpoint' }],
          disagreements: [],
          model: 'fixture',
          generated_at: new Date().toISOString(),
        },
      },
    ],
  },
}
const browser = await chromium.launch({ headless: true, channel: 'chromium' })
try {
  const context = await browser.newContext({
    viewport: { width: 400, height: 850 },
  })
  context.setDefaultTimeout(10000)
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', (error) => errors.push(error.message))
  await context.route('**/api/digest/*', (route) =>
    route.fulfill({ json: digest }),
  )
  await page.goto(`${baseURL}/digest?date=latest`)
  await page.getByText(intro, { exact: true }).waitFor()
  await page.evaluate(() => navigator.serviceWorker.ready)
  await page.waitForFunction(() => navigator.serviceWorker.controller !== null)
  await page.waitForFunction(async () => {
    const request = indexedDB.open('keyval-store')
    const db = await new Promise((resolve, reject) => {
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error)
    })
    const read = db
      .transaction('keyval')
      .objectStore('keyval')
      .get('unspun-digests')
    const saved = await new Promise((resolve, reject) => {
      read.onsuccess = () => resolve(read.result)
      read.onerror = () => reject(read.error)
    })
    db.close()
    return saved?.clientState.queries.length >= 2
  })
  const manifest = await (
    await context.request.get(`${baseURL}/manifest.webmanifest`)
  ).json()
  assert.equal(manifest.start_url, '/digest')
  assert.equal(manifest.display, 'standalone')
  for (const icon of manifest.icons) {
    const response = await context.request.get(`${baseURL}${icon.src}`)
    assert.equal(response.status(), 200)
    const bytes = await response.body()
    assert.equal(bytes.subarray(1, 4).toString(), 'PNG')
    const [width, height] = icon.sizes.split('x').map(Number)
    assert.equal(bytes.readUInt32BE(16), width)
    assert.equal(bytes.readUInt32BE(20), height)
  }
  await context.unroute('**/api/digest/*')
  await context.setOffline(true)
  // Close the original tab and reopen the default installed-app start URL.
  await page.close()
  const offlinePage = await context.newPage()
  await offlinePage.goto(`${baseURL}/digest`)
  await offlinePage.getByText(intro, { exact: true }).waitFor()
  await offlinePage.getByRole('status').filter({ hasText: /\u79bb\u7ebf/ }).waitFor()
  assert.equal(await offlinePage.locator('article').count(), 1)
  assert.equal(
    await offlinePage
      .getByRole('link', { name: /Snapshot viewpoint/ })
      .getAttribute('href'),
    'https://example.com/article',
  )
  assert.equal(
    await offlinePage.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
  )
  await offlinePage.reload()
  await offlinePage.getByText(intro, { exact: true }).waitFor()
  await offlinePage.getByRole('button', { name: '\u524d\u4e00\u5929', exact: true }).click()
  await offlinePage.getByRole('status').filter({ hasText: /\u6b64\u65e5\u671f/ }).waitFor()
  assert.equal(await offlinePage.locator('article').count(), 0)
  // A direct navigation to an uncached SPA route must use the shell too.
  await offlinePage.goto(`${baseURL}/digest?date=2000-01-01`)
  await offlinePage.getByRole('status').filter({ hasText: /\u6b64\u65e5\u671f/ }).waitFor()
  assert.equal(await offlinePage.locator('article').count(), 0)
  // API navigation must never be rewritten to the HTML application shell.
  const apiPage = await context.newPage()
  await apiPage.goto(`${baseURL}/api/digest/${today}`).catch(() => {})
  assert.equal(await apiPage.locator('#root').count(), 0)
  await context.route('**/api/digest/*', (route) =>
    route.fulfill({ json: digest }),
  )
  await context.setOffline(false)
  await offlinePage.getByText(intro, { exact: true }).waitFor()
  assert.deepEqual(errors, [])
  console.log(
    'PASS: install assets, IndexedDB restore, offline new tab/reload, date navigation, mobile layout, API exclusion, reconnect',
  )
  await context.close()
} finally {
  await browser.close()
}
