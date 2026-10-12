import { useQuery } from '@tanstack/react-query'
import { Button, ConfigProvider, Empty, Typography } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { useState } from 'react'
import { Link, NavLink, useLocation, useSearchParams } from 'react-router-dom'

import ThemeToggle from '../ThemeToggle'
import { fetchAdminRange } from './adminApi'
import DateRange from './DateRange'
import { parseRange, rangeSearch, sharedRangeSearch, type AdminRange } from './adminFilters'
import './admin.css'

const pages = [
  { path: '/admin', label: '总览', phase: 'A6' },
  { path: '/admin/sources', label: '信息源', phase: 'A2' },
  { path: '/admin/content', label: '文章与事件', phase: 'A2' },
  { path: '/admin/runs', label: '运行与任务', phase: 'A3' },
  { path: '/admin/costs', label: '费用', phase: 'A5' },
  { path: '/admin/configuration', label: '配置与操作记录', phase: 'A3' },
] as const

export default function AdminLayout() {
  const location = useLocation()
  const [search, setSearch] = useSearchParams()
  const [openedAt, setOpenedAt] = useState(() => new Date())
  const range = parseRange(search, openedAt)
  const page = pages.find((entry) => entry.path === location.pathname)
  const query = useQuery({
    queryKey: ['admin', 'range', range.start, range.end],
    queryFn: ({ signal }) => fetchAdminRange(range, signal),
    retry: false,
    enabled: Boolean(page),
  })

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
        token: {
          colorPrimary: 'var(--accent)',
          colorBgContainer: 'var(--surface)',
          colorText: 'var(--ink)',
          colorBorder: 'var(--line)',
        },
      }}
    >
      <div className="admin-workspace">
        <a href="#admin-content" className="sr-only focus:not-sr-only">跳到后台内容</a>
        <aside className="admin-sidebar">
          <div className="admin-brand"><strong>Unspun</strong><span>管理后台</span></div>
          <nav aria-label="后台导航">
            {pages.map((entry) => (
              <NavLink
                key={entry.path}
                end
                to={{ pathname: entry.path, search: sharedRangeSearch(search) }}
                className={({ isActive }) => isActive ? 'admin-nav-link active' : 'admin-nav-link'}
              >
                {entry.label}
              </NavLink>
            ))}
          </nav>
          <Link to="/" className="admin-return">返回阅读页</Link>
          <ThemeToggle />
        </aside>
        <main id="admin-content" className="admin-main">
          {page ? (
            <>
              <div className="admin-heading">
                <div><Typography.Text type="secondary">管理后台 / 查询工作区</Typography.Text><h1>{page.label}</h1></div>
                <DateRange range={range} onApply={applyRange} />
              </div>
              <p className="admin-range-caption">
                北京时间 · 起点包含，终点不包含
                {query.data && ` · ${new Date(query.data.range.start).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })} 至 ${new Date(query.data.range.end).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })} · 查询截止 ${new Date(query.data.as_of).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}`}
              </p>
              {query.isPending && <p role="status">正在确认查询时间…</p>}
              {query.isError && (
                <div role="alert" className="admin-state">
                  <p>无法获取查询时间，请检查网络后重试。</p>
                  <Button onClick={() => void query.refetch()}>重试</Button>
                </div>
              )}
              {query.isSuccess && (
                <div className="admin-state">
                  <Empty description={`${page.label}历史查询将在 ${page.phase} 接入；当前没有可展示的真实后台数据。`} />
                </div>
              )}
            </>
          ) : (
            <div className="admin-state"><h1>后台页面不存在</h1><Link to="/admin">返回总览</Link></div>
          )}
        </main>
      </div>
    </ConfigProvider>
  )
}
