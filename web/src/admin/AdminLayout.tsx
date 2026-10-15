import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, ConfigProvider, theme as antdTheme } from 'antd'
import { AppstoreOutlined, FileTextOutlined, GlobalOutlined, DeploymentUnitOutlined, WalletOutlined, SettingOutlined, SearchOutlined, ReloadOutlined, ArrowUpOutlined } from '@ant-design/icons'
import WorkspaceSearch from './WorkspaceSearch'
import zhCN from 'antd/locale/zh_CN'
import { useEffect, useState } from 'react'
import { Link, NavLink, useLocation, useSearchParams } from 'react-router-dom'

import ThemeToggle from '../ThemeToggle'
import { fetchAdminRange } from './adminApi'
import ContentPage from './ContentPage'
import DateRange from './DateRange'
import SourcesPage from './SourcesPage'
import RunsPage from './RunsPage'
import ConfigurationPage from './ConfigurationPage'
import CostsPage from './CostsPage'
import OverviewPage from './OverviewPage'
import { parseRange, presetRange, rangeSearch, type AdminRange } from './adminFilters'
import './admin.css'

const pages = [
  { path: '/admin', label: '运营总览', icon: AppstoreOutlined, description: '把握产出、异常与成本，找到下一步行动。' },
  { path: '/admin/content', label: '内容工作区', icon: FileTextOutlined, description: '从原始报道到事件，追溯内容与证据。' },
  { path: '/admin/sources', label: '信息源', icon: GlobalOutlined, description: '查看来源配置、采集结果与抓取异常。' },
  { path: '/admin/runs', label: '运行与任务', icon: DeploymentUnitOutlined, description: '追踪处理轮次，定位当前积压和失败对象。' },
  { path: '/admin/costs', label: '费用与预算', icon: WalletOutlined, description: '查看运行费用、付款记录和本月模型预算。' },
  { path: '/admin/configuration', label: '配置与审计', icon: SettingOutlined, description: '查看当前部署配置、模型路由与运行约束。' },
] as const

function readThemeColors() {
  const style = getComputedStyle(document.documentElement)
  const dark = style.colorScheme.includes('dark')
  const token = (name: string, fallback: string) => style.getPropertyValue(name).trim() || fallback
  return {
    dark, accent: token('--accent', '#5067bd'), accentContrast: token('--accent-contrast', '#ffffff'),
    surface: token('--surface', '#ffffff'), muted: token('--ink-3', '#707b8e'), secondarySurface: token('--surface-2', '#f3f5f8'), ink: token('--ink', '#242b3a'), line: token('--line', '#e3e7ee'),
  }
}

