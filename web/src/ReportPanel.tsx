import { useQuery } from '@tanstack/react-query'

import { fetchReport } from './api'

const REFRESH_INTERVAL_MS = 5 * 60 * 1000

function Stat({ label, value, tone }: { label: string; value: string | number; tone?: 'good' | 'bad' }) {
  const toneClass = tone === 'bad' ? 'text-hot' : tone === 'good' ? 'text-ok' : ''
  return (
    <div className="rounded-card border border-line bg-surface-2 px-3.5 py-2.5">
      <div className="text-[11.5px] text-ink-4">{label}</div>
      <div className={`mt-0.5 font-mono text-[21px] font-bold tabular-nums ${toneClass}`}>{value}</div>
    </div>
  )
}

function SectionH({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="mb-1.5 mt-5 flex items-center gap-2 text-[13px] font-bold tracking-[0.06em] text-ink-3 after:h-px after:flex-1 after:bg-line after:content-['']">
      {children}
    </h3>
  )
}

function StatusDot({ bad = false }: { bad?: boolean }) {
  return (
    <span
      className={`mr-1.5 inline-block h-[7px] w-[7px] rounded-full ${bad ? 'bg-hot' : 'bg-ok'}`}
    />
  )
}

const TH = 'whitespace-nowrap border-b border-line px-3.5 py-2 text-left text-[11px] font-semibold tracking-[0.05em] text-ink-4'
const TD = 'whitespace-nowrap border-b border-line px-3.5 py-[7px]'
const TD_NUM = `${TD} font-mono tabular-nums`

export default function ReportPanel() {
  const { data, error, isPending } = useQuery({
    queryKey: ['report'],
    queryFn: fetchReport,
    refetchInterval: REFRESH_INTERVAL_MS,
  })

  return (
    <section className="mb-4 rounded-card border border-line bg-surface px-4 py-3.5 shadow-card">
      <h2 className="flex items-baseline gap-2 text-sm font-bold">
        运行报告
        <span className="font-mono text-[11px] font-normal tabular-nums text-ink-4">近 24 小时</span>
      </h2>
      {isPending && <p className="mt-2 text-xs text-ink-3">加载中…</p>}
      {error != null && <p className="mt-2 text-xs text-hot">报告加载失败</p>}
      {data && (
        <div>
          <div className="mt-3 grid grid-cols-2 gap-2.5 sm:grid-cols-4">
            <Stat label="抓取轮次" value={data.fetch_runs} />
            <Stat label="新文章" value={data.new_articles} />
            <Stat
              label="失败源"
              value={data.source_failures.length}
              tone={data.source_failures.length > 0 ? 'bad' : undefined}
            />
            {/* No budget threshold in the response, so the cost stays neutral
                (semantic colors are reserved for actual good/bad states). */}
            <Stat label="LLM 花费" value={`$${data.llm_cost_total_usd.toFixed(4)}`} />
          </div>
          <SectionH>抓取失败的源</SectionH>
          {data.source_failures.length > 0 ? (
            <div className="overflow-x-auto rounded-card border border-line bg-surface-2">
              <table className="w-full border-collapse text-[12.5px] [&_tr:last-child_td]:border-b-0">
                <thead>
                  <tr>
                    <th className={TH}>源</th>
                    <th className={TH}>连续失败</th>
                    <th className={TH}>错误</th>
                  </tr>
                </thead>
                <tbody>
                  {data.source_failures.map((f) => (
                    <tr key={f.source_id}>
                      <td className={TD}>
                        <StatusDot bad />
                        {f.source_id}
                      </td>
                      <td className={TD_NUM}>{f.failures} 次</td>
                      <td className={`${TD} text-ink-3`}>{f.last_error ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-xs text-ink-3">
              <StatusDot />
              所有源抓取正常
            </p>
          )}
          {data.llm_spend.length > 0 && (
            <>
              <SectionH>LLM 用量</SectionH>
              <div className="overflow-x-auto rounded-card border border-line bg-surface-2">
                <table className="w-full border-collapse text-[12.5px] [&_tr:last-child_td]:border-b-0">
                  <thead>
                    <tr>
                      <th className={TH}>阶段</th>
                      <th className={TH}>模型</th>
                      <th className={TH}>调用</th>
                      <th className={TH}>tokens</th>
                      <th className={TH}>花费</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.llm_spend.map((s) => (
                      <tr key={`${s.purpose}-${s.model}`}>
                        <td className={TD}>{s.purpose}</td>
                        <td className={TD}>{s.model}</td>
                        <td className={TD_NUM}>{s.calls}</td>
                        <td className={TD_NUM}>
                          {(s.prompt_tokens + s.completion_tokens).toLocaleString('en-US')}
                        </td>
                        <td className={TD_NUM}>${s.cost_usd.toFixed(4)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
          {/* Guard: an older API during a rolling deploy may omit these fields. */}
          {data.backlog != null && (
            <div>
              <SectionH>管线积压</SectionH>
              <p className="font-mono text-xs tabular-nums text-ink-2">
                待摘要 {data.backlog.pending_summaries} 篇 · 待 embedding{' '}
                {data.backlog.pending_embeddings} 篇 · 待评分事件 {data.backlog.pending_scores} 个
              </p>
              {data.backlog.abandoned_total > 0 && (
                <div className="mt-2">
                  <h4 className="text-xs font-semibold text-ink-2">
                    已放弃的文章（摘要连续失败，共 {data.backlog.abandoned_total} 篇）
                  </h4>
                  <ul className="mt-1 space-y-0.5 text-xs text-ink-3">
                    {data.backlog.abandoned_articles.map((a) => (
                      <li key={a.id}>
                        #{a.id} · {a.source_id} · {a.title}
                      </li>
                    ))}
                  </ul>
                  {data.backlog.abandoned_total > data.backlog.abandoned_articles.length && (
                    <p className="mt-1 text-xs text-ink-4">
                      仅显示最新 {data.backlog.abandoned_articles.length} 篇
                    </p>
                  )}
                </div>
              )}
            </div>
          )}
          <div>
            <SectionH>最近一轮处理量</SectionH>
            {data.last_run ? (
              <p className="font-mono text-xs tabular-nums text-ink-2">
                摘要 {data.last_run.summarized} · embedding {data.last_run.embedded} · 聚类{' '}
                {data.last_run.clustered} · 新事件 {data.last_run.new_events} · 评分{' '}
                {data.last_run.scored} ·{' '}
                <span className="text-ink-4">
                  {new Date(data.last_run.run_at).toLocaleString('zh-CN', { hour12: false })}
                </span>
              </p>
            ) : (
              <p className="text-xs text-ink-3">AI 阶段尚未运行过</p>
            )}
          </div>
        </div>
      )}
    </section>
  )
}
