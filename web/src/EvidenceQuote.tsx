export default function EvidenceQuote({
  quote,
  limited,
}: {
  quote?: string | null
  limited?: boolean
}) {
  return (
    <div className="mt-2 text-[11.5px] text-ink-4">
      {limited && <p className="mb-1">信息有限</p>}
      {quote ? (
        <details>
          <summary className="min-h-7 cursor-pointer text-accent-ink">
            原文依据
          </summary>
          <blockquote className="mt-1 whitespace-pre-wrap break-words border-l-2 border-line pl-2 leading-relaxed text-ink-3">
            {quote}
          </blockquote>
        </details>
      ) : (
        <p>历史版本，未附证据</p>
      )}
    </div>
  )
}
