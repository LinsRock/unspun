import { Link, NavLink, Route, Routes } from 'react-router-dom'

import DigestPage from './DigestPage'
import FeedPage from './FeedPage'
import ReportPanel from './ReportPanel'
import ThemeToggle from './ThemeToggle'

const pages = [
  { to: '/', label: '实时事件流', symbol: '▤' },
  { to: '/digest', label: '每日日报', symbol: '▥' },
  { to: '/report', label: '运行报告', symbol: '▦' },
]

export default function App() {
  return (
    <div className="min-h-screen">
      <a
        href="#page-content"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:bg-surface focus:p-3"
      >
        跳到内容
      </a>
      <header className="flex items-center justify-between gap-3 border-b border-line bg-surface-2 px-4 py-4 lg:fixed lg:inset-y-0 lg:left-0 lg:w-[216px] lg:flex-col lg:items-stretch lg:justify-start lg:border-b-0 lg:border-r lg:px-5 lg:py-7">
        <div>
          <div className="text-[18px] font-bold tracking-[0.02em]">
            <span className="text-accent">U</span>nspun
          </div>
          <div className="hidden text-[11px] text-ink-4 lg:block">
            个人情报站 · 让信息回归全貌
          </div>
        </div>
        <nav
          aria-label="主导航"
          className="fixed inset-x-0 bottom-0 z-20 flex border-t border-line bg-surface-2 pb-[env(safe-area-inset-bottom)] lg:static lg:mt-8 lg:flex-col lg:gap-1 lg:border-t-0 lg:pb-0"
        >
          {pages.map(({ to, label, symbol }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `flex min-h-14 flex-1 flex-col items-center justify-center gap-0.5 px-2 py-2 text-[11.5px] transition-colors lg:min-h-11 lg:flex-row lg:justify-start lg:gap-2.5 lg:rounded-ctl lg:px-3 lg:text-[13px] ${isActive ? 'bg-accent-soft font-semibold text-accent-ink' : 'text-ink-3 hover:bg-bg-sunk hover:text-ink'}`
              }
            >
              <span aria-hidden="true" className="text-lg leading-none">
                {symbol}
              </span>
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="lg:mt-auto lg:border-t lg:border-line lg:pt-4">
          <ThemeToggle />
        </div>
      </header>
      <main
        id="page-content"
        className="min-w-0 px-4 pb-[calc(88px+env(safe-area-inset-bottom))] pt-6 sm:px-6 lg:ml-[216px] lg:px-10 lg:py-8"
      >
        <div className="mx-auto max-w-[900px]">
          <Routes>
            <Route path="/" element={<FeedPage />} />
            <Route path="/digest" element={<DigestPage />} />
            <Route
              path="/report"
              element={
                <>
                  <h1 className="mb-4 text-xl font-bold">运行报告</h1>
                  <ReportPanel />
                </>
              }
            />
            <Route
              path="*"
              element={
                <>
                  <h1 className="text-xl font-bold">页面不存在</h1>
                  <Link
                    to="/"
                    className="mt-3 inline-block text-accent-ink hover:underline"
                  >
                    返回实时事件流
                  </Link>
                </>
              }
            />
          </Routes>
        </div>
      </main>
    </div>
  )
}
