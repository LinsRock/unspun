import { useQuery } from '@tanstack/react-query'
import { Alert, Empty, List } from 'antd'

import { getCost, money } from './costsApi'

interface Renewal { rule_id: number; name: string; due_on: string; amount: string; currency: string; reminder_days: number }

export default function Renewals() {
  const query = useQuery({ queryKey: ['admin', 'renewals'], queryFn: ({ signal }) => getCost<{ scope: 'current'; items: Renewal[] }>('renewals', undefined, signal), retry: false })
  return <section className="admin-panel"><h2>站内续费提醒</h2><p className="admin-note">当前规则即将开始的新覆盖期，默认提前 7 天提醒；不发起外部付款。</p>
    {query.isPending && <p role="status">正在加载续费提醒…</p>}
    {query.isError && <Alert type="error" message="续费提醒加载失败" />}
    {query.data && (query.data.items.length ? <List dataSource={query.data.items} renderItem={item => <List.Item>{item.due_on} · {item.name} · {money(item.amount)} {item.currency}</List.Item>} /> : <Empty description="当前没有即将到期的规则" />)}
  </section>
}
