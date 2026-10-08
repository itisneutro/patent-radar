/**
 * Проверка ввода по правилам контракта API (spec/tech/architecture.md, «Контракт API»;
 * spec/product/scenarios.md, сценарий А3). Бэкенд проверяет то же самое (app/api/schemas.py),
 * поэтому при совпадении правил интерфейс не получает ответ 422.
 */
import type { SearchRequest } from '../api/types'

export const MIN_QUERY_WORDS = 3
export const MAX_QUERY_CHARS = 2000
export const MIN_YEAR = 1900
export const MAX_YEAR = 2100
export const MAX_IPC_CHARS = 20
export const MAX_TOP_K = 20
export const DEFAULT_TOP_K = 10
/** Значения поля «Количество результатов» (API допускает любое число от 1 до 20). */
export const TOP_K_OPTIONS: readonly number[] = [5, 10, 20]

/** Сообщения проверки — дословно из spec/product/scenarios.md. */
export const MESSAGES = {
  queryTooShort:
    'Запрос слишком короткий. Опишите идею хотя бы тремя словами: что это, из чего состоит и как работает.',
  queryTooLong: 'Запрос слишком длинный: сократите описание до 2000 символов.',
  yearInvalid: 'Год — целое число от 1900 до 2100.',
  yearRange: 'Начальный год не может быть больше конечного.',
} as const

/**
 * Слово — непрерывная последовательность букв или цифр; дефис и знаки препинания —
 * разделители, поэтому «Wi-Fi» — два слова. На бэкенде то же правило: [^\W_]+.
 */
const WORD = /[\p{L}\p{N}]+/gu

export function countWords(text: string): number {
  return text.match(WORD)?.length ?? 0
}

/** Длина в символах Unicode, как len() в Python: символ вне BMP (например, эмодзи) — один символ. */
export function charLength(text: string): number {
  return Array.from(text).length
}

/** Сообщение об ошибке в описании идеи или null. Порядок как в API: сначала длина, потом число слов. */
export function queryError(query: string): string | null {
  const text = query.trim()
  if (charLength(text) > MAX_QUERY_CHARS) return MESSAGES.queryTooLong
  if (countWords(text) < MIN_QUERY_WORDS) return MESSAGES.queryTooShort
  return null
}

const isYear = (value: number) => Number.isInteger(value) && value >= MIN_YEAR && value <= MAX_YEAR

/**
 * Проверяет тело запроса так же, как API: при false бэкенд ответил бы 422.
 * Используется моком; запросы с «Экрана запроса» проходят проверку раньше, в validateForm().
 */
export function isValidSearchRequest(request: SearchRequest): boolean {
  if (typeof request.query !== 'string' || queryError(request.query) !== null) return false
  const topK = request.top_k ?? DEFAULT_TOP_K
  if (!Number.isInteger(topK) || topK < 1 || topK > MAX_TOP_K) return false
  const yearFrom = request.year_from ?? null
  const yearTo = request.year_to ?? null
  if (yearFrom !== null && !isYear(yearFrom)) return false
  if (yearTo !== null && !isYear(yearTo)) return false
  if (yearFrom !== null && yearTo !== null && yearFrom > yearTo) return false
  const ipc = request.ipc ?? null
  return ipc === null || (typeof ipc === 'string' && charLength(ipc) <= MAX_IPC_CHARS)
}

/** Поля «Экрана запроса» в том виде, в каком их ввёл пользователь. */
export interface SearchForm {
  query: string
  yearFrom: string
  yearTo: string
  ipc: string
  topK: number
}

export const EMPTY_FORM: SearchForm = { query: '', yearFrom: '', yearTo: '', ipc: '', topK: DEFAULT_TOP_K }

export type YearField = 'yearFrom' | 'yearTo'

/** Сообщения проверки: под полем «Описание идеи» и под группой «Год публикации». */
export interface FormErrors {
  query?: string
  year?: string
  /** Поля года, к которым относится сообщение year (для aria-invalid и фокуса). */
  yearFields?: YearField[]
}

export const hasErrors = (errors: FormErrors) => Boolean(errors.query || errors.year)

/** Год из поля ввода: null — поле пустое; undefined — не целое число или вне 1900…2100. */
function parseYearInput(text: string): number | null | undefined {
  const value = text.trim()
  if (value === '') return null
  if (!/^\d+$/.test(value)) return undefined
  const year = Number(value)
  return isYear(year) ? year : undefined
}

/**
 * Проверяет поля «Экрана запроса». Без ошибок возвращает тело запроса: незаданные фильтры —
 * null, пустое поле МПК или поле из одних пробелов — тоже null.
 */
export function validateForm(form: SearchForm): { errors: FormErrors; request: SearchRequest | null } {
  const errors: FormErrors = {}
  const query = queryError(form.query)
  if (query) errors.query = query

  const yearFrom = parseYearInput(form.yearFrom)
  const yearTo = parseYearInput(form.yearTo)
  const invalidYears: YearField[] = []
  if (yearFrom === undefined) invalidYears.push('yearFrom')
  if (yearTo === undefined) invalidYears.push('yearTo')
  if (invalidYears.length > 0) {
    errors.year = MESSAGES.yearInvalid
    errors.yearFields = invalidYears
  } else if (yearFrom != null && yearTo != null && yearFrom > yearTo) {
    errors.year = MESSAGES.yearRange
    errors.yearFields = ['yearFrom', 'yearTo']
  }

  if (hasErrors(errors)) return { errors, request: null }
  return {
    errors,
    request: {
      query: form.query.trim(),
      top_k: form.topK,
      year_from: yearFrom ?? null,
      year_to: yearTo ?? null,
      ipc: form.ipc.trim() || null,
    },
  }
}

/**
 * Обновляет показанные сообщения после правки поля: сообщение исчезает, когда поле исправлено,
 * и меняет текст, если ошибка стала другой. Новые сообщения появляются только при нажатии
 * «Найти аналоги».
 */
export function refreshErrors(shown: FormErrors, current: FormErrors): FormErrors {
  const next: FormErrors = {}
  if (shown.query && current.query) next.query = current.query
  if (shown.year && current.year) {
    next.year = current.year
    next.yearFields = current.yearFields
  }
  return next
}

/** Заполняет поля «Экрана запроса» по параметрам запроса (кнопки «Изменить запрос», «Сбросить фильтры»). */
export function formFromRequest(request: SearchRequest): SearchForm {
  const topK = request.top_k ?? DEFAULT_TOP_K
  return {
    query: request.query,
    yearFrom: request.year_from == null ? '' : String(request.year_from),
    yearTo: request.year_to == null ? '' : String(request.year_to),
    ipc: request.ipc ?? '',
    topK: TOP_K_OPTIONS.includes(topK) ? topK : DEFAULT_TOP_K,
  }
}
