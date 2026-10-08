/**
 * Вид ошибки поиска (spec/product/scenarios.md, сценарий А5):
 * - rejected — API не принял параметры запроса (ответ 422) → состояние «Запрос отклонён»;
 * - unavailable — сервис не ответил, ответил кодом 5xx или ответ нельзя разобрать
 *   → состояние «Сервис недоступен».
 */
export type SearchErrorKind = 'rejected' | 'unavailable'

/** Ошибка searchPatents(). Текст сообщения — для консоли разработчика, интерфейс его не показывает. */
export class SearchError extends Error {
  readonly kind: SearchErrorKind
  /** HTTP-код ответа; null — ответа не было (сетевая ошибка) или ошибку сформировал мок. */
  readonly status: number | null

  constructor(kind: SearchErrorKind, message: string, status: number | null = null) {
    super(message)
    this.name = 'SearchError'
    this.kind = kind
    this.status = status
  }
}
