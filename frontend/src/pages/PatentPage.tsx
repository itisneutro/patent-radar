import type { ReactNode } from 'react'
import { AnswerParagraph, LlmPanel } from '../components/AnswerText'
import { DemoBadge, DemoBanner } from '../components/DemoBanner'
import { ArrowLeft } from '../components/Icons'
import { IpcList, RelevanceBar } from '../components/ResultCards'
import { StatePanel } from '../components/StatePanel'
import { findExplanation } from '../lib/answer'
import { formatScore, formatYear, isDemoId } from '../lib/format'
import { buttonSecondary } from '../lib/ui'
import type { LastResult } from '../lib/useSearch'

interface PatentPageProps {
  /** Номер патента из маршрута #/patent/<id>. */
  id: string
  /** Последний полученный ответ: отдельного запроса за карточкой нет (в API нет такого метода). */
  lastResult: LastResult | null
  onEdit: () => void
}

/**
 * «Карточка патента»: крупный заголовок, реферат с удобной для чтения шириной строки
 * и отдельный блок метаданных с кодами INID — сбоку на широком экране, под заголовком на узком.
 * Или «Патент не найден в текущей выдаче».
 */
export function PatentPage({ id, lastResult, onEdit }: PatentPageProps) {
  const results = lastResult?.response.results ?? []
  const index = results.findIndex((patent) => patent.id === id)

  if (lastResult === null || index === -1) {
    return (
      <StatePanel
        title="Патент не найден в текущей выдаче"
        actions={
          <button type="button" onClick={onEdit} className={buttonSecondary}>
            Изменить запрос
          </button>
        }
      >
        <p className="num text-ink [overflow-wrap:anywhere]">{id}</p>
        <p className="mt-2">Карточка открывается из выдачи. Выполните поиск ещё раз, чтобы снова открыть этот патент.</p>
      </StatePanel>
    )
  }

  const patent = results[index]
  const explanation = findExplanation(lastResult.response.answer, patent.id)
  const resultIds = new Set(results.map((item) => item.id))
  const maxScore = Math.max(0, ...results.map((item) => item.score))

  return (
    <>
      <a href={lastResult.hash} className={buttonSecondary}>
        <ArrowLeft className="size-4" />
        Назад к выдаче
      </a>

      {isDemoId(patent.id) && <DemoBanner className="mt-6" />}

      <article className="mt-8 grid items-start gap-x-12 gap-y-8 lg:grid-cols-[minmax(0,1fr)_21rem]">
        <header className="min-w-0 lg:col-start-1">
          <p className="caps">
            <span className="num">(54)</span> Название
          </p>
          <h1 className="mt-3 max-w-[30ch] text-[1.75rem] font-extrabold leading-[1.18] tracking-tight text-ink sm:text-[2.375rem]">
            {patent.title}
          </h1>
        </header>

        <aside
          aria-label="Метаданные патента"
          className="panel p-5 sm:p-6 lg:sticky lg:top-24 lg:col-start-2 lg:row-span-3 lg:row-start-1"
        >
          <dl className="space-y-5">
            <Meta code="11" label="Номер">
              <span className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
                <span className="num text-lg font-semibold text-ink">{patent.id}</span>
                {isDemoId(patent.id) && <DemoBadge />}
              </span>
            </Meta>
            <Meta code="51" label="МПК">
              <IpcList codes={patent.ipc} />
            </Meta>
            <Meta code="45" label="Год публикации">
              <span className="num text-lg font-semibold text-ink">{formatYear(patent.year)}</span>
            </Meta>
          </dl>
          <dl className="mt-6 space-y-2 border-t border-line pt-5 text-sm">
            <div className="flex justify-between gap-3">
              <dt className="text-muted">Позиция в выдаче:</dt>
              <dd className="text-ink">
                <span className="num font-semibold">{index + 1}</span> из <span className="num">{results.length}</span>
              </dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-muted">Оценка BM25:</dt>
              <dd className="num font-semibold text-ink">{formatScore(patent.score)}</dd>
            </div>
          </dl>
          <RelevanceBar score={patent.score} max={maxScore} className="mt-3" />
        </aside>

        <section aria-labelledby="abstract-title" className="min-w-0 lg:col-start-1">
          <h2 id="abstract-title" className="caps">
            <span className="num">(57)</span> Реферат
          </h2>
          <p className="mt-3 max-w-[68ch] text-[17px] leading-[1.75] text-ink">{patent.abstract}</p>
        </section>

        {explanation !== null && (
          <LlmPanel titleId="explanation-title" title="Пояснение" className="min-w-0 lg:col-start-1">
            <AnswerParagraph
              paragraph={explanation}
              resultIds={resultIds}
              currentId={patent.id}
              className="max-w-[68ch] text-[15.5px] leading-relaxed text-ink"
            />
          </LlmPanel>
        )}
      </article>
    </>
  )
}

/** Строка блока метаданных: код INID моноширинным, подпись, значение. */
function Meta({ code, label, children }: { code: string; label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="caps">
        <span className="num">({code})</span> {label}
      </dt>
      <dd className="mt-2 min-w-0">{children}</dd>
    </div>
  )
}
