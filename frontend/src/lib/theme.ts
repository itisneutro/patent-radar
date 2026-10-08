/**
 * Тема интерфейса: тёмная по умолчанию, светлая — по переключателю в шапке (например, когда
 * прототип показывают на проекторе). Тема — атрибут data-theme на <html>: его выставляет
 * скрипт в index.html до первой отрисовки, а переключатель меняет и запоминает в localStorage.
 */
import { useState } from 'react'

export type Theme = 'dark' | 'light'

const STORAGE_KEY = 'patent-radar-theme'

/** Цвет панели браузера (meta theme-color) — фон страницы в каждой теме. */
const THEME_COLOR: Record<Theme, string> = { dark: '#050c1a', light: '#eef3f8' }

function currentTheme(): Theme {
  return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark'
}

function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', THEME_COLOR[theme])
  try {
    localStorage.setItem(STORAGE_KEY, theme)
  } catch {
    // Хранилище недоступно (приватный режим, запрет cookies): тема просто не запомнится.
  }
}

export function useTheme(): { theme: Theme; toggleTheme: () => void } {
  const [theme, setTheme] = useState<Theme>(currentTheme)

  function toggleTheme() {
    const next: Theme = theme === 'dark' ? 'light' : 'dark'
    applyTheme(next)
    setTheme(next)
  }

  return { theme, toggleTheme }
}
