import { useState } from 'react'
import { Alert, Button } from 'antd'

import type { AdminRange } from './adminFilters'
import { downloadHistoryCsv, type HistoryFilters } from './adminHistoryApi'

interface Props {
  resource: 'sources' | 'articles' | 'events'
  range: AdminRange
  filters: HistoryFilters
}

export default function HistoryExport({ resource, range, filters }: Props) {
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function download() {
    setLoading(true)
    setError(null)
    try {
      await downloadHistoryCsv(resource, range, filters)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '导出失败，请稍后重试。')
    } finally {
      setLoading(false)
    }
  }

  return <div className="admin-export-wrap">
    <Button className="admin-export" type="link" loading={loading} onClick={() => void download()}>导出 CSV</Button>
    {error && <Alert type="error" showIcon title={error} closable onClose={() => setError(null)} />}
  </div>
}
