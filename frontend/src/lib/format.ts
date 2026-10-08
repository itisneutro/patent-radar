/** Форматы значений (spec/product/scenarios.md, «Форматы значений»). */

/** Оценка BM25 — два знака после точки, как в API: 12.47. */
export const formatScore = (score: number) => score.toFixed(2)

/** Год — без разделителя разрядов (не toLocaleString): 2021. */
export const formatYear = (year: number) => String(year)

/** Демонстрационная запись — id с префиксом DEMO-. Отдельного поля в ответе API нет. */
export const isDemoId = (id: string) => id.startsWith('DEMO-')

/** Строка фильтра года: «с 2022», «по 2020», «с 2000 по 2010»; null — год не задан. */
export function describeYears(yearFrom: number | null, yearTo: number | null): string | null {
  if (yearFrom !== null && yearTo !== null) return `с ${yearFrom} по ${yearTo}`
  if (yearFrom !== null) return `с ${yearFrom}`
  if (yearTo !== null) return `по ${yearTo}`
  return null
}
