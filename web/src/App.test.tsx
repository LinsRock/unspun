// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, test, vi } from 'vitest'
import App from './App'

vi.mock('./reader/ReadingPage', () => ({ default: () => <h1>独立阅读</h1> }))
vi.mock('./reader/InterestsPage', () => ({ default: () => <h1>我的关注</h1> }))
vi.mock('./admin/AdminLayout', () => ({ default: () => <h1>运营总览</h1> }))
function renderApp(path = '/') {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ hybrid: false, home: 'reading', topic_preferences: false })))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>)
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); localStorage.clear(); delete document.documentElement.dataset.theme })

test('navigation contains current reading, interests and administration', async () => {
  renderApp()
  await screen.findByRole('heading', { name: '独立阅读' })
  expect(document.querySelector('nav')?.querySelectorAll('a')).toHaveLength(3)
  expect(document.querySelector('a[href="/history"], a[href="/events"], a[href="/digest"]')).toBeNull()
  fireEvent.click(screen.getByRole('link', { name: /我的关注/ }))
  await screen.findByRole('heading', { name: '我的关注' })
  fireEvent.click(screen.getAllByRole('link', { name: /管理后台/ })[0]!)
  await screen.findByRole('heading', { name: '运营总览' })
})

test('theme toggle applies and persists the choice', async () => {
  renderApp()
  await screen.findByRole('heading', { name: '独立阅读' })
  fireEvent.click(screen.getByRole('button', { name: '暗色' }))
  expect(document.documentElement.dataset.theme).toBe('dark')
  expect(localStorage.getItem('unspun-theme')).toBe('dark')
  fireEvent.click(screen.getByRole('button', { name: '跟随系统' }))
  expect(document.documentElement.dataset.theme).toBeUndefined()
})

test('unknown routes provide a return to the current home', () => {
  renderApp('/missing')
  expect(screen.getByRole('heading', { name: '页面不存在' })).toBeTruthy()
  expect(screen.getByRole('link', { name: '返回首页' }).getAttribute('href')).toBe('/')
})
