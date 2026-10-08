import type { ReactNode, Ref } from 'react'
import { API_MODE } from '../api/client'
import { ANSWER_DISCLAIMER } from '../lib/answer'
import { useTheme } from '../lib/theme'
import { Moon, RadarMark, Sun } from './Icons'

interface LayoutProps {
  /** Статус поиска для экранных дикторов (aria-live): «Ищем похожие патенты…», «Результатов: 3». */
  status: string
  /** Ключ экрана: при его смене содержимое появляется заново с плавным переходом. */
  screenKey: string
  mainRef: Ref<HTMLElement>
  children: ReactNode
}

const CONTAINER = 'mx-auto w-full max-w-6xl px-4 sm:px-6'

export function Layout({ status, screenKey, mainRef, children }: LayoutProps) {
  const { theme, toggleTheme } = useTheme()
  const themeAction = theme === 'dark' ? 'Включить светлую тему' : 'Включить тёмную тему'

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-30 border-b border-line bg-bg/75 backdrop-blur-md">
        <div className={`${CONTAINER} flex h-16 items-center justify-between gap-3`}>
          <p className="font-display text-[15px] font-semibold tracking-tight sm:text-base">
            <a href="#/" className="inline-flex items-center gap-2.5 rounded-lg text-ink transition-colors hover:text-accent">
              <RadarMark className="size-7 text-accent" />
              Патентный радар
            </a>
          </p>
          <div className="flex items-center gap-2.5 sm:gap-3">
            <p className="text-xs text-muted">
              <span className="max-sm:sr-only">режим данных </span>
              <span className="num rounded-md border border-line bg-raised px-1.5 py-0.5 text-ink-soft">{API_MODE}</span>
            </p>
            <button
              type="button"
              onClick={toggleTheme}
              aria-label={themeAction}
              title={themeAction}
              className="inline-flex size-9 items-center justify-center rounded-full border border-line text-ink-soft transition-colors hover:border-accent hover:text-accent"
            >
              {theme === 'dark' ? <Sun className="size-[18px]" /> : <Moon className="size-[18px]" />}
            </button>
          </div>
        </div>
      </header>

      <main ref={mainRef} id="main" tabIndex={-1} className={`${CONTAINER} flex-1 py-8 outline-none sm:py-12`}>
        <div key={screenKey} className="screen-enter">
          {children}
        </div>
      </main>

      <footer className="border-t border-line">
        <p className={`${CONTAINER} py-6 text-sm text-muted`}>{ANSWER_DISCLAIMER}</p>
      </footer>

      <p role="status" className="sr-only">
        {status}
      </p>
    </div>
  )
}
