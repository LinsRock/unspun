import { useQuery } from '@tanstack/react-query'
import { Alert, Button, Descriptions, Drawer, Spin, Typography } from 'antd'

import type { AdminRange } from './adminFilters'
import { displayTime, getHistoryDetail, safeExternalUrl, type ArticleDetailData } from './adminHistoryApi'

interface Props { id: number | null; range: AdminRange; onClose: () => void; onEvent: (id: number) => void }

function groundingFacts(value: unknown): { text: string; quote: string }[] {
  if (!value || typeof value !== 'object' || !('facts' in value) || !Array.isArray(value.facts)) return []
  return value.facts.filter((fact): fact is { text: string; quote: string } =>
    Boolean(fact && typeof fact === 'object' && typeof fact.text === 'string' && typeof fact.quote === 'string'))
}

export default function ArticleDetail({ id, range, onClose, onEvent }: Props) {
  const query = useQuery({
    queryKey: ['admin', 'article', id],
    queryFn: ({ signal }) => getHistoryDetail<ArticleDetailData>('articles', id!, range, signal),
    enabled: id !== null, retry: false,
  })
  const article = query.data
  const href = article && safeExternalUrl(article.url)
  return <Drawer className="admin-detail-drawer" open={id !== null} onClose={onClose} title={article?.title_zh || article?.title || `文章 #${id}`} size={Math.min(680, typeof window === 'undefined' ? 680 : window.innerWidth)}>
    {query.isPending && <Spin />}
    {query.isError && <Alert type="error" showIcon title="无法加载文章详情" action={<Button size="small" onClick={() => void query.refetch()}>重试</Button>} />}
    {article && <div className="admin-detail-stack">
      <Descriptions bordered size="small" column={1} items={[
        { key: 'source', label: '来源', children: article.source_name || article.source_id },
        { key: 'published', label: '报道时间', children: displayTime(article.published_at) },
        { key: 'fetched', label: '入库时间', children: displayTime(article.fetched_at) },
        { key: 'status', label: '处理状态', children: ({ pending: '待处理', failed: '处理失败', summarized: '已摘要', embedded: '已嵌入', clustered: '已归入事件' } as Record<string, string>)[article.processing_status] || article.processing_status || '未记录' },
        { key: 'cost', label: '关联调用费用', children: article.call_cost === null || article.call_cost === undefined ? '未记录' : `$${article.call_cost.toFixed(4)}` },
      ]} />
      <div>{href ? <a href={href} target="_blank" rel="noopener noreferrer">打开原文 ↗</a> : <Typography.Text type="secondary">原文链接不可用</Typography.Text>}</div>
      <Typography.Title level={5}>中文摘要</Typography.Title><Typography.Paragraph>{article.summary_zh || '未记录'}</Typography.Paragraph>
      <Typography.Title level={5}>原文依据</Typography.Title>
      {groundingFacts(article.summary_grounding).length ? groundingFacts(article.summary_grounding).map((fact, index) => <blockquote className="admin-evidence" key={index}><strong>{fact.text}</strong><p>“{fact.quote}”</p></blockquote>) : <Typography.Text type="secondary">未记录可展示的摘要证据</Typography.Text>}
      <details className="admin-article-text"><summary>查看已提取正文</summary><Typography.Paragraph className="admin-full-text">{article.content || '未记录'}</Typography.Paragraph></details>
      {article.event ? <Button onClick={() => onEvent(article.event!.id)} aria-label={`查看关联事件 ${article.event.id}`}>查看关联事件 #{article.event.id} →</Button> : <Typography.Text type="secondary">尚未归属事件</Typography.Text>}
    </div>}
  </Drawer>
}
