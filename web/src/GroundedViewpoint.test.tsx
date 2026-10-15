// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, test } from 'vitest'
import type { EventOut } from './api'
import EventCard from './EventCard'
import DigestItem from './DigestItem'

const event: EventOut = {
  id: 1,
  title: '证据展示样本',
  summary_zh: '有依据的摘要',
  score_final: 70,
  score_decayed: 65,
  score_breakdown: null,
  first_seen_at: '2026-10-10T00:00:00Z',
  changed_at: '2026-10-10T00:00:00Z',
  articles: [
    {
      id: 1,
      title: 'Source one',
      title_zh: null,
      url: 'https://example.com/one',
      source_id: 'a',
      source_name: '来源甲',
      published_at: null,
      content_quality: 'limited',
    },
    {
      id: 2,
      title: 'Source two',
      title_zh: null,
      url: 'https://example.com/two',
      source_id: 'b',
      source_name: '来源乙',
      published_at: null,
    },
  ],
  viewpoint: {
    model: 'm',
    generated_at: '2026-10-10T00:00:00Z',
    claims: [
      {
        article_id: 1,
        claim: '先暂停航班',
        evidence_quote: 'Flights were suspended at 08:00.',
      },
      {
        article_id: 2,
        claim: '后恢复航班',
        evidence_quote: 'Flights resumed at 11:00.',
      },
    ],
    disagreements: [
      {
        point: '停航后恢复，并非相互矛盾',
        claim_indexes: [0, 1],
        kind: 'temporal_update',
      },
    ],
  },
}
afterEach(cleanup)

test('feed comparison shows original evidence, limited input and temporal classification', () => {
  render(<EventCard event={event} />)
  fireEvent.click(screen.getByRole('button', { name: /查看依据/ }))
  fireEvent.click(screen.getByRole('button', { name: /观点对比/ }))
  expect(screen.getAllByText('原文依据').length).toBe(2)
  expect(screen.getByText('Flights were suspended at 08:00.')).toBeTruthy()
  expect(screen.getByText('时间进展')).toBeTruthy()
  expect(screen.getAllByText('信息有限').length).toBeGreaterThan(0)
  expect(
    screen
      .getAllByRole('link', { name: /Source one/ })[0]!
      .getAttribute('href'),
  ).toBe('https://example.com/one')
})

test('digest shares the same evidence and relation semantics', () => {
  render(<DigestItem event={event} rank={1} />)
  expect(screen.getAllByText('原文依据').length).toBe(2)
  expect(screen.getByText('Flights resumed at 11:00.')).toBeTruthy()
  expect(screen.getByText('时间进展')).toBeTruthy()
  expect(screen.queryByText('分歧焦点：')).toBeNull()
})

test('historical claims without quotes are explicitly marked', () => {
  const legacy = structuredClone(event)
  if (!legacy.viewpoint) throw new Error('Missing fixture')
  for (const claim of legacy.viewpoint.claims) delete claim.evidence_quote
  for (const point of legacy.viewpoint.disagreements) delete point.kind
  render(<DigestItem event={legacy} rank={1} />)
  expect(screen.getAllByText('历史版本，未附证据').length).toBe(2)
  expect(screen.getByText('未分类差异')).toBeTruthy()
})

test('evidence is plain text and unsafe article links stay disabled', () => {
  const unsafe = structuredClone(event)
  unsafe.articles[0]!.url = 'javascript:alert(1)'
  unsafe.viewpoint!.claims[0]!.evidence_quote = '<img src=x onerror=alert(1)>'
  render(<DigestItem event={unsafe} rank={1} />)
  expect(screen.getByText('<img src=x onerror=alert(1)>')).toBeTruthy()
  expect(screen.queryByRole('img')).toBeNull()
  expect(screen.queryByRole('link', { name: /来源甲/ })).toBeNull()
})

test('limited source status remains visible without a comparison', () => {
  const limited = structuredClone(event)
  limited.articles = limited.articles.slice(0, 1)
  limited.viewpoint = null
  render(<EventCard event={limited} />)
  fireEvent.click(screen.getByRole('button', { name: /查看依据/ }))
  expect(screen.getByText('信息有限')).toBeTruthy()
  cleanup()
  render(<DigestItem event={limited} rank={1} />)
  expect(screen.getByText('信息有限')).toBeTruthy()
})

test('cached empty comparison does not hide source limitations', () => {
  const empty = structuredClone(event)
  empty.viewpoint!.claims = []
  empty.viewpoint!.disagreements = []
  render(<EventCard event={empty} />)
  fireEvent.click(screen.getByRole('button', { name: /查看依据/ }))
  expect(screen.getByText('信息有限')).toBeTruthy()
})

test('review budget fallback is labelled separately from scarce source evidence', () => {
  const paused = structuredClone(event)
  paused.viewpoint = null
  paused.articles = paused.articles.slice(0, 1)
  paused.articles[0]!.content_quality = 'review_limited'
  render(<EventCard event={paused} />)
  fireEvent.click(screen.getByRole('button', { name: /查看依据/ }))
  expect(screen.getByText('摘要审核因预算延期')).toBeTruthy()
  expect(screen.queryByText('信息有限')).toBeNull()
  cleanup()
  render(<DigestItem event={paused} rank={1} />)
  expect(screen.getByText('摘要审核因预算延期')).toBeTruthy()
})

test('pending comparison audit remains visible when source summaries are reviewed', () => {
  const paused = structuredClone(event)
  for (const article of paused.articles) article.content_quality = 'grounded'
  paused.viewpoint!.claims = []
  paused.viewpoint!.disagreements = []
  paused.viewpoint!.status = 'review_limited'
  render(<EventCard event={paused} />)
  fireEvent.click(screen.getByRole('button', { name: /查看依据/ }))
  expect(screen.getByText(/观点对比审核因预算延期/)).toBeTruthy()
  cleanup()
  render(<DigestItem event={paused} rank={1} />)
  expect(screen.getByText('观点对比待审核')).toBeTruthy()
})
