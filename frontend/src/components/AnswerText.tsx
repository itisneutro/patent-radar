import { Fragment, useId, type ReactNode } from 'react'
import { ANSWER_DISCLAIMER, leadingRefId, parseParagraph, splitParagraphs } from '../lib/answer'
import { patentHash } from '../lib/route'
import { Info, Sparkle } from './Icons'

interface LlmPanelProps {
  /** id и текст заголовка блока: «Сводка» на «Выдаче», «Пояснение» в «Карточке патента». */
  titleId: string
  title: string
  children: ReactNode
  className?: string
}

/** Панель ответа языковой модели: отдельный заметный блок с акцентной рамкой и свечением. */
export function LlmPanel({ titleId, title, children, className = '' }: LlmPanelProps) {
  return (
    <section
      aria-labelledby={titleId}
      className={`relative overflow-hidden rounded-[1.25rem] border border-accent/40 bg-surface p-5 shadow-[0_24px_60px_-34px_var(--c-glow)] sm:p-7 ${className}`}
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 top-0 h-px bg-linear-to-r from-transparent via-accent to-transparent"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -top-24 -right-16 size-56 rounded-full bg-accent/10 blur-3xl"
      />
      <div className="relative flex items-center gap-3">
        <span className="inline-flex size-9 items-center justify-center rounded-full bg-accent/14 text-accent">
          <Sparkle className="size-[18px]" />
        </span>
        <h2 id={titleId} className="font-display text-lg font-semibold tracking-tight">
          {title}
        </h2>
      </div>
      <div className="relative mt-5">{children}</div>
    </section>
  )
}

interface AnswerTextProps {
  answer: string
  /** id патентов текущей выдачи: метки с этими номерами — ссылки на карточку. */
  resultIds: ReadonlySet<string>
}

/**
 * Текст блока «Сводка»: answer как простой текст, абзацы по пустой строке. Вводный абзац —
 * обычным текстом, абзацы о патентах — с акцентной линией слева и меткой [ID], дисклеймер — мелко внизу.
 */
export function AnswerText({ answer, resultIds }: AnswerTextProps) {
  return (
    <div className="max-w-[72ch] space-y-4 text-[15.5px] leading-relaxed">
      {splitParagraphs(answer).map((paragraph, index) => {
        if (paragraph === ANSWER_DISCLAIMER) {
          return (
            <p key={index} className="flex items-start gap-2.5 border-t border-line pt-4 text-sm leading-5 text-muted">
              <Info className="mt-px size-4 shrink-0" />
              <span>{paragraph}</span>
            </p>
          )
        }
        const aboutPatent = leadingRefId(paragraph) !== null
        return (
          <AnswerParagraph
            key={index}
            paragraph={paragraph}
            resultIds={resultIds}
            className={aboutPatent ? 'border-l-2 border-accent/60 pl-4 text-ink' : 'text-ink-soft'}
          />
        )
      })}
    </div>
  )
}

interface AnswerParagraphProps {
  paragraph: string
  resultIds: ReadonlySet<string>
  /** Номер открытой карточки: метка на неё не ссылается сама на себя. */
  currentId?: string
  className?: string
}

/** Абзац пояснения: текст с метками [ID]. */
export function AnswerParagraph({ paragraph, resultIds, currentId, className = '' }: AnswerParagraphProps) {
  return (
    <p className={`whitespace-pre-line ${className}`}>
      {parseParagraph(paragraph).map((part, index) =>
        part.kind === 'text' ? (
          <Fragment key={index}>{part.text}</Fragment>
        ) : (
          <RefTag key={index} id={part.id} known={resultIds.has(part.id)} current={part.id === currentId} />
        ),
      )}
    </p>
  )
}

function RefTag({ id, known, current }: { id: string; known: boolean; current: boolean }) {
  if (current) return <span className="ref-tag ref-tag-current">[{id}]</span>
  if (known) {
    return (
      <a href={patentHash(id)} className="ref-tag">
        [{id}]
      </a>
    )
  }
  return <UnknownRefTag id={id} />
}

/** Номер, которого нет в выдаче: метка некликабельна, подсказка видна при наведении и фокусе. */
function UnknownRefTag({ id }: { id: string }) {
  const hintId = useId()
  return (
    <span className="group relative inline-block">
      <span tabIndex={0} aria-describedby={hintId} className="ref-tag ref-tag-unknown">
        [{id}]
      </span>
      <span
        role="tooltip"
        id={hintId}
        className="pointer-events-none absolute left-0 top-full z-10 mt-1.5 hidden w-max max-w-[16rem] rounded-lg border border-line bg-raised px-2.5 py-1.5 text-xs leading-4 text-ink shadow-lg group-focus-within:block group-hover:block"
      >
        Номер отсутствует в выдаче
      </span>
    </span>
  )
}
