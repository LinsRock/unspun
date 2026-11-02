import { lazy, Suspense } from 'react'
import { Link, Navigate, NavLink, Route, Routes, useLocation } from 'react-router-dom'

import ReportPanel from './ReportPanel'
import ThemeToggle from './ThemeToggle'
import { ReaderSkeleton } from './reader/LoadingState'
import { useCapabilities } from './reader/capabilities'
import './reading.css'

const HybridPage = lazy(() => import('./reader/HybridPage'))
const TopicPage = lazy(() => import('./reader/TopicPage'))
const ReadingPage = lazy(() => import('./reader/ReadingPage'))
const ContentPage = lazy(() => import('./reader/ContentPage'))
const InterestsPage = lazy(() => import('./reader/InterestsPage'))

const AdminLayout = lazy(() => import('./admin/AdminLayout'))

export default function App() {
  const location = useLocation()
  const capabilities = useCapabilities()
  const hybrid = capabilities.data?.hybrid === true
  const discoverHome = capabilities.data?.home === 'discover'
  const navigation = [
    { to: hybrid ? '/discover' : '/reading', label: hybrid ? '发现' : '发现阅读', symbol: '◉' },
    { to: '/interests', label: '我的关注', symbol: '☆' },
    { to: '/admin', label: '管理后台', symbol: '▦' },
  ]
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
          {navigation.map(({ to, label, symbol }) => <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) => `${isActive ? 'active' : ''} ${to === '/admin' ? 'reading-mobile-admin' : ''}`}><span aria-hidden="true">{symbol}</span>{label}</NavLink>)}
        </nav>
        <div className="reading-sidebar-footer"><Link to="/admin">管理后台 <span aria-hidden="true">↗</span></Link><ThemeToggle /></div>
      </header>
      <main id="page-content" tabIndex={-1} className="reading-main">
        <div className="reading-topbar"><span>阅读空间 / {location.pathname.startsWith('/topics/') ? '话题详情' : location.pathname === '/discover' || location.pathname === '/' && discoverHome ? '发现' : location.pathname.startsWith('/reading') ? '独立阅读' : location.pathname === '/interests' ? '我的关注' : '阅读'}</span></div>
        <div className="reading-page">
          <Suspense fallback={<ReaderSkeleton layout={location.pathname.startsWith('/reading/') ? 'detail' : location.pathname === '/interests' ? 'interests' : 'feed'} label="正在打开阅读空间" />}>
          <Routes>
            <Route path="/discover" element={<HybridPage />} />
            <Route path="/topics/:id" element={<TopicPage />} />
            <Route path="/reading" element={<ReadingPage />} />
            <Route path="/reading/:id" element={<ContentPage />} />
            <Route path="/interests" element={<InterestsPage />} />
            <Route path="/" element={capabilities.isPending && capabilities.fetchStatus !== 'paused' ? <ReaderSkeleton /> : <Navigate to={discoverHome ? '/discover' : '/reading'} replace />} />
            {['/history/*', '/events/*', '/digest/*'].map(path => <Route key={path} path={path} element={<Navigate to="/" replace />} />)}
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
                    返回首页
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
