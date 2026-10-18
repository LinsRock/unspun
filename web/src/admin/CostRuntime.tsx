import { Progress } from 'antd'
import { Link } from 'react-router-dom'
import { money, type CallLink, type CostSummary, type UnitCost } from './costsApi'

export function CallAssociation({ row }: { row: CallLink }) {
  if (row.association === 'not_recorded' || (!row.article_id && !row.task_id)) return <>未记录</>
  return <span>{row.article_id && <Link to={`/admin/content?r1_content=${row.article_id}`}>内容 #{row.article_id}</Link>}{row.task_id && <small>任务 #{row.task_id}</small>}{row.stage && <small>{row.stage}{row.phase ? ` / ${row.phase}` : ''}</small>}</span>
}

function Metric({ label, metric }: { label: string; metric: UnitCost }) {
  return <p>{label}：{metric.value_usd === null ? metric.status === 'unmeasured' ? '未测' : '费用未知' : `$${money(metric.value_usd)}${metric.status === 'known_lower_bound' ? '（已知下界）' : ''}`} · 分母 {metric.denominator_count}{['known_lower_bound', 'unknown'].includes(metric.status) && <small>含预留场景 {metric.known_plus_holds_scenario_usd === null ? '待核对' : `$${money(metric.known_plus_holds_scenario_usd)}`}，预留不是已发生费用。</small>}</p>
}

export function BudgetStatus({ budget }: { budget: CostSummary['budget'] }) {
  const enforcement = budget.enforcement
  const accounting = enforcement?.accounting
  const occupancy = accounting ? accounting.occupancy_usd : budget.spent
  const limit = enforcement?.monthly_limit_usd ?? budget.limit
  const percent = occupancy !== null && Number(limit) > 0 ? Math.min(100, Number(occupancy) / Number(limit) * 100) : null
  return <div className="admin-budget">
    <div><strong>{enforcement?.scope === 'evaluation' ? '原累计评测分配' : '本月模型预算'}</strong><span>USD</span></div>
    <div className="admin-budget-amount"><strong>{occupancy === null ? '待核对' : money(occupancy)}</strong><span>/ {money(limit)}</span></div>
    {percent !== null && <Progress percent={percent} showInfo={false} strokeColor={Number(occupancy) >= Number(limit) ? 'var(--hot)' : 'var(--accent)'} />}
    <small>{accounting ? '账本占用 / 分配（含历史差额与未结预留）' : '已知费用 / 分配（未含历史差额与未知预留）'}</small>
    {enforcement && <>
      <p>已知费用 ${money(accounting ? accounting.known_spend_usd : budget.spent)} · 历史差额 {accounting?.historical_carry_usd == null ? '待核对' : `$${money(accounting.historical_carry_usd)}`}</p>
      <p>未结请求 {enforcement.unresolved_calls} 笔 · 保留预留 ${money(enforcement.reserved_usd)}，不计作已知费用。</p>
      {!enforcement.enabled && <p className="admin-budget-warning">付费预算尚未启用。</p>}
      {enforcement.incident && <p className="admin-budget-warning">账务需要核对：{enforcement.incident}</p>}
      <small>实际请求还受阶段、审核及提供方硬限约束。生产按 UTC 月份记账；评测分配不随月份重置。</small>
      {enforcement.unit_costs && <details><summary>R1 运行单位成本</summary>
        <Metric label="每百个尝试候选" metric={enforcement.unit_costs.per_100_candidates} />
        <Metric label="每条准入结果" metric={enforcement.unit_costs.per_admitted_item} />
        <Metric label="每份新导读" metric={enforcement.unit_costs.per_new_guide} />
        <small>仅统计当前契约的关联运行任务，包含失败费用。准入结果不等于当前公开条目；这些分母不是来源召回率或用户评价。</small>
      </details>}
    </>}
    {occupancy !== null && Number(occupancy) >= Number(limit) && <p className="admin-budget-warning">已达到分配上限</p>}
  </div>
}
