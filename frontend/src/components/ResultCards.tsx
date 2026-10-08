import type { CSSProperties } from 'react'
import type { PatentResult } from '../api/types'
import { formatScore, formatYear, isDemoId } from '../lib/format'
import { patentHash } from '../lib/route'
import { DemoBadge } from './DemoBanner'

interface ResultCardsProps {
  results: PatentResult[]
  /** id заголовка блока «Похожие патенты»: подпись списка для экранных дикторов. */
  labelledBy: string
}

/**
 * Выдача — карточки патентов в порядке API (сортировки нет), «№» — с 1. Название — ссылка
 * на «Карточку патента», растянутая на всю карточку: щелчок в любом месте открывает её.
 * Номер и коды МПК — моноширинным шрифтом; полоса релевантности показывает оценку BM25
 * относительно лучшей в этой выдаче (оценки сравнимы только внутри одной выдачи).
 */
export function ResultCards({ results, labelledBy }: ResultCardsProps) {
  const maxScore = Math.max(0, ...results.map((patent) => patent.score))

  return (
    <ol aria-labelledby={labelledBy} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-1">
      {results.map((patent, index) => (
        <li key={patent.id} className="rise-in" style={{ '--delay': `${index * 70}ms` } as CSSProperties}>
          <article className="group relative flex h-full flex-col rounded-[1.25rem] border border-line bg-surface p-5 transition-[border-color,box-shadow] duration-200 hover:border-accent/70 hover:shadow-[0_0_0_1px_var(--c-glow),0_18px_40px_-24px_var(--c-glow)]">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
              <span className="num text-xs text-muted">№ {index + 1}</span>
              <span className="num text-[15px] font-semibold text-ink">{patent.id}</span>
              {isDemoId(patent.id) && <DemoBadge />}
            </div>

            <h3 className="mt-2.5 text-[17px] font-bold leading-snug">
              <a href={patentHash(patent.id)} className="card-link text-ink transition-colors group-hover:text-accent">
                {patent.title}
              </a>
            </h3>

            <dl className="mt-4 grid grid-cols-[auto_minmax(0,1fr)] items-baseline gap-x-4 gap-y-2.5 text-sm">
              <dt className="caps">МПК</dt>
              <dd>
                <IpcList codes={patent.ipc} />
              </dd>
              <dt className="caps">Год</dt>
              <dd className="num text-ink">{formatYear(patent.year)}</dd>
            </dl>

            <div className="mt-auto pt-5">
              <div className="flex items-baseline justify-between gap-3">
                <span className="caps">Оценка BM25</span>
                <span className="num text-[15px] font-semibold text-ink">{formatScore(patent.score)}</span>
              </div>
              <RelevanceBar score={patent.score} max={maxScore} className="mt-2" />
            </div>
          </article>
        </li>
      ))}
    </ol>
  )
}

/** Коды МПК в порядке из ipc — моноширинные чипы; код не переносится внутри. */
export function IpcList({ codes }: { codes: string[] }) {
  return (
    <ul className="flex flex-wrap gap-1.5">
      {codes.map((code, index) => (
        <li
          key={`${index}-${code}`}
          className="num whitespace-nowrap rounded-md border border-line bg-raised px-2 py-0.5 text-[13px] leading-5 text-ink-soft"
        >
          {code}
        </li>
      ))}
    </ul>
  )
}

/**
 * Полоса релевантности: заполнение — оценка относительно максимальной в выдаче, дорожка —
 * тот же оттенок, только бледнее. Значение рядом написано текстом, поэтому полоса декоративная.
 */
export function RelevanceBar({ score, max, className = '' }: { score: number; max: number; className?: string }) {
  const share = max > 0 ? Math.min(1, Math.max(0, score / max)) : 0
  return (
    <span aria-hidden="true" className={`relative block h-2 overflow-hidden rounded-full bg-signal/20 ${className}`}>
      <span
        className="absolute inset-y-0 left-0 rounded-full bg-signal"
        style={{ width: `${(share * 100).toFixed(1)}%` }}
      />
    </span>
  )
}
