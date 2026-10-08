import { useEffect, useState } from 'react'

interface Health {
  status: string
  version: string
  database: string
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    fetch('/api/health')
      .then((res) => (res.ok ? (res.json() as Promise<Health>) : Promise.reject(new Error())))
      .then(setHealth)
      .catch(() => setError(true))
  }, [])

  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col items-center justify-center gap-4 px-4">
      <h1 className="text-3xl font-bold">Unspun</h1>
      <p className="text-gray-500">个人情报站 · M0 占位页</p>
      <div className="rounded-lg border border-gray-200 px-4 py-2 text-sm">
        {error && <span className="text-red-600">API 不可用</span>}
        {!error && !health && <span>检查中…</span>}
        {health && (
          <span data-testid="health">
            状态 {health.status} · 版本 {health.version} · 数据库 {health.database}
          </span>
        )}
      </div>
    </main>
  )
}
