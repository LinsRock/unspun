import { lazy, Suspense } from 'react'
import { Link, NavLink, Route, Routes, useLocation } from 'react-router-dom'

import DigestPage from './DigestPage'
import FeedPage from './FeedPage'
import ReportPanel from './ReportPanel'
import ThemeToggle from './ThemeToggle'
import './reading.css'

const ReadingPage = lazy(() => import('./reader/ReadingPage'))
const ContentPage = lazy(() => import('./reader/ContentPage'))
const InterestsPage = lazy(() => import('./reader/InterestsPage'))

const AdminLayout = lazy(() => import('./admin/AdminLayout'))

const pages = [
  { to: '/reading', label: '发现阅读', symbol: '◉' },
  { to: '/interests', label: '我的关注', symbol: '☆' },
  { to: '/', label: '实时事件流', symbol: '▤' },
  { to: '/digest', label: '每日日报', symbol: '▥' },
  { to: '/admin', label: '管理后台', symbol: '▦' },
]

export default function App() {
  const location = useLocation()
  if (location.pathname === '/admin' || location.pathname.startsWith('/admin/')) {
    return <Suspense fallback={<p role="status">正在打开管理后台…</p>}><AdminLayout /></Suspense>
  }
  return (
    <div className="min-h-screen">
      <a
        href="#page-content"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:bg-surface focus:p-3"
      >
        跳到内容
      </a>
      <header className="reading-sidebar">
        <Link to="/" className="reading-brand" aria-label="Unspun 首页"><span className="reading-brand-mark">u<span>↗</span></span><strong>unspun<small>INTELLIGENCE</small></strong></Link>
        <p className="reading-sidebar-note">个人情报站 · 让信息回归全貌</p>
        <nav aria-label="主导航" className="reading-nav">
          {pages.map(({ to, label, symbol }) => <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => `${isActive ? 'active' : ''} ${to === '/admin' ? 'reading-mobile-admin' : ''}`}><span aria-hidden="true">{symbol}</span>{label}</NavLink>)}
        </nav>
        <div className="reading-sidebar-footer"><Link to="/admin">管理后台 <span aria-hidden="true">↗</span></Link><ThemeToggle /></div>
      </header>
      <main id="page-content" className="reading-main">
        <div className="reading-topbar"><span>阅读空间 / {location.pathname.startsWith('/reading') ? '发现阅读' : location.pathname === '/interests' ? '我的关注' : location.pathname === '/digest' ? '每日日报' : '实时事件流'}</span><span>中文阅读 · 原文可溯</span></div>
        <div className="reading-page">
          <Suspense fallback={<p role="status">正在打开阅读空间…</p>}>
          <Routes>
            <Route path="/reading" element={<ReadingPage />} />
            <Route path="/reading/:id" element={<ContentPage />} />
            <Route path="/interests" element={<InterestsPage />} />
            <Route path="/" element={<FeedPage />} />
            <Route path="/digest" element={<DigestPage />} />
            <Route
              path="/report"
              element={
                <>
                  <h1 className="mb-2 text-xl font-bold">运行报告</h1>
                  <Link to="/admin" className="mb-4 inline-block text-accent-ink hover:underline">进入管理后台</Link>
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
          </Suspense>
        </div>
      </main>
    </div>
  )
}
