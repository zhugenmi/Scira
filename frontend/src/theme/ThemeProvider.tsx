import { createContext, useContext, useEffect, useState, useCallback, type ReactNode } from 'react'

export type Theme = 'light' | 'dark' | 'system'
type Effective = 'light' | 'dark'

interface ThemeContextValue {
  theme: Theme
  effective: Effective
  setTheme: (t: Theme) => void
  cycleTheme: () => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

const STORAGE_KEY = 'scira-theme'

function readStoredTheme(): Theme {
  if (typeof window === 'undefined') return 'system'
  const v = window.localStorage.getItem(STORAGE_KEY)
  if (v === 'light' || v === 'dark' || v === 'system') return v
  return 'system'
}

function systemPrefersDark(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) return false
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

function applyClass(effective: Effective) {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  if (effective === 'dark') root.classList.add('dark')
  else root.classList.remove('dark')
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => readStoredTheme())
  const [effective, setEffective] = useState<Effective>(() => {
    const t = readStoredTheme()
    if (t === 'system') return systemPrefersDark() ? 'dark' : 'light'
    return t
  })

  // 主题变化或系统主题变化时，重算 effective 并写 class
  useEffect(() => {
    const recompute = () => {
      const eff: Effective = theme === 'system'
        ? (systemPrefersDark() ? 'dark' : 'light')
        : theme
      setEffective(eff)
      applyClass(eff)
    }
    recompute()

    if (theme !== 'system') return
    const mql = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = () => recompute()
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [theme])

  const setTheme = useCallback((t: Theme) => {
    setThemeState(t)
    try { window.localStorage.setItem(STORAGE_KEY, t) } catch { /* ignore */ }
  }, [])

  const cycleTheme = useCallback(() => {
    setThemeState((prev) => {
      const next: Theme = prev === 'light' ? 'dark' : prev === 'dark' ? 'system' : 'light'
      try { window.localStorage.setItem(STORAGE_KEY, next) } catch { /* ignore */ }
      return next
    })
  }, [])

  return (
    <ThemeContext.Provider value={{ theme, effective, setTheme, cycleTheme }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider')
  return ctx
}
