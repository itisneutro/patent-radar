import { useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import type { SearchRequest } from '../api/types'
import { ArrowRight } from '../components/Icons'
import { RadarScope } from '../components/RadarScope'
import { EXAMPLE_QUERIES } from '../lib/examples'
import { buttonPrimary } from '../lib/ui'
import {
  charLength,
  hasErrors,
  MAX_IPC_CHARS,
  MAX_QUERY_CHARS,
  refreshErrors,
  TOP_K_OPTIONS,
  validateForm,
  type FormErrors,
  type SearchForm,
} from '../lib/validation'

interface SearchPageProps {
  form: SearchForm
  onChange: (form: SearchForm) => void
  /** Ввод прошёл проверку: открыть выдачу по этому запросу. */
  onSubmit: (request: SearchRequest) => void
}

/**
 * «Экран запроса» (маршрут #/): развёртка радара и крупное поле описания идеи с кнопкой
 * «Найти аналоги». Ввод проверяется при нажатии кнопки; при ошибке запрос не отправляется,
 * сообщение пропадает, когда поле исправлено (scenarios.md, А3).
 */
export function SearchPage({ form, onChange, onSubmit }: SearchPageProps) {
  const [errors, setErrors] = useState<FormErrors>({})
  const queryRef = useRef<HTMLTextAreaElement>(null)
  const yearFromRef = useRef<HTMLInputElement>(null)
  const yearToRef = useRef<HTMLInputElement>(null)

  const length = charLength(form.query.trim())
  const tooLong = length > MAX_QUERY_CHARS
  const yearInvalid = (field: 'yearFrom' | 'yearTo') => Boolean(errors.yearFields?.includes(field))

  function update(patch: Partial<SearchForm>) {
    const next = { ...form, ...patch }
    onChange(next)
    if (hasErrors(errors)) setErrors(refreshErrors(errors, validateForm(next).errors))
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const { errors: found, request } = validateForm(form)
    setErrors(found)
    if (request) {
      onSubmit(request)
      return
    }
    if (found.query) queryRef.current?.focus()
    else if (found.yearFields?.includes('yearFrom')) yearFromRef.current?.focus()
    else yearToRef.current?.focus()
  }

  /** Ctrl+Enter или Cmd+Enter в поле описания — то же, что «Найти аналоги». */
  function handleQueryKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault()
      event.currentTarget.form?.requestSubmit()
    }
  }

  const queryDescribedBy = errors.query ? 'query-error query-counter' : 'query-counter'
  // Фокус в поле виден по рамке всего блока: 2 px акцентного цвета и мягкое свечение вокруг.
  const composerBorder = errors.query
    ? 'border-danger focus-within:shadow-[0_0_0_1px_var(--c-danger),0_0_0_6px_color-mix(in_oklab,var(--c-danger)_22%,transparent)]'
    : 'border-line-strong focus-within:border-accent focus-within:shadow-[0_0_0_1px_var(--c-accent),0_0_0_6px_var(--c-glow)]'

  return (
    <div className="grid items-start gap-8 lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.15fr)] lg:gap-14">
      <div className="mx-auto w-full max-w-[220px] sm:max-w-[280px] lg:sticky lg:top-28 lg:row-span-2 lg:max-w-[460px]">
        <RadarScope className="w-full drop-shadow-[0_0_40px_var(--c-glow)]" />
      </div>

      <div className="min-w-0 lg:pt-6">
        <h1 className="font-display text-[2.375rem] font-semibold leading-[1.04] tracking-tight sm:text-6xl">
          Патентный <span className="text-accent">радар</span>
        </h1>
        <p className="mt-5 max-w-[56ch] text-[17px] leading-relaxed text-ink-soft sm:text-lg">
          Опишите идею изобретения своими словами — радар найдёт похожие патенты РФ и кратко объяснит, чем они похожи
          на вашу идею и чем отличаются.
        </p>
      </div>

      <form noValidate onSubmit={handleSubmit} className="min-w-0 space-y-8 lg:col-start-2">
        <div>
          <div
            className={`rounded-[1.25rem] border bg-raised/80 transition-[border-color,box-shadow] duration-200 ${composerBorder}`}
          >
            <label htmlFor="query" className="block px-5 pt-4 text-sm font-semibold text-ink-soft">
              Описание идеи
            </label>
            <textarea
              ref={queryRef}
              id="query"
              name="query"
              rows={6}
              value={form.query}
              onChange={(event) => update({ query: event.target.value })}
              onKeyDown={handleQueryKeyDown}
              placeholder="Опишите своими словами: что это, из чего состоит и как работает"
              aria-invalid={errors.query ? true : undefined}
              aria-describedby={queryDescribedBy}
              className="block min-h-40 w-full resize-y bg-transparent px-5 pb-4 pt-2 text-[17px] leading-relaxed text-ink outline-none focus-visible:outline-none sm:text-lg"
            />
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3 sm:px-5">
              <p
                id="query-counter"
                className={`num text-sm leading-5 ${tooLong ? 'font-semibold text-danger' : 'text-muted'}`}
              >
                {length} / {MAX_QUERY_CHARS}
              </p>
              <button type="submit" className={`${buttonPrimary} px-6 py-3 text-base`}>
                Найти аналоги
                <ArrowRight className="size-4" />
              </button>
            </div>
          </div>
          {/* Контейнер сообщения всегда в разметке (aria-live): сообщение озвучивается, даже если фокус уже в поле. */}
          <p id="query-error" aria-live="polite" className={`text-sm leading-5 text-danger ${errors.query ? 'mt-2.5' : ''}`}>
            {errors.query}
          </p>
        </div>

        <section aria-labelledby="examples-title">
          <h2 id="examples-title" className="caps">
            Примеры запросов
          </h2>
          <ul className="mt-3 grid gap-3 sm:grid-cols-2">
            {EXAMPLE_QUERIES.map((example) => (
              <li key={example.key}>
                <button
                  type="button"
                  onClick={() => update({ query: example.text })}
                  className="group flex size-full flex-col items-start justify-start rounded-2xl border border-line bg-surface/70 px-4 py-3.5 text-left transition-colors hover:border-accent/70 hover:bg-raised"
                >
                  <span className="block text-[15px] font-semibold text-accent">{example.label}</span>
                  <span aria-hidden="true" className="mt-1 line-clamp-2 text-sm leading-5 text-muted">
                    {example.text}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>

        <section aria-labelledby="filters-title" className="panel p-5 sm:p-6">
          <h2 id="filters-title" className="caps">
            Фильтры
          </h2>
          <div className="mt-4 grid gap-x-8 gap-y-6 sm:grid-cols-[auto_minmax(0,1fr)]">
            <fieldset>
              <legend className="text-sm font-semibold">Год публикации</legend>
              <div className="mt-2 flex items-center gap-2.5">
                <label htmlFor="year-from" className="text-sm text-ink-soft">
                  с
                </label>
                <input
                  ref={yearFromRef}
                  id="year-from"
                  name="year_from"
                  inputMode="numeric"
                  autoComplete="off"
                  maxLength={4}
                  value={form.yearFrom}
                  onChange={(event) => update({ yearFrom: event.target.value })}
                  aria-invalid={yearInvalid('yearFrom') ? true : undefined}
                  aria-describedby={errors.year ? 'year-error' : undefined}
                  className="field num h-10 w-[5.5rem] text-[15px]"
                />
                <label htmlFor="year-to" className="text-sm text-ink-soft">
                  по
                </label>
                <input
                  ref={yearToRef}
                  id="year-to"
                  name="year_to"
                  inputMode="numeric"
                  autoComplete="off"
                  maxLength={4}
                  value={form.yearTo}
                  onChange={(event) => update({ yearTo: event.target.value })}
                  aria-invalid={yearInvalid('yearTo') ? true : undefined}
                  aria-describedby={errors.year ? 'year-error' : undefined}
                  className="field num h-10 w-[5.5rem] text-[15px]"
                />
              </div>
              <p
                id="year-error"
                aria-live="polite"
                className={`max-w-[22rem] text-sm leading-5 text-danger ${errors.year ? 'mt-2' : ''}`}
              >
                {errors.year}
              </p>
            </fieldset>

            <div>
              <label htmlFor="ipc" className="block text-sm font-semibold">
                МПК (префикс)
              </label>
              <input
                id="ipc"
                name="ipc"
                autoComplete="off"
                autoCapitalize="characters"
                spellCheck={false}
                maxLength={MAX_IPC_CHARS}
                value={form.ipc}
                onChange={(event) => update({ ipc: event.target.value })}
                placeholder="например, A01G"
                className="field num mt-2 h-10 w-full max-w-[14rem] text-[15px]"
              />
            </div>

            <fieldset className="sm:col-span-2">
              <legend className="text-sm font-semibold">Количество результатов</legend>
              <div className="mt-2 inline-flex rounded-full border border-line-strong bg-raised p-1">
                {TOP_K_OPTIONS.map((value) => (
                  <label key={value} className="relative">
                    <input
                      type="radio"
                      name="top_k"
                      value={value}
                      checked={form.topK === value}
                      onChange={() => update({ topK: value })}
                      className="peer sr-only"
                    />
                    <span className="num block h-8 min-w-12 cursor-pointer rounded-full px-3.5 text-center text-[15px] leading-8 text-ink-soft transition-colors hover:text-ink peer-checked:bg-accent peer-checked:font-semibold peer-checked:text-accent-ink peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-accent">
                      {value}
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>
          </div>
        </section>
      </form>
    </div>
  )
}
