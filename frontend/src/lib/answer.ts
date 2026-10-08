/**
 * Разбор поля answer (spec/tech/architecture.md, формат answer): простой текст без Markdown,
 * абзацы разделены пустой строкой, абзац о патенте начинается с «[ID] », последний абзац —
 * дисклеймер, который добавляет API.
 */

/** Фиксированный дисклеймер: последний абзац любого непустого answer и текст подвала. */
export const ANSWER_DISCLAIMER =
  'Это первичный поиск аналогов, а не юридическое заключение о новизне или патентоспособности.'

/** Ссылка на патент в тексте: [DEMO-001] или [RU<номер><код вида>], например RU<7 цифр>C1. */
const REF = /\[(DEMO-\d{3}|RU\d+[A-Z]\d?)\]/g

export type AnswerPart = { kind: 'text'; text: string } | { kind: 'ref'; id: string }

/** Делит answer на абзацы по пустым строкам; пустые абзацы отбрасываются. */
export function splitParagraphs(answer: string): string[] {
  return answer
    .split(/\n[ \t]*\n/)
    .map((paragraph) => paragraph.trim())
    .filter((paragraph) => paragraph !== '')
}

/** Делит абзац на текст и ссылки [ID]. */
export function parseParagraph(paragraph: string): AnswerPart[] {
  const parts: AnswerPart[] = []
  let position = 0
  for (const match of paragraph.matchAll(REF)) {
    if (match.index > position) parts.push({ kind: 'text', text: paragraph.slice(position, match.index) })
    parts.push({ kind: 'ref', id: match[1] })
    position = match.index + match[0].length
  }
  if (position < paragraph.length) parts.push({ kind: 'text', text: paragraph.slice(position) })
  return parts
}

/** ID в начале абзаца вида «[ID] текст» или null (вводный абзац, дисклеймер). */
export function leadingRefId(paragraph: string): string | null {
  return /^\[([^[\]\s]+)\] /.exec(paragraph)?.[1] ?? null
}

/** Абзац пояснения о патенте: начинается с «[<id>] ». null — модель о нём не писала. */
export function findExplanation(answer: string, id: string): string | null {
  return splitParagraphs(answer).find((paragraph) => leadingRefId(paragraph) === id) ?? null
}
