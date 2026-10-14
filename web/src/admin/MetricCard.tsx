import { Link, type To } from 'react-router-dom'

export default function MetricCard({ label, value, note, to }: { label: string; value: string; note?: string; to: To }) {
  return <Link className="admin-metric" to={to} aria-label={`${label}：${value}`}>
    <span>{label}<span aria-hidden="true">↗</span></span><strong>{value}</strong>{note && <small>{note}</small>}
  </Link>
}
