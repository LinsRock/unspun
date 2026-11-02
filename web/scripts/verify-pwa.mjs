import assert from 'node:assert/strict'
import { chromium } from 'playwright'

// Verify the current app shell and removal of only the retired device cache.
const baseURL = process.env.PWA_BASE_URL ?? 'http://localhost:4173'
const browser = await chromium.launch({ headless: true, channel: 'chromium' })
try {
  const context = await browser.newContext({ viewport: { width: 390, height: 850 } })
  context.setDefaultTimeout(10000)
  const requests = []
  const apiRoute = route => {
    const path = new URL(route.request().url()).pathname
    requests.push(path)
    const data = path === '/api/reading-capabilities'
      ? { hybrid: false, topic_preferences: false, home: 'reading', engineering_preview: false }
      : path === '/api/reader-preferences'
        ? { version: 0, sort: 'recommended', interests: [], feedback: [] }
        : { items: [], next_cursor: null }
    return route.fulfill({ json: data })
  }
  await context.route('**/api/**', apiRoute)
  const page = await context.newPage()
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto(`${baseURL}/icon.svg`)
  await page.evaluate(async () => {
    localStorage.setItem('unspun.feed-preferences.v2', 'retired')
    localStorage.setItem('unspun-theme', 'dark')
    const request = indexedDB.open('keyval-store')
    request.onupgradeneeded = () => request.result.createObjectStore('keyval')
    const db = await new Promise((resolve, reject) => {
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error)
    })
    const tx = db.transaction('keyval', 'readwrite')
    tx.objectStore('keyval').put({ buster: 'digest-v1', original: 'retired snapshot' }, 'unspun-digests')
    tx.objectStore('keyval').put('retained', 'unrelated-data')
    await new Promise((resolve, reject) => { tx.oncomplete = resolve; tx.onerror = () => reject(tx.error) })
    db.close()
  })
  await page.goto(`${baseURL}/digest?date=latest`)
  await page.waitForURL(`${baseURL}/reading`)
  await page.locator('h1').waitFor()
  await page.evaluate(() => navigator.serviceWorker.ready)
  await page.waitForFunction(() => navigator.serviceWorker.controller !== null)
  await page.waitForFunction(async () => {
    const request = indexedDB.open('keyval-store')
    const db = await new Promise((resolve, reject) => {
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error)
    })
    const read = db.transaction('keyval').objectStore('keyval').get('unspun-digests')
    const value = await new Promise((resolve, reject) => {
      read.onsuccess = () => resolve(read.result)
      read.onerror = () => reject(read.error)
    })
    db.close()
    return value === undefined
  })
  assert.equal(await page.evaluate(() => localStorage.getItem('unspun.feed-preferences.v2')), null)
  assert.equal(await page.evaluate(() => localStorage.getItem('unspun-theme')), 'dark')
  assert.equal(await page.locator('nav a').count(), 3)
  assert.equal(await page.locator('a[href="/history"], a[href="/events"], a[href="/digest"]').count(), 0)
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false)
  const manifest = await (await context.request.get(`${baseURL}/manifest.webmanifest`)).json()
  assert.equal(manifest.start_url, '/')
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
  await context.unroute('**/api/**')
  await context.setOffline(true)
  await page.close()
  const offline = await context.newPage()
  await offline.goto(`${baseURL}/`)
  await offline.waitForURL(`${baseURL}/reading`)
  await offline.locator('h1').waitFor()
  await offline.reload()
  await offline.locator('h1').waitFor()
  await offline.goto(`${baseURL}/history`)
  await offline.waitForURL(`${baseURL}/reading`)
  const apiPage = await context.newPage()
  await apiPage.goto(`${baseURL}/api/digest/latest`).catch(() => {})
  assert.equal(await apiPage.locator('#root').count(), 0)
  await context.route('**/api/**', apiRoute)
  await context.setOffline(false)
  await offline.reload()
  await offline.locator('h1').waitFor()
  assert.deepEqual(errors, [])
  assert(!requests.some(path => /^\/api\/(events|digest|feed-preferences)/.test(path)))
  console.log('PASS: install assets, retired cache cleanup, current offline shell, redirects, mobile layout, API exclusion, reconnect')
  await context.close()
} finally {
  await browser.close()
}
