import { Input, Modal } from 'antd'
import { SearchOutlined, ArrowRightOutlined } from '@ant-design/icons'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

export default function WorkspaceSearch({ open, onClose, rangeSearch }: { open: boolean; onClose: () => void; rangeSearch: string }) {
  const [keyword, setKeyword] = useState('')
  const navigate = useNavigate()
  const pages = [{ label: '运营总览', path: '/admin' }, { label: '内容工作区', path: '/admin/content' }, { label: '信息源', path: '/admin/sources' }, { label: '运行与任务', path: '/admin/runs' }, { label: '费用与预算', path: '/admin/costs' }, { label: '配置与审计', path: '/admin/configuration' }]
  function go(path: string, tab?: string) {
    const params = new URLSearchParams(rangeSearch)
    if (tab) { params.set('tab', tab); if (keyword.trim()) params.set('keyword', keyword.trim()) }
    navigate({ pathname: path, search: params.toString() })
    onClose()
  }
  return <Modal open={open} onCancel={onClose} footer={null} title="搜索工作区" destroyOnHidden className="admin-search-modal">
    <Input autoFocus size="large" prefix={<SearchOutlined />} placeholder="输入内容关键词或页面名称…" value={keyword} onChange={event => setKeyword(event.target.value)} onPressEnter={() => go('/admin/content', 'articles')} />
    {keyword.trim() && <div className="admin-search-results"><small>搜索所选期间的内容</small>{['articles', 'events'].map(tab => <button key={tab} onClick={() => go('/admin/content', tab)}>搜索{tab === 'articles' ? '文章' : '事件'}「{keyword.trim()}」<ArrowRightOutlined /></button>)}</div>}
    <div className="admin-search-results"><small>快速前往</small>{pages.filter(page => !keyword.trim() || page.label.includes(keyword.trim())).map(page => <button key={page.path} onClick={() => go(page.path)}>{page.label}<ArrowRightOutlined /></button>)}</div>
    <p className="admin-note">Enter 搜索文章 · Esc 关闭 · 搜索范围沿用当前日期</p>
  </Modal>
}
