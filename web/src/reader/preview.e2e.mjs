// Explicit opt-in, real-API smoke test against the isolated R2-10 preview only.
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { chromium } from 'playwright'

const base = process.env.UNSPUN_R210_PREVIEW_URL
assert(base && ['127.0.0.1', 'localhost'].includes(new URL(base).hostname), 'An explicit loopback preview URL is required')
const output = process.env.UNSPUN_R210_SCREENSHOTS ?? '/tmp/unspun-r210-browser'
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage()
const errors = []
page.on('pageerror', error => errors.push(error.message))
async function json(path) { const response = await context.request.get(base + path); assert(response.ok(), `${path}: ${response.status()}`); return response.json() }
const capabilities = await json('/api/reading-capabilities')
assert(capabilities.engineering_preview && capabilities.home === 'discover')
assert.equal((await json('/api/health')).version, 'r2-10-engineering-preview')
const initial = await json('/api/topic-preferences')
assert.equal(initial.topic_preferences.length, 0, 'Use a preview with no existing topic preferences for this interaction test')
const observed = []
page.on('response', response => { if (response.url().includes('/api/')) observed.push({ path: new URL(response.url()).pathname, status: response.status() }) })
try {
  await page.goto(base)
  await page.getByRole('heading', { name: '跟上变化，发现好内容' }).waitFor()
  await page.getByRole('link', { name: '如果黄金极度廉价，它会成为建材吗？', exact: true }).waitFor()
  await page.keyboard.press('Tab')
  assert.equal(await page.locator(':focus').innerText(), '跳到内容')
  await page.keyboard.press('Enter')
  assert.equal(await page.locator(':focus').getAttribute('id'), 'page-content')
  await page.getByRole('button', { name: '亮色', exact: true }).click()
  await page.screenshot({ path: `${output}/desktop-feed-light.png` })
  await page.getByRole('button', { name: '继续阅读', exact: true }).click()
  const topicLink = page.getByRole('link', { name: 'AI收益分配方案的报道比较', exact: true })
  await topicLink.waitFor()
  await topicLink.scrollIntoViewIfNeeded()
  const previousY = await page.evaluate(() => scrollY)
  await topicLink.click()
  await page.getByRole('heading', { name: '话题概况', exact: true }).waitFor()
  await page.getByRole('button', { name: '关注话题', exact: true }).focus()
  await page.keyboard.press('Enter')
  await page.getByRole('button', { name: '已关注 · 取消', exact: true }).waitFor()
  await page.getByRole('button', { name: '感兴趣', exact: true }).click()
  await page.getByRole('button', { name: '撤销感兴趣', exact: true }).waitFor()
  await page.getByRole('button', { name: '不感兴趣', exact: true }).click()
  await page.getByRole('button', { name: '撤销不感兴趣', exact: true }).waitFor()
  await page.getByRole('button', { name: '撤销不感兴趣', exact: true }).click()
  await page.getByRole('button', { name: '不感兴趣', exact: true }).waitFor()
  await page.getByRole('button', { name: '已关注 · 取消', exact: true }).click()
  await page.getByRole('button', { name: '关注话题', exact: true }).waitFor()
  await page.getByRole('button', { name: '暗色', exact: true }).click()
  await page.screenshot({ path: `${output}/desktop-topic-dark.png` })
  const related = page.locator('#related h3 a').first()
  const relatedTitle = await related.innerText()
  await related.click()
  await page.getByRole('heading', { name: relatedTitle, exact: true }).waitFor()
  assert.equal(await page.getByRole('button', { name: '按需生成导读' }).count(), 0)
  await page.getByRole('link', { name: '← 返回话题', exact: true }).click()
  await page.getByRole('heading', { name: '话题概况', exact: true }).waitFor()
  await page.getByRole('link', { name: '← 返回阅读列表', exact: true }).click()
  await page.getByRole('button', { name: '继续阅读', exact: true }).waitFor()
  // Preference changes fence the previous snapshot and intentionally restart it.
  await page.getByRole('button', { name: '继续阅读', exact: true }).click()
  await topicLink.waitFor()
  await topicLink.scrollIntoViewIfNeeded()
  const stableY = await page.evaluate(() => scrollY)
  await topicLink.click()
  await page.getByRole('heading', { name: '话题概况', exact: true }).waitFor()
  await page.getByRole('link', { name: '← 返回阅读列表', exact: true }).click()
  await topicLink.waitFor()
  await page.waitForFunction(expected => Math.abs(scrollY - expected) < 4, stableY)
  assert(previousY > 0 && stableY > 0)

  for (const width of [390, 768, 1440]) {
    await page.setViewportSize({ width, height: width < 700 ? 844 : 1000 })
    for (const theme of ['亮色', '暗色']) {
      await page.getByRole('button', { name: theme, exact: true }).click()
      for (const [name, path, heading] of [
        ['feed', '/discover', '跟上变化，发现好内容'],
        ['topic', new URL(await topicLink.getAttribute('href'), base).pathname, '话题概况'],
        ['interests', '/interests', '我的关注'],
        ['history', '/history', '历史阅读'],
      ]) {
        await page.goto(base + path)
        await page.getByRole('heading', { name: heading, exact: true }).waitFor()
        await page.waitForLoadState('networkidle')
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Horizontal overflow: ${width} ${name}`)
        await page.screenshot({ path: `${output}/${width}-${name}-${theme === '亮色' ? 'light' : 'dark'}.png` })
      }
      await page.goto(base + '/discover')
      await page.getByRole('button', { name: '继续阅读', exact: true }).click()
      await topicLink.waitFor()
    }
  }
  await page.goto(base + '/discover?sort=latest')
  await page.getByRole('heading', { name: '跟上变化，发现好内容' }).waitFor()
  await page.getByRole('button', { name: '继续阅读', exact: true }).waitFor()
  const first = await json('/api/feed?mode=mixed&sort=latest&limit=10')
  const stale = first.next_cursor
  const current = await json('/api/topic-preferences')
  const changed = await context.request.put(base + '/api/reader-preferences', { headers: { Origin: base }, data: { version: current.version, mutation_id: crypto.randomUUID(), sort: 'latest' } })
  assert(changed.ok())
  assert.equal((await context.request.get(base + '/api/feed?mode=mixed&sort=latest&limit=10&cursor=' + encodeURIComponent(stale))).status(), 409)
  await page.getByRole('button', { name: '继续阅读', exact: true }).click()
  await page.getByRole('alert').waitFor()
  await page.getByRole('button', { name: '重新加载', exact: true }).click()
  await page.getByRole('button', { name: '继续阅读', exact: true }).waitFor()
  await context.setOffline(true)
  await page.getByText('网络不可用，关注和反馈暂不能保存；不会离线排队。', { exact: true }).waitFor()
  assert(await page.getByRole('button', { name: '推荐', exact: true }).isDisabled())
  await context.setOffline(false)
  const lan = process.env.UNSPUN_R210_LAN_URL
  if (lan) {
    assert(/^192\.168\./.test(new URL(lan).hostname), 'Explicit private LAN preview only')
    const rows = await json('/api/feed?mode=mixed&limit=50')
    const topic = rows.items.find(item => item.type === 'topic')
    await page.goto(`${lan}/topics/${topic.id}`)
    await page.getByRole('heading', { name: '话题概况', exact: true }).waitFor()
    assert.equal(await page.evaluate(() => window.isSecureContext), false)
    await page.getByRole('button', { name: '关注话题', exact: true }).click()
    await page.getByRole('button', { name: '已关注 · 取消', exact: true }).click()
    await page.getByRole('button', { name: '关注话题', exact: true }).waitFor()
  }
  assert.equal(errors.length, 0, errors.join('\n'))
  console.log(JSON.stringify({ real_api: true, topic_preferences: 'follow/modify/revoke/unfollow', pagination: 'return and 409 restart passed', layouts: [390, 768, 1440], themes: ['light', 'dark'], keyboard: 'skip link', offline: 'writes disabled', lan_writes: !!lan, page_errors: errors, screenshots: output, api_responses: observed.length }))
} finally {
  const current = await json('/api/topic-preferences')
  if (current.sort !== initial.sort) {
    const response = await context.request.put(base + '/api/reader-preferences', { headers: { Origin: base }, data: { version: current.version, mutation_id: crypto.randomUUID(), sort: initial.sort } })
    assert(response.ok(), 'Failed to restore the test sort')
  }
  await browser.close()
}
