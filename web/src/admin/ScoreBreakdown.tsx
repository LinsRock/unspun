function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}
export default function ScoreBreakdown({ value }: { value: unknown }) {
  const breakdown = record(value)
  const objective = record(breakdown.objective)
  const importance = record(breakdown.importance)
  const groups = [
    { label: '客观信号', data: objective, fields: [{ key: 'breadth', label: '报道广度', max: 100 }, { key: 'growth', label: '报道增长', max: 100 }, { key: 'source_quality', label: '来源质量', max: 100 }, { key: 'community', label: '社区热度', max: 100 }] },
    { label: '重要性判断', data: importance, fields: [{ key: 'scope', label: '影响范围', max: 5 }, { key: 'durability', label: '持久性', max: 5 }, { key: 'novelty', label: '新颖性', max: 5 }] },
  ]
  if (!Object.keys(breakdown).length) return <p className="admin-note">评分构成未记录</p>
  return <div className="admin-score-breakdown">{groups.map(group => <section key={group.label}><div className="admin-section-heading"><h3>{group.label}</h3><strong>{typeof group.data.score === 'number' ? group.data.score.toFixed(1) : '未记录'}<small> / 100</small></strong></div>{group.fields.filter(field => typeof group.data[field.key] === 'number').map(field => { const number = group.data[field.key] as number; return <div className="admin-score-row" key={field.key}><span>{field.label}</span><div><i style={{ width: `${Math.max(0, Math.min(100, number / field.max * 100))}%` }} /></div><b>{number.toFixed(1)}<small> / {field.max}</small></b></div> })}</section>)}{typeof importance.reason === 'string' && importance.reason && <blockquote className="admin-evidence"><strong>评分理由</strong><p>{importance.reason}</p></blockquote>}<details className="admin-methodology"><summary>原始评分记录</summary><pre className="admin-json-detail">{JSON.stringify(value, null, 2)}</pre></details></div>
}
