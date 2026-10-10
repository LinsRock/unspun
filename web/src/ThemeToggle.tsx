import { useEffect, useState } from 'react'

// Theme model (see DESIGN.md): an explicit choice sets data-theme="light"/
// "dark" on <html>; "system" removes the attribute so prefers-color-scheme
// decides. index.html re-applies the persisted choice before first paint.
type ThemeMode = 'light' | 'system' | 'dark'

const STORAGE_KEY = 'unspun-theme'

// localStorage may be unavailable (private mode); the choice then lasts one visit.
function readStoredMode(): ThemeMode {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored === 'light' || stored === 'dark') return stored
  } catch {
    /* ignore */
  }
  return 'system'
}

function SunIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M19.1 4.9L17 7M7 17l-2.1 2.1" />
    </svg>
  )
}

function SystemIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <rect x="3" y="5" width="18" height="13" rx="2" />
      <path d="M9 21h6" />
    </svg>
  )
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M20 14.5A8 8 0 1 1 9.5 4 6.5 6.5 0 0 0 20 14.5z" />
    </svg>
  )
}

const MODES: { mode: ThemeMode; label: string; icon: () => React.ReactNode }[] = [
  { mode: 'light', label: '亮色', icon: SunIcon },
  { mode: 'system', label: '跟随系统', icon: SystemIcon },
  { mode: 'dark', label: '暗色', icon: MoonIcon },
]

export default function ThemeToggle() {
  const [mode, setMode] = useState<ThemeMode>(readStoredMode)

  useEffect(() => {
    if (mode === 'system') delete document.documentElement.dataset.theme
    else document.documentElement.dataset.theme = mode
    try {
      localStorage.setItem(STORAGE_KEY, mode)
    } catch {
      /* ignore */
    }
  }, [mode])

  return (
    <div role="group" aria-label="主题切换" className="inline-flex gap-0.5 rounded-full border border-line bg-bg-sunk p-[3px]">
      {MODES.map(({ mode: m, label, icon: Icon }) => (
        <button
          key={m}
          type="button"
          title={label}
          aria-label={label}
          aria-pressed={mode === m}
          onClick={() => setMode(m)}
          className={`grid h-6 w-[30px] place-items-center rounded-full ${
            mode === m ? 'border border-line bg-surface text-ink shadow-card' : 'text-ink-4'
          }`}
        >
          <Icon />
        </button>
      ))}
    </div>
  )
}
