import type { ReactNode } from 'react'
import { AlertTriangle, Info } from './Icons'

interface StatePanelProps {
  /** Заголовок состояния: «Ничего не найдено», «Сервис недоступен» и т. п. */
  title: string
  tone?: 'neutral' | 'danger'
  /** Иллюстрация над заголовком (радар без целей у «Ничего не найдено»); без неё — значок. */
  illustration?: ReactNode
  /** Пояснение под заголовком. */
  children?: ReactNode
  /** Действия состояния: кнопки «Изменить запрос», «Повторить», «Сбросить фильтры». */
  actions: ReactNode
}

/** Состояние без выдачи: пустая выдача, ошибки, патент не найден. */
export function StatePanel({ title, tone = 'neutral', illustration, children, actions }: StatePanelProps) {
  if (illustration) {
    return (
      <section className="panel mt-6 flex flex-col items-center px-6 py-10 text-center sm:px-10 sm:py-12">
        {illustration}
        <h1 className="mt-8 font-display text-2xl font-semibold tracking-tight sm:text-[1.75rem]">{title}</h1>
        {children && <div className="mt-3 max-w-[58ch] leading-relaxed text-ink-soft">{children}</div>}
        <div className="mt-7 flex flex-wrap justify-center gap-3">{actions}</div>
      </section>
    )
  }

  const danger = tone === 'danger'
  const Icon = danger ? AlertTriangle : Info
  return (
    <section className={`panel mt-6 p-6 sm:p-8 ${danger ? 'border-danger/50' : ''}`}>
      <div className="flex flex-col gap-5 sm:flex-row sm:items-start">
        <span
          className={`inline-flex size-12 shrink-0 items-center justify-center rounded-2xl ${
            danger ? 'bg-danger/12 text-danger' : 'bg-accent/12 text-accent'
          }`}
        >
          <Icon className="size-6" />
        </span>
        <div className="min-w-0">
          <h1 className="font-display text-xl font-semibold tracking-tight sm:text-2xl">{title}</h1>
          {children && <div className="mt-2 max-w-[64ch] leading-relaxed text-ink-soft">{children}</div>}
          <div className="mt-6 flex flex-wrap gap-3">{actions}</div>
        </div>
      </div>
    </section>
  )
}
