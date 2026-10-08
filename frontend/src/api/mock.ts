/**
 * Мок POST /search для режима mock (КТ1). Ведёт себя так же, как заглушка бэкенда
 * app/api/stub.py (spec/tech/architecture.md, раздел о заглушке КТ1):
 * 1. Запрос проверяется по правилам контракта; если API ответил бы 422 — SearchError('rejected').
 * 2. Демо-тема: если запрос в нижнем регистре, с заменой «ё» на «е», содержит хотя бы одну
 *    основу из DEMO_TOPIC_STEMS, берутся три демо-патента из src/mock/search.json, иначе выдача пуста.
 * 3. Фильтры: год публикации (границы включаются) и префикс МПК — без учёта регистра и пробелов,
 *    по любому коду патента.
 * 4. Сортировка по убыванию score (при равенстве — по id) и обрезка до top_k.
 * 5. answer: при пустой выдаче — NO_RESULTS_ANSWER; иначе абзацы answer из мока без абзацев
 *    об отфильтрованных патентах (вводный абзац и дисклеймер остаются).
 * Для основного демо-запроса без фильтров ответ в точности равен src/mock/search.json.
 */
import { leadingRefId } from '../lib/answer'
import { DEFAULT_TOP_K, isValidSearchRequest } from '../lib/validation'
import demo from '../mock/search.json'
import { SearchError } from './errors'
import type { PatentResult, SearchRequest, SearchResponse } from './types'

/** Эталонный ответ: совпадает с ответом заглушки бэкенда на основной демо-запрос. */
const DEMO_RESPONSE: SearchResponse = demo

/** Основы слов демо-темы «полив и влажность почвы»; ищутся подстрокой в запросе. */
export const DEMO_TOPIC_STEMS: readonly string[] = [
  'полив',
  'влаг',
  'влажн',
  'почв',
  'грядк',
  'огород',
  'теплиц',
  'дожд',
  'осадк',
  'орош',
  'капельн',
  'пересох',
  'пересых',
]

/** answer при пустой выдаче (LLM в этом случае не вызывается и на КТ2). */
export const NO_RESULTS_ANSWER =
  'Похожих патентов в корпусе не найдено. Опишите идею иначе: назначение, из чего состоит и как работает, — или ослабьте фильтры по году и МПК.'

/** Задержка ответа, мс: чтобы было видно состояние «Загрузка». */
export const MOCK_DELAY_MS = 400

export function isDemoTopic(query: string): boolean {
  const normalized = query.toLowerCase().replaceAll('ё', 'е')
  return DEMO_TOPIC_STEMS.some((stem) => normalized.includes(stem))
}

/** Код или префикс МПК для сравнения: без пробелов, прописными. «g01n 33» → «G01N33». */
function normalizeIpc(code: string): string {
  return code.replace(/\s+/g, '').toUpperCase()
}

function matchesFilters(patent: PatentResult, yearFrom: number | null, yearTo: number | null, ipc: string | null) {
  if (yearFrom !== null && patent.year < yearFrom) return false
  if (yearTo !== null && patent.year > yearTo) return false
  if (ipc === null) return true
  const prefix = normalizeIpc(ipc)
  return patent.ipc.some((code) => normalizeIpc(code).startsWith(prefix))
}

/** По убыванию score, при равенстве — по id (посимвольно, как sort в Python). */
function byScoreThenId(a: PatentResult, b: PatentResult): number {
  if (a.score !== b.score) return b.score - a.score
  return a.id < b.id ? -1 : a.id > b.id ? 1 : 0
}

function buildAnswer(resultIds: readonly string[]): string {
  if (resultIds.length === 0) return NO_RESULTS_ANSWER
  const kept = new Set(resultIds)
  return DEMO_RESPONSE.answer
    .split('\n\n')
    .filter((paragraph) => {
      const id = leadingRefId(paragraph)
      return id === null || kept.has(id)
    })
    .join('\n\n')
}

/** Пауза, которую можно прервать: новый поиск отменяет предыдущий. */
function delay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason)
      return
    }
    const onAbort = () => {
      clearTimeout(timer)
      reject(signal?.reason)
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort)
      resolve()
    }, ms)
    signal?.addEventListener('abort', onAbort, { once: true })
  })
}

export async function mockSearch(request: SearchRequest, signal?: AbortSignal): Promise<SearchResponse> {
  await delay(MOCK_DELAY_MS, signal)
  if (!isValidSearchRequest(request)) {
    throw new SearchError('rejected', 'Мок: параметры запроса не прошли проверку контракта (как ответ 422)')
  }
  const query = request.query.trim()
  const ipc = request.ipc?.trim() || null
  const candidates = isDemoTopic(query) ? DEMO_RESPONSE.results : []
  const results = candidates
    .filter((patent) => matchesFilters(patent, request.year_from ?? null, request.year_to ?? null, ipc))
    .sort(byScoreThenId)
    .slice(0, request.top_k ?? DEFAULT_TOP_K)
    .map((patent) => ({ ...patent, ipc: [...patent.ipc] }))
  return { query, results, answer: buildAnswer(results.map((patent) => patent.id)) }
}
