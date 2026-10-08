import { Info } from './Icons'

/**
 * Плашка демо-данных. Показывается на «Выдаче» и в «Карточке патента», если хотя бы у одной
 * показанной записи id начинается с DEMO- (отдельного поля для этого в ответе API нет).
 */
export function DemoBanner({ className = '' }: { className?: string }) {
  return (
    <p
      role="note"
      className={`flex items-start gap-3 rounded-2xl border border-warn/45 bg-warn/10 px-4 py-3 text-sm leading-5 text-warn ${className}`}
    >
      <Info className="mt-px size-[18px] shrink-0" />
      <span>
        Демонстрационные данные: записи <span className="num whitespace-nowrap">DEMO-xxx</span> — не реальные патенты. Результаты — не
        юридическое заключение.
      </span>
    </p>
  )
}

/** Бейдж у номера демонстрационной записи. */
export function DemoBadge() {
  return (
    <span
      title="Демонстрационные данные"
      className="inline-block rounded-md border border-warn/50 bg-warn/12 px-1.5 text-[10px] font-bold leading-[18px] tracking-[0.12em] text-warn"
    >
      ДЕМО
    </span>
  )
}
