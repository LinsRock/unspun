import type { ReactNode } from 'react'
import './reader.css'

export function LoadingStatus({ children }: { children: ReactNode }) {
  return <span className="r1-loading-status" role="status"><span className="r1-spinner" aria-hidden="true" />{children}</span>
}

export function ReaderSkeleton({ layout = 'feed', label = '正在加载阅读内容' }: { layout?: 'feed' | 'detail' | 'interests'; label?: string }) {
  return <div className={`r1-skeleton r1-skeleton-${layout}`} role="status" aria-label={label} aria-busy="true">
    <span className="sr-only">{label}</span>
    <div aria-hidden="true">{Array.from({ length: layout === 'detail' ? 1 : 3 }, (_, index) => <div className="r1-skeleton-card" key={index}>
      <div className="r1-skeleton-bar r1-skeleton-meta" />
      <div className="r1-skeleton-bar r1-skeleton-title" />
      <div className="r1-skeleton-bar r1-skeleton-line" />
      <div className="r1-skeleton-bar r1-skeleton-line r1-skeleton-short" />
      {layout === 'detail' && <div className="r1-skeleton-body">{Array.from({ length: 6 }, (_, line) => <div className="r1-skeleton-bar r1-skeleton-line" key={line} />)}</div>}
      <div className="r1-skeleton-bar r1-skeleton-meta r1-skeleton-footer" />
    </div>)}</div>
  </div>
}
