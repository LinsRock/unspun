// Section heading with a trailing hairline rule (DESIGN.md section-h).
export default function SectionHeading({
  children,
  className = '',
}: {
  children: React.ReactNode
  className?: string
}) {
  return (
    <h3
      className={`flex items-center gap-2 text-[13px] font-bold tracking-[0.06em] text-ink-3 after:h-px after:flex-1 after:bg-line after:content-[''] ${className}`}
    >
      {children}
    </h3>
  )
}
