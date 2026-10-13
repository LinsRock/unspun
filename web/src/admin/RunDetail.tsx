import { Descriptions, Drawer, Empty } from 'antd'
import { useQuery } from '@tanstack/react-query'

import { fetchAdmin, type RunRecord } from './adminApi'

export default function RunDetail({ id, onClose }: { id: number | null; onClose: () => void }) {
  const query = useQuery({ queryKey: ['admin', 'run', id], queryFn: ({ signal }) => fetchAdmin<RunRecord>(`runs/${id}`, undefined, signal), enabled: id !== null, retry: false })
  const run = query.data
  return <Drawer title={id === null ? '' : `运行 #${id}`} open={id !== null} onClose={onClose} size={520} className="admin-run-detail">
    {query.isPending && <p>正在加载运行详情…</p>}
    {query.isError && <p role="alert">运行详情加载失败，请关闭后重试。</p>}
    {run && <>
      <Descriptions column={1} bordered size="small" items={[
        { key: 'run_at', label: '记录时间', children: new Date(run.run_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' }) },
        { key: 'status', label: '整轮状态', children: run.status ?? '未记录' },
        { key: 'ended_at', label: '结束时间', children: run.ended_at ?? '未记录' },
        { key: 'duration', label: '耗时', children: run.duration_seconds === null ? '未记录' : `${run.duration_seconds} 秒` },
        { key: 'summary', label: '摘要处理量', children: run.summarized },
        { key: 'embedding', label: 'Embedding 处理量', children: run.embedded },
        { key: 'cluster', label: '聚类处理量', children: run.clustered },
        { key: 'events', label: '新事件', children: run.new_events },
        { key: 'score', label: '评分处理量', children: run.scored },
        { key: 'cost', label: '关联费用', children: run.cost_usd === null ? '未记录' : `$${run.cost_usd}` },
      ]} />
      <Empty description="历史阶段状态与错误未记录；处理量不能证明整轮成功。" />
    </>}
  </Drawer>
}
