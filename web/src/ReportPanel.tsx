import { useQuery } from '@tanstack/react-query'

import { fetchReport } from './api'

const REFRESH_INTERVAL_MS = 5 * 60 * 1000

export default function ReportPanel() {
  const { data, error, isPending } = useQuery({
    queryKey: ['report'],
    queryFn: fetchReport,
    refetchInterval: REFRESH_INTERVAL_MS,
  })

  return (
    <section className="mb-4 rounded-xl border border-gray-200 bg-gray-50 p-4 text-sm">
      <h2 className="mb-2 font-semibold">运行报告（近 24 小时）</h2>
      {isPending && <p className="text-gray-500">加载中…</p>}
      {error != null && <p className="text-red-600">报告加载失败</p>}
      {data && (
        <div className="space-y-2">
          <p className="text-gray-600">
            抓取 {data.fetch_runs} 次 · 新文章 {data.new_articles} 篇 · LLM 花费 $
            {data.llm_cost_total_usd.toFixed(4)}
          </p>
          {data.source_failures.length > 0 ? (
            <div>
              <h3 className="font-medium text-gray-700">抓取失败的源</h3>
              <ul className="mt-1 space-y-0.5 text-xs text-gray-600">
                {data.source_failures.map((f) => (
                  <li key={f.source_id}>
                    {f.source_id} · {f.failures} 次
                    {f.last_error && <span className="text-gray-400">（{f.last_error}）</span>}
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="text-xs text-gray-500">所有源抓取正常</p>
          )}
          {data.llm_spend.length > 0 && (
            <div>
              <h3 className="font-medium text-gray-700">LLM 用量</h3>
              <ul className="mt-1 space-y-0.5 text-xs text-gray-600">
                {data.llm_spend.map((s) => (
                  <li key={`${s.purpose}-${s.model}`}>
                    {s.purpose} · {s.model} · {s.calls} 次 · ${s.cost_usd.toFixed(4)}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {/* Guard: an older API during a rolling deploy may omit these fields. */}
          {data.backlog != null && (
            <div>
              <h3 className="font-medium text-gray-700">管线积压</h3>
              <p className="mt-1 text-xs text-gray-600">
                待摘要 {data.backlog.pending_summaries} 篇 · 待 embedding{' '}
                {data.backlog.pending_embeddings} 篇 · 待评分事件 {data.backlog.pending_scores} 个
              </p>
              {data.backlog.abandoned_total > 0 && (
                <div className="mt-1">
                  <h4 className="text-xs font-medium text-gray-700">
                    已放弃的文章（摘要连续失败，共 {data.backlog.abandoned_total} 篇）
                  </h4>
                  <ul className="mt-0.5 space-y-0.5 text-xs text-gray-600">
                    {data.backlog.abandoned_articles.map((a) => (
                      <li key={a.id}>
                        #{a.id} · {a.source_id} · {a.title}
                      </li>
                    ))}
                  </ul>
                  {data.backlog.abandoned_total > data.backlog.abandoned_articles.length && (
                    <p className="mt-0.5 text-xs text-gray-400">
                      仅显示最新 {data.backlog.abandoned_articles.length} 篇
                    </p>
                  )}
                </div>
              )}
            </div>
          )}
          <div>
            <h3 className="font-medium text-gray-700">最近一轮处理量</h3>
            {data.last_run ? (
              <p className="mt-1 text-xs text-gray-600">
                摘要 {data.last_run.summarized} · embedding {data.last_run.embedded} · 聚类{' '}
                {data.last_run.clustered} · 新事件 {data.last_run.new_events} · 评分{' '}
                {data.last_run.scored} ·{' '}
                <span className="text-gray-400">
                  {new Date(data.last_run.run_at).toLocaleString()}
                </span>
              </p>
            ) : (
              <p className="mt-1 text-xs text-gray-500">AI 阶段尚未运行过</p>
            )}
          </div>
        </div>
      )}
    </section>
  )
}
