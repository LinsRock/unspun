import { Button } from 'antd'
import type { ArticleRow, EventRow } from './adminHistoryApi'

export default function SelectionExport({ rows, onClear }: { rows: (ArticleRow | EventRow)[]; onClear: () => void }) {
  function download() {
    const cell = (value: unknown) => {
      const text = String(value ?? '')
      const safe = /^[\s]*[=+@-]/.test(text) ? `'${text}` : text
      return `"${safe.replaceAll('"', '""')}"`
    }
    const lines = [['ID', '标题', '类型', '来源', '状态'], ...rows.map(row => [row.id, 'title_zh' in row ? row.title_zh || row.title : row.title, 'source_id' in row ? '文章' : '事件', 'source_id' in row ? row.source_name || row.source_id : '', row.processing_status])]
    const url = URL.createObjectURL(new Blob(['\uFEFF' + lines.map(line => line.map(cell).join(',')).join('\r\n')], { type: 'text/csv;charset=utf-8' }))
    const link = document.createElement('a')
    link.href = url; link.download = 'unspun-selected-content.csv'; link.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  if (!rows.length) return null
  return <div className="admin-selection"><strong>已选择 {rows.length} 项</strong><span>仅当前页</span><Button size="small" onClick={download}>导出选中项</Button><Button type="text" size="small" onClick={onClear}>取消选择</Button></div>
}
