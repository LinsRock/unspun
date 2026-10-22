import type { MemberRelation } from './topicApi'

export const RELATIONS: Record<MemberRelation, string> = { report: '直接报道', background: '背景材料', opinion: '观点', explanation: '解释', reprint: '转载' }
export const VOICES = { reported: '报道事实', author: '作者观点', question: '问题背景', description: '内容简介' }
