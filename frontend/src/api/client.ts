/**
 * Источник данных интерфейса. Режим задаёт VITE_API_MODE:
 * - mock (по умолчанию, `npm run dev`) — ответ формирует mockSearch() по src/mock/search.json;
 * - api (`npm run dev:api`, файл .env.api) — POST /api/search, dev-сервер Vite передаёт запрос
 *   бэкенду на http://127.0.0.1:8000/search (vite.config.ts).
 */
import { SearchError } from './errors'
import { mockSearch } from './mock'
import type { PatentResult, SearchRequest, SearchResponse } from './types'

export type ApiMode = 'mock' | 'api'

export const API_MODE: ApiMode = import.meta.env.VITE_API_MODE === 'api' ? 'api' : 'mock'

export const SEARCH_URL = '/api/search'

/**
 * Поиск похожих патентов. Ошибки — SearchError: kind 'rejected' (422) или 'unavailable'
 * (сеть, 5xx, ответ не по контракту). При отмене через signal — AbortError.
 */
export function searchPatents(request: SearchRequest, signal?: AbortSignal): Promise<SearchResponse> {
  return API_MODE === 'api' ? fetchSearch(request, signal) : mockSearch(request, signal)
}

async function fetchSearch(request: SearchRequest, signal?: AbortSignal): Promise<SearchResponse> {
  let response: Response
  try {
    response = await fetch(SEARCH_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(request),
      signal,
    })
  } catch (error) {
    if (signal?.aborted) throw error
    throw new SearchError('unavailable', 'Сервис поиска не ответил (сетевая ошибка)')
  }
  if (response.status === 422) {
    throw new SearchError('rejected', 'Сервер не принял параметры запроса', 422)
  }
  if (!response.ok) {
    throw new SearchError('unavailable', `Сервис поиска ответил кодом ${response.status}`, response.status)
  }
  let data: unknown
  try {
    data = await response.json()
  } catch (error) {
    if (signal?.aborted) throw error
    throw new SearchError('unavailable', 'Ответ сервиса поиска — не JSON', response.status)
  }
  if (!isSearchResponse(data)) {
    throw new SearchError('unavailable', 'Ответ сервиса поиска не соответствует контракту API', response.status)
  }
  return data
}

const isObject = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null

function isPatentResult(value: unknown): value is PatentResult {
  return (
    isObject(value) &&
    typeof value.id === 'string' &&
    typeof value.title === 'string' &&
    typeof value.abstract === 'string' &&
    typeof value.score === 'number' &&
    Number.isFinite(value.score) &&
    Array.isArray(value.ipc) &&
    value.ipc.every((code) => typeof code === 'string') &&
    typeof value.year === 'number' &&
    Number.isInteger(value.year)
  )
}

/** Проверка ответа по контракту: поля и типы, которые нужны интерфейсу. */
export function isSearchResponse(value: unknown): value is SearchResponse {
  return (
    isObject(value) &&
    typeof value.query === 'string' &&
    typeof value.answer === 'string' &&
    Array.isArray(value.results) &&
    value.results.every(isPatentResult)
  )
}
