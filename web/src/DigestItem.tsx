import type { EventOut } from './api'
import { safeHref } from './links'

export default function DigestItem({
  event,
  rank,
}: {
  event: EventOut
  rank: number
}) {
  const score = event.score_decayed ?? event.score_final
  const rounded = score == null ? null : Math.round(score)
  const rankTone =
    rank === 1
      ? 'text-hot'
      : rank === 2
        ? 'text-amber'
        : rank === 3
          ? 'text-ink-2'
          : 'text-ink-4'
  const scoreTone =
    rounded != null && rounded >= 80
      ? 'bg-hot-soft text-hot'
      : rounded != null && rounded >= 65
        ? 'bg-amber-soft text-amber'
        : 'bg-bg-sunk text-ink-3'
  const byId = new Map(event.articles.map((article) => [article.id, article]))
  const claims =
    event.viewpoint?.claims.flatMap((claim, index) => {
      const article = byId.get(claim.article_id)
      return article ? [{ claim, article, index }] : []
    }) ?? []
  const indexes = new Set(claims.map((claim) => claim.index))
  const disagreements =
    event.viewpoint?.disagreements.filter(
      (point) =>
        new Set(point.claim_indexes.filter((index) => indexes.has(index)))
          .size >= 2,
    ) ?? []
  return (
    <article className="flex gap-3 border-b border-line py-4 last:border-b-0">
      <span
        className={`w-6 shrink-0 pt-0.5 text-center font-mono text-[15px] font-bold tabular-nums ${rankTone}`}
      >
        {String(rank).padStart(2, '0')}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-start gap-2.5">
          <h2 className="min-w-0 flex-1 break-words text-[15px] font-[650] leading-normal">
            {event.title ?? '未命名事件'}
          </h2>
          {rounded != null && (
            <span
              title="生成时的衰减热度"
              className={`shrink-0 rounded-ctl px-2 py-0.5 font-mono text-sm font-bold tabular-nums ${scoreTone}`}
            >
              {rounded}
            </span>
          )}
        </div>
        {event.summary_zh && (
          <p className="mt-1.5 break-words text-[13.5px] leading-[1.8] text-ink-2">
            {event.summary_zh}
          </p>
        )}
        {claims.length > 0 && (
          <div className="mt-2 rounded-ctl bg-accent-soft px-3 py-2.5 text-[12.5px] leading-[1.8] text-ink-2">
            <div className="mb-1 text-[11px] font-semibold text-accent-ink">
              观点摘录
            </div>
            {claims.map(({ claim, article }) => {
              const href = safeHref(article.url)
              const content = (
                <>
                  <b className="font-semibold">{article.source_name}</b>
                  <span className="ml-1.5">{claim.claim}</span>
                </>
              )
              return (
                <p key={claim.article_id} className="break-words">
                  {href ? (
                    <a
                      href={href}
                      target="_blank"
                      rel="noreferrer"
                      className="hover:underline"
                    >
                      {content}
                    </a>
                  ) : (
                    <span>{content}</span>
                  )}
                </p>
              )
            })}
            {disagreements.map((point, index) => (
              <p
                key={`${index}-${point.point}`}
                className="mt-1.5 border-t border-line pt-1.5"
              >
                <b className="font-semibold">分歧焦点：</b>
                {point.point}
              </p>
            ))}
          </div>
        )}
        <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs">
          {event.articles.map((article) => {
            const href = safeHref(article.url)
            return (
              <li key={article.id} className="min-w-0 max-w-full">
                {href ? (
                  <a
                    href={href}
                    target="_blank"
                    rel="noreferrer"
                    className="block truncate text-accent-ink hover:underline"
                    title={article.title_zh ?? article.title}
                  >
                    {article.source_name} ↗
                  </a>
                ) : (
                  <span className="text-ink-4">{article.source_name}</span>
                )}
              </li>
            )
          })}
        </ul>
      </div>
    </article>
  )
}
