import { useQuery } from '@tanstack/react-query'

import { fetchReport } from './api'

export default function ReportPanel() {
  const { data, error, isPending } = useQuery({ queryKey: ['report'], queryFn: fetchReport })

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
        </div>
      )}
    </section>
  )
}
