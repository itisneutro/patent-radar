/**
 * Хэш-роутер без библиотек. Маршруты (spec/product/scenarios.md, раздел 1):
 * - #/ — «Экран запроса»;
 * - #/results?query=…&top_k=…[&year_from=…][&year_to=…][&ipc=…] — выдача и её состояния;
 *   параметры называются как поля запроса API, фильтры пишутся, только если заданы;
 * - #/patent/<id> — «Карточка патента».
 * Неизвестный маршрут открывает «Экран запроса».
 */
import { useMemo, useSyncExternalStore } from 'react'
import type { SearchRequest } from '../api/types'
import { DEFAULT_TOP_K } from './validation'

export type Route =
  | { name: 'search' }
  /** hash — канонический вид маршрута: по нему узнаётся, для какой выдачи уже есть ответ. */
  | { name: 'results'; request: SearchRequest; hash: string }
  | { name: 'patent'; id: string }

export const SEARCH_HASH = '#/'

/** Маршрут выдачи по параметрам запроса. */
export function resultsHash(request: SearchRequest): string {
  const params = new URLSearchParams()
  params.set('query', request.query)
  params.set('top_k', String(request.top_k ?? DEFAULT_TOP_K))
  if (request.year_from != null) params.set('year_from', String(request.year_from))
  if (request.year_to != null) params.set('year_to', String(request.year_to))
  if (request.ipc != null) params.set('ipc', request.ipc)
  return `#/results?${params.toString()}`
}

export function patentHash(id: string): string {
  return `#/patent/${encodeURIComponent(id)}`
}

/** Целое число из параметра маршрута или null, если параметра нет или это не целое число. */
function parseInteger(value: string | null): number | null {
  if (value === null || !/^-?\d+$/.test(value.trim())) return null
  return Number(value)
}

/**
 * Тело запроса по параметрам маршрута. Нецелые year_from и year_to отбрасываются (фильтр
 * не задан), нецелый или отсутствующий top_k заменяется на 10. Целые значения вне диапазона,
 * year_from больше year_to и короткий запрос не исправляются: API (в режиме mock — мок)
 * отвечает 422, и выдача показывает «Запрос отклонён».
 */
function requestFromParams(params: URLSearchParams): SearchRequest {
  return {
    query: (params.get('query') ?? '').trim(),
    top_k: parseInteger(params.get('top_k')) ?? DEFAULT_TOP_K,
    year_from: parseInteger(params.get('year_from')),
    year_to: parseInteger(params.get('year_to')),
    ipc: params.get('ipc')?.trim() || null,
  }
}

function decode(value: string): string {
  try {
    return decodeURIComponent(value)
  } catch {
    return value
  }
}

export function parseRoute(hash: string): Route {
  const path = hash.replace(/^#/, '')
  const separator = path.indexOf('?')
  const pathname = separator === -1 ? path : path.slice(0, separator)
  if (pathname === '/results') {
    const request = requestFromParams(new URLSearchParams(separator === -1 ? '' : path.slice(separator + 1)))
    return { name: 'results', request, hash: resultsHash(request) }
  }
  const patent = /^\/patent\/(.+)$/.exec(pathname)
  if (patent) return { name: 'patent', id: decode(patent[1]) }
  return { name: 'search' }
}

/** Переход на маршрут с новой записью в истории браузера: «Назад» в браузере вернёт предыдущий экран. */
export function navigate(hash: string): void {
  if (window.location.hash !== hash) window.location.hash = hash
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener('hashchange', onChange)
  return () => window.removeEventListener('hashchange', onChange)
}

const readHash = () => window.location.hash

/** Текущий маршрут; компонент перерисовывается при каждой смене хэша. */
export function useHashRoute(): { route: Route; hash: string } {
  const hash = useSyncExternalStore(subscribe, readHash)
  const route = useMemo(() => parseRoute(hash), [hash])
  return { route, hash }
}
