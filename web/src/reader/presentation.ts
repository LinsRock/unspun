import type { Metadata } from './api'
export const DOMAINS: Record<string, string> = { world: '国际', china: '中国', economy: '经济', technology: '科技', science: '科学', health: '健康', society: '社会', culture: '文化', life: '生活', environment: '环境' }
export const GENRES: Record<string, string> = { news: '报道', analysis: '分析', opinion: '观点', knowledge: '知识', review: '评论', question: '问题线索', description: '内容简介' }
export const SCOPES: Record<string, string> = { open_text_unit: '已取得的公开正文', editorial_edition: '日报编辑版正文', complete_brief: '完整短讯', preview: '公开预览，非全文', question_background: '问题背景，未取得回答', media_description: '媒体简介，未观看或收听', feed_lead: '订阅导语，非全文', none: '未取得可读材料' }
export const TIME_LABELS: Record<string, string> = { original: '原始发布', editorial: '编辑版发布', question_created: '问题创建', feed: '订阅提供时间', modified: '修改时间', reprint: '转载时间' }
export function publication(metadata: Metadata): string {
  const value = ['original', 'editorial', 'question_created'].map(kind => metadata.times.find(t => t.kind === kind && t.precision !== 'unknown')).find(Boolean)
  if (!value) return '原始发布时间未知'
  const date = value.at ? new Date(value.at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false }) : value.on
  return `${date ?? '未知'} · ${TIME_LABELS[value.kind]}${value.precision === 'date' ? '（仅日期）' : ''}`
}
export function guideMessage(status: string, reason: string | null): string {
  if (reason === 'insufficient_increment') return '现有材料没有足够的新增细节，暂不提供导读。'
  if (reason === 'paid_stage_disabled') return '导读处理尚未开放，仍可阅读已取得材料或打开原文。'
  if (reason === 'card_unavailable') return '卡片未通过当前审核，导读暂不可用。'
  return ({ not_requested: '尚未生成导读。按需整理，不影响正文阅读。', pending: '导读排队中，可先阅读正文。', generating: '正在整理导读。', review_pending: '导读已整理，正在审核。', budget_deferred: '导读因预算暂缓，已有草稿会保留。', failed: '导读处理失败，尚无可发布结果。正文与原文仍可阅读。', blocked: '导读当前不可用，原文入口仍保留。', rejected: '现有材料不适合生成额外导读。', unavailable: '暂不提供导读。' } as Record<string, string>)[status] ?? '导读状态待更新。'
}

export const SOURCE_NAMES: Record<string, string> = { xinhua: '新华社', 'zaobao-china': '早报中国', 'zaobao-world': '早报国际', '36kr-newsflashes': '36氪快讯', 'people-frontpage': '人民日报头版', 'bjnews-depth': '新京报深读', 'zhihu-daily': '知乎日报', 'zhihu-hot': '知乎热榜', 'douban-book': '豆瓣书评', 'douban-movie': '豆瓣影评', 'fortune-business': '财富商业', 'fortune-tech': '财富科技', 'infzm-news': '南方周末公开预览', 'bbc-world': 'BBC 国际', 'bbc-zhongwen': 'BBC 中文', 'nyt-world': '纽约时报国际', 'nyt-cn': '纽约时报中文', 'wsj-world': '华尔街日报国际' }
export const PLATFORM_NAMES: Record<string, string> = { zhihu: '知乎', 'zhihu-daily': '知乎日报', douban: '豆瓣', xinhua: '新华社', zaobao: '联合早报', people: '人民日报', bjnews: '新京报', fortune: '财富', infzm: '南方周末', bbc: 'BBC', nyt: '纽约时报', wsj: '华尔街日报' }
export function resourceValue(value: string, names: Record<string, string>): string { return Object.entries(names).find(([, name]) => name === value)?.[0] ?? value }