export default function AdminLayout() {
  const queryClient = useQueryClient()
  const [mobile, setMobile] = useState(() => window.innerWidth <= 700)
  const [searchOpen, setSearchOpen] = useState(false)
  const [colors, setColors] = useState(readThemeColors)
  const location = useLocation()
  const [search, setSearch] = useSearchParams()
  const [openedAt, setOpenedAt] = useState(() => new Date())
  const range = parseRange(search, openedAt)
  const page = pages.find((entry) => entry.path === location.pathname)
  const query = useQuery({
    queryKey: ['admin', 'range', range.start, range.end],
    queryFn: ({ signal }) => fetchAdminRange(range, signal),
    retry: false,
    enabled: Boolean(page) && page?.path !== '/admin/configuration',
  })

  useEffect(() => {
    const viewport = window.matchMedia('(max-width: 700px)')
    const updateViewport = () => setMobile(viewport.matches)
    viewport.addEventListener('change', updateViewport)
    const shortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); setSearchOpen(value => !value) }
    }
    window.addEventListener('keydown', shortcut)
    return () => { window.removeEventListener('keydown', shortcut); viewport.removeEventListener('change', updateViewport) }
  }, [])

  useEffect(() => {
    const refreshColors = () => setColors(readThemeColors())
    const observer = new MutationObserver(refreshColors)
    const systemTheme = window.matchMedia?.('(prefers-color-scheme: dark)')
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    systemTheme?.addEventListener('change', refreshColors)
    return () => {
      observer.disconnect()
      systemTheme?.removeEventListener('change', refreshColors)
    }
  }, [])

  function applyRange(next: AdminRange) {
    setOpenedAt(new Date())
    const params = rangeSearch(search, next)
    params.delete('page')
    setSearch(params)
  }

  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        algorithm: colors.dark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
        token: {
          colorPrimary: colors.accent,
          colorLink: colors.accent, colorLinkHover: colors.accent, colorLinkActive: colors.accent,
          colorTextSecondary: colors.muted, colorBorderSecondary: colors.line,
          colorBgLayout: colors.secondarySurface, colorFillAlter: colors.secondarySurface,
          colorTextLightSolid: colors.accentContrast,
          colorBgContainer: colors.surface,
          colorBgElevated: colors.surface,
          colorText: colors.ink,
          colorBorder: colors.line,
          borderRadius: 6, controlHeight: 34, fontSize: 13,
          fontFamily: '-apple-system, BlinkMacSystemFont, PingFang SC, sans-serif',
        },
        components: { Table: { headerBg: colors.dark ? '#252d3d' : '#f3f5f8', cellPaddingBlock: 13, cellPaddingInline: 14 }, Tabs: { horizontalItemGutter: 28 },
        },
      }}
    >
      <div className="admin-workspace">
        <a href="#admin-content" className="sr-only focus:not-sr-only">跳到后台内容</a>
        <aside className="admin-sidebar">
          <Link to={{ pathname: '/admin', search: rangeSearch(new URLSearchParams(), range).toString() }} className="admin-brand"><span className="admin-brand-mark">u<span>↗</span></span><strong>unspun<span>OPERATIONS</span></strong></Link>
          <div className="admin-workspace-label"><span className="admin-dot" />个人情报工作站<small>工作区</small></div>
          <nav aria-label="后台导航">
            <span className="admin-nav-caption">运营</span>
            {pages.map((entry, index) => <div key={entry.path}>
              {index === 5 && <span className="admin-nav-caption admin-nav-system">系统</span>}
              <NavLink end to={{ pathname: entry.path, search: rangeSearch(new URLSearchParams(), range).toString() }} className={({ isActive }) => isActive ? 'admin-nav-link active' : 'admin-nav-link'}>
                <entry.icon aria-hidden="true" /><span>{entry.label}</span>
              </NavLink>
            </div>)}
          </nav>
          <div className="admin-sidebar-footer"><Link to="/" className="admin-return">打开阅读端<ArrowUpOutlined aria-hidden="true" rotate={45} /></Link><div className="admin-theme-control">{!mobile && <ThemeToggle />}</div><small>UNSPUN · INTELLIGENCE, UNFILTERED</small></div>
        </aside>
        <main id="admin-content" className="admin-main">
          <header className="admin-topbar"><span>工作区 <span>/</span> {page?.label ?? '页面不存在'}</span><div><button className="admin-search-trigger" onClick={() => setSearchOpen(true)}><SearchOutlined />搜索<kbd>⌘ K</kbd></button><span className="admin-topbar-divider" /><span className="admin-avatar">U</span><div className="admin-mobile-tools"><Link to="/">阅读端 ↗</Link>{mobile && <ThemeToggle />}</div></div></header>
          <div className="admin-page-body">
          {page ? (
            <>
              <div className="admin-heading">
                <div><h1>{page.label}</h1><p className="admin-page-description">{page.description}</p></div>
                <div className="admin-heading-controls">{page.path !== '/admin/configuration' && <DateRange range={range} onApply={applyRange} />}<Button aria-label="刷新工作区" icon={<ReloadOutlined />} onClick={() => { if (range.period !== 'custom') applyRange(presetRange(range.period)); void queryClient.invalidateQueries({ queryKey: ['admin'] }) }}>刷新</Button></div>
              </div>
              <div className="admin-range-caption"><span className="admin-dot" />{page.path === '/admin/configuration' ? '当前部署配置 · 不受日期范围影响' : '北京时间 · 所选期间'}{page.path !== '/admin/configuration' && query.data && <><details><summary>统计范围</summary><p>{new Date(query.data.range.start).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })} 至 {new Date(query.data.range.end).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })} · 起点包含，终点不包含</p></details><span className="admin-updated">快照 {new Date(query.data.as_of).toLocaleTimeString('zh-CN', { timeZone: 'Asia/Shanghai' })}</span></>}</div>
              {page.path !== '/admin/configuration' && query.isPending && <p role="status">正在确认查询时间…</p>}
              {page.path !== '/admin/configuration' && query.isError && (
                <div role="alert" className="admin-state">
                  <p>无法获取查询时间，请检查网络后重试。</p>
                  <Button onClick={() => void query.refetch()}>重试</Button>
                </div>
              )}
              {query.isSuccess && page.path === '/admin/sources' && <SourcesPage range={range} />}
              {query.isSuccess && page.path === '/admin/content' && <ContentPage range={range} />}
              {query.isSuccess && page.path === '/admin/runs' && <RunsPage range={range} />}
              {page.path === '/admin/configuration' && <ConfigurationPage />}
              {query.isSuccess && page.path === '/admin/costs' && <CostsPage range={range} />}
              {query.isSuccess && page.path === '/admin' && <OverviewPage range={range} />}
            </>
          ) : (
            <div className="admin-state"><h1>后台页面不存在</h1><Link to="/admin">返回总览</Link></div>
          )}
          </div>
        </main>
        <WorkspaceSearch key={String(searchOpen)} open={searchOpen} onClose={() => setSearchOpen(false)} rangeSearch={rangeSearch(new URLSearchParams(), range).toString()} />
      </div>
    </ConfigProvider>
  )
}
