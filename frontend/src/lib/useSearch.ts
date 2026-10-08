/**
 * Состояние поиска приложения. Выдача запрашивается по параметрам маршрута #/results?…:
 * - runSearch() — отправить запрос всегда («Найти аналоги», «Сбросить фильтры», «Повторить»);
 * - ensureSearch() — отправить, только если для этого маршрута ещё нет ответа или запроса
 *   в работе (открытие по ссылке, «Назад» в браузере). Поэтому возврат из карточки показывает
 *   ту же выдачу сразу, без повторной загрузки.
 * Новый запрос отменяет предыдущий, ответ на устаревший запрос не показывается.
 */
import { useCallback, useRef, useState } from 'react'
import { searchPatents } from '../api/client'
import { SearchError } from '../api/errors'
import type { SearchRequest, SearchResponse } from '../api/types'
import { resultsHash } from './route'

interface SearchBase {
  /** Маршрут выдачи (resultsHash) этого запроса. */
  hash: string
  request: SearchRequest
}

export type SearchState =
  | (SearchBase & { status: 'loading' })
  | (SearchBase & { status: 'success'; response: SearchResponse })
  /** API ответил 422 → «Запрос отклонён». */
  | (SearchBase & { status: 'rejected' })
  /** Сеть, 5xx или ответ не по контракту → «Сервис недоступен». */
  | (SearchBase & { status: 'unavailable' })

/** Последний полученный ответ: из него «Карточка патента» берёт данные. */
export type LastResult = SearchBase & { response: SearchResponse }

export function useSearch() {
  const [search, setSearch] = useState<SearchState | null>(null)
  const [lastResult, setLastResult] = useState<LastResult | null>(null)
  const active = useRef<{ hash: string; controller: AbortController } | null>(null)

  const runSearch = useCallback((request: SearchRequest) => {
    const hash = resultsHash(request)
    active.current?.controller.abort()
    const controller = new AbortController()
    active.current = { hash, controller }
    setSearch({ hash, request, status: 'loading' })

    searchPatents(request, controller.signal).then(
      (response) => {
        if (controller.signal.aborted) return
        setSearch({ hash, request, status: 'success', response })
        setLastResult({ hash, request, response })
      },
      (error: unknown) => {
        if (controller.signal.aborted) return
        if (!(error instanceof SearchError)) console.error(error)
        const status = error instanceof SearchError && error.kind === 'rejected' ? 'rejected' : 'unavailable'
        setSearch({ hash, request, status })
      },
    )
  }, [])

  const ensureSearch = useCallback(
    (request: SearchRequest) => {
      if (active.current?.hash !== resultsHash(request)) runSearch(request)
    },
    [runSearch],
  )

  return { search, lastResult, runSearch, ensureSearch }
}
