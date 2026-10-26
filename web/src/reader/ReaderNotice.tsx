import { ReaderError } from './api'

export default function ReaderNotice({ error, retry }: { error: unknown; retry: () => void }) {
  const status = error instanceof ReaderError ? error.status : 0
  return <div role="alert" className="r1-notice"><p>{status === 401 || status === 403 ? '登录已失效或没有访问权限，请重新登录后继续。' : status === 409 ? '内容或偏好已变化，这份列表已失效。请重新加载后继续。' : status === 400 ? '这份列表已过期，请从第一页重新加载。' : status === 404 ? '当前入口尚未开放，或内容已不再公开。历史阅读入口仍可访问。' : '暂时无法连接服务器。请检查网络后重试。'}</p>{status === 401 || status === 403 ? <a href={window.location.pathname + window.location.search}>重新登录并加载</a> : <button onClick={retry}>重新加载</button>}</div>
}
