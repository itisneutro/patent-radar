import type { SearchRequest } from '../api/types'
import { AnswerText, LlmPanel } from '../components/AnswerText'
import { DemoBanner } from '../components/DemoBanner'
import { QuerySummary } from '../components/QuerySummary'
import { RadarScope } from '../components/RadarScope'
import { ResultCards } from '../components/ResultCards'
import { StatePanel } from '../components/StatePanel'
import { isDemoId } from '../lib/format'
import { buttonPrimary, buttonSecondary } from '../lib/ui'
import type { SearchState } from '../lib/useSearch'

interface ResultsPageProps {
  /** Параметры запроса из маршрута #/results?… */
  request: SearchRequest
  /** Состояние поиска по этому маршруту; null — запрос ещё не отправлен. */
  search: SearchState | null
  onEdit: () => void
  onResetFilters: () => void
  onRetry: () => void
}

/** Раскладка выдачи: «Сводка» и карточки рядом на широком экране, друг под другом — на узком. */
const RESULTS_GRID = 'mt-8 grid items-start gap-8 lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]'

/**
 * Маршрут #/results?…: «Загрузка», «Выдача», «Ничего не найдено», «Сервис недоступен»,
 * «Запрос отклонён». Вверху каждого состояния — строка «Запрос» и строка фильтров.
 */
export function ResultsPage({ request, search, onEdit, onResetFilters, onRetry }: ResultsPageProps) {
  const editButton = (
    <button type="button" onClick={onEdit} className={buttonSecondary}>
      Изменить запрос
    </button>
  )

  if (search === null || search.status === 'loading') {
    return (
      <>
        <h1 className="sr-only">Выдача</h1>
        <QuerySummary query={request.query} request={request} />
        <LoadingSkeleton />
      </>
    )
  }

  if (search.status === 'unavailable') {
    return (
      <>
        <QuerySummary query={request.query} request={request} />
        <StatePanel
          tone="danger"
          title="Сервис недоступен"
          actions={
            <>
              <button type="button" onClick={onRetry} className={buttonPrimary}>
                Повторить
              </button>
              {editButton}
            </>
          }
        >
          <p>Не удалось получить ответ от сервиса поиска. Проверьте, что бэкенд запущен, и повторите попытку.</p>
        </StatePanel>
      </>
    )
  }

  if (search.status === 'rejected') {
    return (
      <>
        <QuerySummary query={request.query} request={request} />
        <StatePanel tone="danger" title="Запрос отклонён" actions={editButton}>
          <p>Сервер не принял параметры запроса (ошибка 422). Проверьте текст запроса и фильтры.</p>
        </StatePanel>
      </>
    )
  }

  const { response } = search
  const { results } = response

  if (results.length === 0) {
    const hasFilters = request.year_from != null || request.year_to != null || request.ipc != null
    return (
      <>
        <QuerySummary query={response.query} request={request} />
        <StatePanel
          title="Ничего не найдено"
          illustration={<RadarScope blips={[]} period={6} className="w-44 opacity-90 sm:w-52" />}
          actions={
            <>
              {editButton}
              <button type="button" onClick={onResetFilters} disabled={!hasFilters} className={buttonSecondary}>
                Сбросить фильтры
              </button>
            </>
          }
        >
          <p className="whitespace-pre-line">{response.answer}</p>
        </StatePanel>
      </>
    )
  }

  const resultIds = new Set(results.map((patent) => patent.id))
  return (
    <>
      <h1 className="sr-only">Выдача</h1>
      {results.some((patent) => isDemoId(patent.id)) && <DemoBanner className="mb-5" />}
      <QuerySummary query={response.query} request={request} action={editButton} />

      <div className={RESULTS_GRID}>
        <LlmPanel titleId="summary-title" title="Сводка" className="lg:sticky lg:top-24">
          <AnswerText answer={response.answer} resultIds={resultIds} />
        </LlmPanel>

        <section aria-labelledby="results-title">
          <div className="mb-4 flex items-baseline justify-between gap-4">
            <h2 id="results-title" className="font-display text-lg font-semibold tracking-tight">
              Похожие патенты
            </h2>
            <p className="text-sm text-ink-soft">
              Результатов: <span className="num font-semibold text-ink">{results.length}</span>
            </p>
          </div>
          <ResultCards results={results} labelledBy="results-title" />
        </section>
      </div>
    </>
  )
}

/** Состояние «Загрузка»: маленький радар, текст и скелетоны в раскладке выдачи. */
function LoadingSkeleton() {
  return (
    <>
      <div className="mt-8 flex items-center gap-3.5">
        <RadarScope compact blips={[]} period={1.6} className="size-10" />
        <p className="text-ink-soft">Ищем похожие патенты…</p>
      </div>
      <div aria-hidden="true" className={RESULTS_GRID}>
        <div className="panel p-5 sm:p-7">
          <div className="flex items-center gap-3">
            <div className="skeleton size-9 rounded-full" />
            <div className="skeleton h-5 w-28" />
          </div>
          <div className="mt-6 space-y-3">
            <div className="skeleton h-4 w-full" />
            <div className="skeleton h-4 w-11/12" />
            <div className="skeleton h-4 w-4/5" />
          </div>
          <div className="mt-6 space-y-3 border-l-2 border-line pl-4">
            <div className="skeleton h-4 w-full" />
            <div className="skeleton h-4 w-10/12" />
            <div className="skeleton h-4 w-2/3" />
          </div>
        </div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-1">
          {[0, 1, 2].map((index) => (
            <div key={index} className="panel p-5">
              <div className="skeleton h-4 w-32" />
              <div className="skeleton mt-4 h-5 w-full" />
              <div className="skeleton mt-2 h-5 w-3/4" />
              <div className="mt-5 flex gap-2">
                <div className="skeleton h-6 w-24" />
                <div className="skeleton h-6 w-20" />
              </div>
              <div className="skeleton mt-6 h-2 w-full rounded-full" />
            </div>
          ))}
        </div>
      </div>
    </>
  )
}
