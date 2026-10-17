// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { StrictMode, useLayoutEffect } from 'react'
import type { ReactElement } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ReadingPage from './ReadingPage'
import ContentPage from './ContentPage'
import InterestsPage from './InterestsPage'
import type { ContentDetail, FeedPage, ReaderState } from './api'

const empty: ReaderState = { version: 0, sort: 'recommended', interests: [], feedback: [] }
const detail: ContentDetail = {
  id: 10, title: '模拟样本：公开媒体简介', original_title: 'Synthetic media description', 
  url: 'https://example.org/video',
  source_id: 'synthetic', source_name: '模拟来源', channels: [],
  metadata: { form: 'video', genre: null, platform: 'synthetic', publisher: null, authors: [], times: [{ kind: 'editorial', precision: 'date', at: null, on: '2026-10-16', basis: 'synthetic' }], original_url: null, media_url: 'https://example.org/video', duration_seconds: null },
  material_scope: 'media_description', material_id: 1, input_fingerprint: 'synthetic', card: { title_zh: '模拟样本', genre: 'description', domains: ['science'], claims: [{ text: '简介中介绍了一项测量。', quote: '简介中介绍了一项测量。', voice: 'description' }], reading_value: 1, reading_reason: null }, feedback: null, ranking: { reading_value: 1, current_value: .5, interest: 0, feedback: 0 }, preview: true, requested_alias_id: null,
  material: { scope: 'media_description', paragraphs: [{ kind: 'paragraph', text: '简介只说明了测量过程，没有实际视频内容。<img src=x onerror=alert(1)>' }], retrieved_at: '2026-10-16T10:00:00Z', extractor_version: 'synthetic' }, guide: { status: 'not_requested', reason: null, requestable: true, task_id: null, payload: null },
}
let state: ReaderState
let calls: { path: string; method: string; body?: Record<string, unknown> }[]
function setup(path = '/reading', content: ReactElement = <ContentPage />) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(<StrictMode><QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><Routes><Route path="/reading" element={<ReadingPage />} /><Route path="/reading/:id" element={content} /><Route path="/interests" element={<InterestsPage />} /></Routes></MemoryRouter></QueryClientProvider></StrictMode>)
}
beforeEach(() => {
  state = structuredClone(empty); calls = []
  vi.stubGlobal('scrollTo', vi.fn())
  vi.stubGlobal('fetch', vi.fn(async (input: string, options?: RequestInit) => {
    const method = options?.method ?? 'GET'; const body = options?.body ? JSON.parse(String(options.body)) as Record<string, unknown> : undefined
    calls.push({ path: String(input), method, body })
    if (input === '/api/reader-preferences') return Response.json(state)
    if (String(input).startsWith('/api/feed?')) return Response.json({ items: [detail], next_cursor: null, sort: 'recommended', as_of: '2026-10-16T10:00:00Z', ranking_version: 'synthetic', preview: true, empty_reason: null } satisfies FeedPage)
    if (input === '/api/contents/10' && method === 'GET') return Response.json(detail)
    if (input === '/api/contents/10/guide') return Response.json({ ...detail.guide, status: 'pending', task_id: 1, requestable: false })
    if (input === '/api/feedback') {
      if (body?.version !== state.version) return Response.json({ detail: { current: state } }, { status: 409 })
      state = { ...state, version: state.version + 1, feedback: method === 'DELETE' ? [] : [{ content_id: 10, value: body?.value as 'interested', version: state.version + 1 }] }
      return Response.json(state)
    }
    if (input === '/api/interests') {
      const target = body?.target as ReaderState['interests'][0]['target']
      state = { ...state, version: state.version + 1, interests: method === 'DELETE' ? [] : [{ resource_key: 'synthetic', label: target.value, target, support: { matching: 'unknown_source', collection: 'not_connected', dedicated_author_collection: false } }] }
      return Response.json(state)
    }
    return Response.json({}, { status: 404 })
  }))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

describe('R1 reading', () => {
  it('restores the second page and its last scroll position after a short detail', async () => {
    const second = { ...detail, id: 11, title: '模拟样本：第二页内容' }
    const original = vi.mocked(fetch).getMockImplementation()!
    vi.stubGlobal('fetch', vi.fn(async (input: string, options?: RequestInit) => {
      if (String(input).startsWith('/api/feed?')) {
        const next = new URL(String(input), 'https://example.org').searchParams.has('cursor')
        return Response.json({ items: [next ? second : detail], next_cursor: next ? null : 'second-page', sort: 'recommended', as_of: '2026-10-16T10:00:00Z', ranking_version: 'synthetic', preview: true, empty_reason: null } satisfies FeedPage)
      }
      if (input === '/api/contents/11') return Response.json(second)
      return original(input, options)
    }))
    function ShortDetail() {
      // Model the browser clamping a shorter document before passive cleanup.
      useLayoutEffect(() => { vi.stubGlobal('scrollY', 0) }, [])
      return <ContentPage />
    }
    setup('/reading', <ShortDetail />)
    fireEvent.click(await screen.findByRole('button', { name: '继续阅读' }))
    const link = await screen.findByRole('link', { name: second.title })
    vi.stubGlobal('scrollY', 2400)
    fireEvent.scroll(window)
    fireEvent.click(link)
    await screen.findByRole('heading', { name: second.title })
    fireEvent.click(screen.getByRole('link', { name: '← 返回阅读列表' }))
    await screen.findByRole('link', { name: second.title })
    expect(screen.queryByRole('button', { name: '继续阅读' })).toBeNull()
    await waitFor(() => expect(window.scrollTo).toHaveBeenLastCalledWith(0, 2400))
    vi.stubGlobal('scrollY', 0)
    fireEvent.scroll(window)
  })
  it('uses real API contracts, preserves scope and saves then revokes feedback', async () => {
    setup()
    await screen.findByRole('heading', { name: detail.title })
    expect(screen.getByText('媒体简介，未观看或收听')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: '感兴趣' }))
    await screen.findByRole('button', { name: '感兴趣 · 撤销' })
    fireEvent.click(screen.getByRole('button', { name: '感兴趣 · 撤销' }))
    await waitFor(() => expect(state.feedback).toHaveLength(0))
    const writes = calls.filter(call => call.path === '/api/feedback')
    expect(writes.map(w => w.method)).toEqual(['PUT', 'DELETE'])
    expect(writes.map(w => w.body?.version)).toEqual([0, 1])
    expect(writes.every(w => typeof w.body?.mutation_id === 'string')).toBe(true)
  })
  it('detail GET never requests a guide and renders source as plain text', async () => {
    setup('/reading/10')
    await screen.findByRole('heading', { name: detail.title })
    expect(screen.getByText(/未观看或收听，不提供观后结论/)).toBeTruthy()
    expect(document.querySelector('img')).toBeNull()
    expect(calls.some(call => call.method !== 'GET')).toBe(false)
    fireEvent.click(screen.getByRole('button', { name: '按需生成导读' }))
    await waitFor(() => expect(calls.filter(call => call.path.endsWith('/guide'))).toHaveLength(1))
  })
  it('keeps date-only precision and never labels retrieval as original publication', async () => {
    setup('/reading/10')
    await screen.findByRole('heading', { name: detail.title })
    expect(screen.getByText(/10-16 · 编辑版发布（仅日期）/)).toBeTruthy()
    expect(screen.queryByText(/10-16 00:00/)).toBeNull()
  })
  it('saves unknown source interest without claiming source collection', async () => {
    setup('/interests')
    await screen.findByText('还没有关注。可以先浏览，再逐渐留下偏好。')
    fireEvent.change(screen.getByLabelText('关注类型'), { target: { value: 'source' } })
    fireEvent.change(screen.getByLabelText('来源名称'), { target: { value: 'unknown-source' } })
    fireEvent.click(screen.getByRole('button', { name: '保存关注' }))
    await screen.findByText('采集未开放／未接入；只保存偏好')
    fireEvent.click(screen.getByRole('button', { name: '取消关注' }))
    await waitFor(() => expect(state.interests).toHaveLength(0))
  })
  it('does not auto-resubmit a stale device write after 409', async () => {
    setup()
    await screen.findByRole('heading', { name: detail.title })
    state = { ...state, version: 4 }
    fireEvent.click(screen.getByRole('button', { name: '感兴趣' }))
    await screen.findByText('另一台设备已更新设置，已载入当前状态。请核对后重新操作。')
    expect(calls.filter(call => call.method === 'PUT')).toHaveLength(1)
    expect(state.feedback).toHaveLength(0)
  })
})
