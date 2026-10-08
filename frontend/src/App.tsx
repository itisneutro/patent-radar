import { useEffect, useRef, useState } from 'react'
import type { SearchRequest } from './api/types'
import { Layout } from './components/Layout'
import { navigate, resultsHash, SEARCH_HASH, useHashRoute, type Route } from './lib/route'
import { useSearch, type SearchState } from './lib/useSearch'
import { DEFAULT_TOP_K, EMPTY_FORM, formFromRequest, type SearchForm } from './lib/validation'
import { PatentPage } from './pages/PatentPage'
import { ResultsPage } from './pages/ResultsPage'
import { SearchPage } from './pages/SearchPage'

/**
 * Приложение: хэш-маршрут → экран. Здесь же хранятся поля «Экрана запроса» (они переживают
 * переход к выдаче и обратно) и состояние поиска (см. lib/useSearch.ts).
 */
export default function App() {
  const { route, hash } = useHashRoute()
  const [form, setForm] = useState<SearchForm>(EMPTY_FORM)
  const { search, lastResult, runSearch, ensureSearch } = useSearch()
  const mainRef = useRef<HTMLElement>(null)
  const previousHash = useRef<string | null>(null)

  // Выдача запрашивается по параметрам маршрута; если ответ на них уже есть, запроса нет.
  useEffect(() => {
    if (route.name === 'results') ensureSearch(route.request)
  }, [route, ensureSearch])

  // Смена экрана: прокрутка в начало и фокус на основное содержимое (клавиатура, экранные дикторы).
  useEffect(() => {
    if (previousHash.current !== null && previousHash.current !== hash) {
      window.scrollTo(0, 0)
      mainRef.current?.focus({ preventScroll: true })
    }
    previousHash.current = hash
  }, [hash])

  /** «Найти аналоги»: поиск отправляется всегда, даже если такой запрос уже был. */
  function startSearch(request: SearchRequest) {
    runSearch(request)
    navigate(resultsHash(request))
  }

  /** «Изменить запрос»: «Экран запроса» с текстом и фильтрами текущего запроса. */
  function editQuery(request: SearchRequest | undefined) {
    if (request) setForm(formFromRequest(request))
    navigate(SEARCH_HASH)
  }

  /** «Сбросить фильтры»: год и МПК очищаются, количество — 10, поиск сразу повторяется. */
  function resetFilters(request: SearchRequest) {
    const next: SearchRequest = {
      query: request.query,
      top_k: DEFAULT_TOP_K,
      year_from: null,
      year_to: null,
      ipc: null,
    }
    setForm(formFromRequest(next))
    startSearch(next)
  }

  const routeSearch = route.name === 'results' && search?.hash === route.hash ? search : null

  return (
    <Layout status={statusText(route, routeSearch)} screenKey={screenKey(route)} mainRef={mainRef}>
      {route.name === 'search' && <SearchPage form={form} onChange={setForm} onSubmit={startSearch} />}
      {route.name === 'results' && (
        <ResultsPage
          request={route.request}
          search={routeSearch}
          onEdit={() => editQuery(route.request)}
          onResetFilters={() => resetFilters(route.request)}
          onRetry={() => {
            // Кнопка «Повторить» исчезает на время загрузки: фокус переходит на основное содержимое.
            runSearch(route.request)
            mainRef.current?.focus({ preventScroll: true })
          }}
        />
      )}
      {route.name === 'patent' && (
        <PatentPage
          id={route.id}
          lastResult={lastResult}
          onEdit={() => editQuery(lastResult?.request ?? search?.request)}
        />
      )}
    </Layout>
  )
}

/** Ключ экрана для плавного перехода: новый маршрут — новое появление содержимого. */
function screenKey(route: Route): string {
  if (route.name === 'results') return route.hash
  if (route.name === 'patent') return `patent:${route.id}`
  return 'search'
}

/** Текст для aria-live: что происходит с поиском на маршруте #/results?… */
function statusText(route: Route, search: SearchState | null): string {
  if (route.name !== 'results') return ''
  if (search === null || search.status === 'loading') return 'Ищем похожие патенты…'
  if (search.status === 'unavailable') return 'Сервис недоступен'
  if (search.status === 'rejected') return 'Запрос отклонён'
  const count = search.response.results.length
  return count === 0 ? 'Ничего не найдено' : `Результатов: ${count}`
}
