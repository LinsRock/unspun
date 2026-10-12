import { DatePicker, Select } from 'antd'
import dayjs from 'dayjs'
import 'dayjs/locale/zh-cn'

import { periodLabels, presetRange, type AdminRange, type Period } from './adminFilters'

dayjs.locale('zh-cn')

interface Props {
  range: AdminRange
  onApply: (range: AdminRange) => void
}

export default function DateRange({ range, onApply }: Props) {
  const start = dayjs(range.start).tz('Asia/Shanghai')
  const end = dayjs(new Date(Date.parse(range.end) - 1)).tz('Asia/Shanghai')

  return (
    <div className="admin-date-range">
      <label htmlFor="admin-period">时间范围</label>
      <Select
        id="admin-period"
        aria-label="快捷时间范围"
        value={range.period}
        options={Object.entries(periodLabels).map(([key, label]) => ({
          value: key as Period,
          label,
          disabled: key === 'custom',
        }))}
        onChange={(value: Period) => {
          if (value !== 'custom') onApply(presetRange(value))
        }}
      />
      <DatePicker.RangePicker
        key={`${range.start}-${range.end}`}
        aria-label="自定义日期范围"
        value={[start, end]}
        needConfirm
        allowClear={false}
        format="YYYY-MM-DD"
        maxDate={dayjs().tz('Asia/Shanghai')}
        onChange={(dates) => {
          if (!dates?.[0] || !dates[1]) return
          const startMs = dayjs.tz(`${dates[0].format('YYYY-MM-DD')}T00:00:00`, 'Asia/Shanghai').valueOf()
          const endMs = dayjs.tz(`${dates[1].add(1, 'day').format('YYYY-MM-DD')}T00:00:00`, 'Asia/Shanghai').valueOf()
          const nowMs = Date.now()
          if (startMs >= Math.min(endMs, nowMs)) return
          onApply({
            period: 'custom',
            start: new Date(startMs).toISOString(),
            end: new Date(Math.min(endMs, nowMs)).toISOString(),
          })
        }}
        renderExtraFooter={() => <span>北京时间 · 分别选择起止日期并确认；关闭日历不改变查询</span>}
      />
    </div>
  )
}
