import type { ReactNode } from 'react'
import type { SearchRequest } from '../api/types'
import { DEFAULT_TOP_K } from '../lib/validation'

interface QuerySummaryProps {
  /** Текст запроса: на «Выдаче» — query из ответа, в остальных состояниях — из маршрута. */
  query: string
  /** Параметры запроса из маршрута: по ним строится строка фильтров. */
  request: SearchRequest
  /** Кнопка рядом со строкой «Запрос» (на «Выдаче» — «Изменить запрос»). */
  action?: ReactNode
}

/** Верх всех состояний #/results: строка «Запрос» и строка фильтров — моноширинные чипы. */
export function QuerySummary({ query, request, action }: QuerySummaryProps) {
  const yearFrom = request.year_from ?? null
  const yearTo = request.year_to ?? null
  return (
    <div className="panel flex flex-col gap-4 p-5 sm:flex-row sm:items-start sm:justify-between sm:gap-10 sm:p-6">
      <div className="min-w-0">
        <dl>
          <dt className="caps">Запрос</dt>
          <dd className="mt-2 max-w-[72ch] text-[17px] font-medium leading-relaxed text-ink [overflow-wrap:anywhere] sm:text-lg">
            {query}
          </dd>
        </dl>
        <ul className="mt-4 flex flex-wrap gap-2 text-[13px] text-ink-soft">
          {(yearFrom !== null || yearTo !== null) && (
            <li className="rounded-full border border-line bg-raised px-3 py-1">
              <span className="text-muted">Год публикации:</span>
              {yearFrom !== null && (
                <>
                  {' '}
                  с <span className="num text-ink">{yearFrom}</span>
                </>
              )}
              {yearTo !== null && (
                <>
                  {' '}
                  по <span className="num text-ink">{yearTo}</span>
                </>
              )}
            </li>
          )}
          {request.ipc != null && (
            <li className="rounded-full border border-line bg-raised px-3 py-1 [overflow-wrap:anywhere]">
              <span className="text-muted">МПК (префикс):</span> <span className="num text-ink">{request.ipc}</span>
            </li>
          )}
          <li className="rounded-full border border-line bg-raised px-3 py-1">
            <span className="text-muted">Количество результатов:</span>{' '}
            <span className="num text-ink">{request.top_k ?? DEFAULT_TOP_K}</span>
          </li>
        </ul>
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  )
}
