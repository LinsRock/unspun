import { useEffect, useState } from 'react'

import { todayInBeijing } from './digestDates'

export function useBeijingToday(): string {
  const [today, setToday] = useState(todayInBeijing)
  useEffect(() => {
    const update = () => setToday(todayInBeijing())
    const interval = window.setInterval(update, 60_000)
    window.addEventListener('focus', update)
    document.addEventListener('visibilitychange', update)
    return () => {
      window.clearInterval(interval)
      window.removeEventListener('focus', update)
      document.removeEventListener('visibilitychange', update)
    }
  }, [])
  return today
}
