import { ArrowRightOutlined, WarningOutlined, CheckCircleOutlined } from '@ant-design/icons'
import { Link, type To } from 'react-router-dom'
import type { OverviewData } from './overviewApi'

type Target = (path: string, params?: Record<string, string>) => To
export function AttentionQueue({ data, target }: { data: OverviewData; target: Target }) {
  const failed = data.current.backlog.abandoned_summaries
  const errors = data.current.source_health.error
  return <section className={`admin-attention ${errors + failed ? 'has-issues' : ''}`} aria-label="需要关注">
    <div>{errors + failed ? <WarningOutlined /> : <CheckCircleOutlined />}<strong>{errors + failed ? '需要关注' : '当前没有已记录的失败项'}</strong><span>当前状态</span></div>
    <div className="admin-attention-actions">{errors > 0 && <Link to={target('/admin/sources', { health: 'error' })}><b>{errors}</b> 个来源最近抓取失败<ArrowRightOutlined /></Link>}{failed > 0 && <Link to={target('/admin/runs', { tab: 'backlog', stage: 'abandoned_summary' })}><b>{failed}</b> 篇摘要达到重试上限<ArrowRightOutlined /></Link>}{errors + failed === 0 && <span>可继续查看产出与积压；这不代表实时管线健康。</span>}</div>
  </section>
}
export function SourceHealth({ data, target }: { data: OverviewData; target: Target }) {
  const health = data.current.source_health
  const total = health.ok + health.error + health.no_runs
  const segments = [{ key: 'ok', label: '最近成功', count: health.ok, color: 'var(--ok)' }, { key: 'error', label: '最近失败', count: health.error, color: 'var(--hot)' }, { key: 'no_runs', label: '从未抓取', count: health.no_runs, color: 'var(--ink-4)' }]
  return <section className="admin-panel admin-health"><div className="admin-section-heading"><h2>信息源健康</h2><span className="admin-scope">当前</span></div><div className="admin-health-number"><strong>{health.ok}</strong><span>/ {total} 个有状态的来源</span></div><p className="admin-note">最近一次抓取成功</p><div className="admin-distribution" aria-label={`成功 ${health.ok}，失败 ${health.error}，从未抓取 ${health.no_runs}`}>{segments.map(item => <span key={item.key} style={{ width: `${total ? item.count / total * 100 : 0}%`, background: item.color }} />)}</div><div className="admin-health-legend">{segments.map(item => <Link key={item.key} to={target('/admin/sources', { health: item.key })}><i style={{ background: item.color }} />{item.label}<strong>{item.count}</strong><ArrowRightOutlined /></Link>)}</div><div className="admin-health-footer">期间有产出 <b>{data.period.sources.productive_sources}</b> 个来源 <Link to={target('/admin/sources')}>查看全部 ↗</Link></div></section>
}
export function PipelineBacklog({ data, target }: { data: OverviewData; target: Target }) {
  const backlog = data.current.backlog
  const stages = [{ label: '待摘要', value: backlog.pending_summaries, stage: 'pending_summary', caption: '文章' }, { label: '待 Embedding', value: backlog.pending_embeddings, stage: 'pending_embedding', caption: '文章' }, { label: '待评分', value: backlog.pending_scores, stage: 'pending_score', caption: '事件' }, { label: '摘要失败上限', value: backlog.abandoned_summaries, stage: 'abandoned_summary', caption: '需检查' }]
  return <section className="admin-panel admin-pipeline"><div className="admin-section-heading"><h2>处理队列 <small>当前积压</small></h2><Link to={target('/admin/runs', { tab: 'backlog' })}>查看队列 <ArrowRightOutlined /></Link></div><div className="admin-pipeline-stages">{stages.map((stage, index) => <Link className={index === 3 && stage.value ? 'is-error' : ''} key={stage.stage} to={target('/admin/runs', { tab: 'backlog', stage: stage.stage })}><span><small>0{index + 1}</small>{stage.label}<ArrowRightOutlined /></span><strong>{stage.value.toLocaleString()}<small>{stage.caption}</small></strong></Link>)}</div><p className="admin-note">文章与事件是不同对象；这里展示队列积压，不表示各阶段转化率。</p></section>
}
