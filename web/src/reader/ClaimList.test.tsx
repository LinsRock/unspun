// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import ClaimList from './ClaimList'

afterEach(cleanup)

describe('card attribution', () => {
  it('shares the source attribution without changing or dropping any of its points', () => {
    const claims = [
      { text: '文中称：项目预计明年完成，具体时间尚未确定。', quote: '项目预计明年完成，具体时间尚未确定。', voice: 'reported' },
      { text: '文中称：报告用“文中称”表达尚未核实的消息。', quote: '报告用“文中称”表达尚未核实的消息。', voice: 'reported' },
    ]
    const original = structuredClone(claims)
    render(<ClaimList claims={claims} label="AI 要点" />)
    expect(screen.getByText('AI 要点 · 原文陈述')).toBeTruthy()
    expect(screen.getAllByRole('listitem').map(item => item.textContent)).toEqual(claims.map(claim => claim.quote))
    expect(claims).toEqual(original)
  })

  it.each([
    ['文中观点：', 'author', '作者观点'],
    ['简介中提到：', 'description', '简介内容'],
    ['问题背景中提到：', 'question', '问题背景'],
  ])('keeps %s explicitly scoped rather than presenting it as an independent fact', (prefix, voice, label) => {
    render(<ClaimList claims={[{ text: `${prefix}这是一项有待检验的判断。`, quote: '这是一项有待检验的判断。', voice }]} label="AI 要点" />)
    expect(screen.getByText(`AI 要点 · ${label}`)).toBeTruthy()
    expect(screen.getByRole('listitem').textContent).toBe('这是一项有待检验的判断。')
  })

  it('leaves mixed voices and unrecognized or inconsistent attributions intact', () => {
    const claims = [
      { text: '文中称：一项报道。', quote: '一项报道。', voice: 'reported' },
      { text: '文中观点：一项作者判断。', quote: '一项作者判断。', voice: 'author' },
      { text: '文中称：需要保留的作者归属。', quote: '需要保留的作者归属。', voice: 'author' },
      { text: '受访者称：一项未确认的消息。', quote: '一项未确认的消息。', voice: 'reported' },
    ]
    render(<ClaimList claims={claims} label="AI 要点" />)
    expect(screen.getAllByRole('listitem').map(item => item.textContent)).toEqual(claims.map(claim => claim.text))
    expect(screen.queryByText('AI 要点 · 原文陈述')).toBeNull()
  })
})
