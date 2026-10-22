import { afterEach, expect, test, vi } from 'vitest'

import { getMemberTasks, memberCost, TopicApiError, writeTopic } from './topicApi'

afterEach(() => vi.unstubAllGlobals())

test('task filters include topic and article while all requests use same-origin credentials', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ items: [], total: 0, page: 2, page_size: 20 })))
  vi.stubGlobal('fetch', fetchMock)
  await getMemberTasks({ topic_id: 'topic/id', article_id: 7, status: 'blocked', page: 2 })
  expect(fetchMock).toHaveBeenCalledWith('/api/admin/member-tasks?page=2&page_size=20&topic_id=topic%2Fid&article_id=7&status=blocked', expect.objectContaining({ credentials: 'same-origin', cache: 'no-store' }))
})

test('conflict status survives a non-JSON error and does not retry automatically', async () => {
  const fetchMock = vi.fn().mockResolvedValue(new Response('conflict', { status: 409 }))
  vi.stubGlobal('fetch', fetchMock)
  const result = writeTopic({ kind: 'remove', topicId: 'topic/id', articleId: 7, body: { mutation_id: 'fixed-operation', expected_revision: 2, reason: 'human reason' } })
  await expect(result).rejects.toBeInstanceOf(TopicApiError)
  await expect(result).rejects.toMatchObject({ status: 409 })
  expect(fetchMock).toHaveBeenCalledOnce()
  expect(fetchMock).toHaveBeenCalledWith('/api/admin/topics/topic%2Fid/members/7/remove', expect.objectContaining({ method: 'POST', headers: { 'Content-Type': 'application/json' } }))
})

test('unknown costs remain unknown while known zero and sub-cent amounts are explicit', () => {
  expect(memberCost(null)).toBe('费用未知')
  expect(memberCost(undefined)).toBe('费用未知')
  expect(memberCost('')).toBe('费用未知')
  expect(memberCost('not-a-cost')).toBe('费用未知')
  expect(memberCost('0')).toBe('$0')
  expect(memberCost('0.00000001')).toBe('$0.00000001')
})
