import { useId, type CSSProperties } from 'react'

/** Цель на экране радара: угол по часовой стрелке от «12 часов» (0–360°) и расстояние от центра (0–1). */
export interface Blip {
  angle: number
  radius: number
}

/** «Находки» на главном экране: декоративные точки, к данным поиска не относятся. */
const SEARCH_BLIPS: readonly Blip[] = [
  { angle: 34, radius: 0.62 },
  { angle: 98, radius: 0.36 },
  { angle: 152, radius: 0.78 },
  { angle: 228, radius: 0.5 },
  { angle: 306, radius: 0.7 },
]

interface RadarScopeProps {
  /** Цели на экране; пустой список — радар без целей (состояние «Ничего не найдено»). */
  blips?: readonly Blip[]
  /** Период оборота луча, секунды. */
  period?: number
  /** Упрощённый вид без шкалы и подписей: маленький индикатор загрузки. */
  compact?: boolean
  className?: string
}

const CENTER = 100
const RADIUS = 96

/** Точка на экране по углу (по часовой от верха) и доле радиуса. */
function polar(angle: number, share: number): { x: number; y: number } {
  const radians = (angle * Math.PI) / 180
  return { x: CENTER + RADIUS * share * Math.sin(radians), y: CENTER - RADIUS * share * Math.cos(radians) }
}

/**
 * Экран радара: кольца, перекрестие, шкала, вращающаяся развёртка и цели. Чистые SVG и CSS,
 * без библиотек анимации. Луч проходит цель — она вспыхивает: задержка анимации каждой цели
 * отрицательная и пропорциональна её углу, поэтому вспышка совпадает с проходом луча.
 * При prefers-reduced-motion развёртка стоит, цели горят ровно (src/index.css).
 * Рисунок декоративный: aria-hidden.
 */
export function RadarScope({ blips = SEARCH_BLIPS, period = 4, compact = false, className = '' }: RadarScopeProps) {
  const id = useId()
  const faceId = `${id}-face`
  const style = { '--radar-period': `${period}s` } as CSSProperties
  const ticks = compact ? [] : Array.from({ length: 72 }, (_, index) => index * 5)

  return (
    <div aria-hidden="true" className={`relative aspect-square select-none ${className}`} style={style}>
      <svg viewBox="0 0 200 200" className="absolute inset-0 size-full overflow-visible">
        <defs>
          <radialGradient id={faceId} cx="50%" cy="50%" r="50%">
            <stop offset="0%" style={{ stopColor: 'var(--c-accent)', stopOpacity: 0.14 }} />
            <stop offset="70%" style={{ stopColor: 'var(--c-accent)', stopOpacity: 0.04 }} />
            <stop offset="100%" style={{ stopColor: 'var(--c-accent)', stopOpacity: 0.08 }} />
          </radialGradient>
        </defs>
        <circle cx={CENTER} cy={CENTER} r={RADIUS} fill={`url(#${faceId})`} stroke="var(--c-grid)" strokeWidth={compact ? 6 : 1.25} />
        {!compact &&
          [0.25, 0.5, 0.75].map((share) => (
            <circle key={share} cx={CENTER} cy={CENTER} r={RADIUS * share} fill="none" stroke="var(--c-grid)" strokeWidth="0.9" />
          ))}
        {!compact && (
          <g stroke="var(--c-grid)" strokeWidth="0.75">
            <line x1={CENTER - RADIUS} y1={CENTER} x2={CENTER + RADIUS} y2={CENTER} />
            <line x1={CENTER} y1={CENTER - RADIUS} x2={CENTER} y2={CENTER + RADIUS} />
            <line x1="32.1" y1="32.1" x2="167.9" y2="167.9" strokeDasharray="1.5 3" />
            <line x1="167.9" y1="32.1" x2="32.1" y2="167.9" strokeDasharray="1.5 3" />
          </g>
        )}
        {ticks.map((angle) => {
          const major = angle % 30 === 0
          const outer = polar(angle, 1)
          const inner = polar(angle, major ? 0.92 : 0.96)
          return (
            <line
              key={angle}
              x1={inner.x}
              y1={inner.y}
              x2={outer.x}
              y2={outer.y}
              stroke="var(--c-grid)"
              strokeWidth={major ? 1.2 : 0.7}
            />
          )
        })}
        {!compact &&
          [0, 90, 180, 270].map((angle) => {
            const point = polar(angle, 0.84)
            return (
              <text
                key={angle}
                x={point.x}
                y={point.y}
                textAnchor="middle"
                dominantBaseline="central"
                className="num fill-muted"
                style={{ fontSize: 6.5, letterSpacing: '0.08em' }}
              >
                {String(angle).padStart(3, '0')}
              </text>
            )
          })}
      </svg>

      <div
        className="radar-sweep absolute inset-[2%] rounded-full"
        style={{
          background:
            'conic-gradient(from 0deg, transparent 0deg 250deg, color-mix(in oklab, var(--c-accent) 5%, transparent) 290deg, color-mix(in oklab, var(--c-accent) 34%, transparent) 356deg, var(--c-accent) 360deg)',
        }}
      />

      <svg viewBox="0 0 200 200" className="absolute inset-0 size-full overflow-visible">
        {blips.map((blip) => {
          const point = polar(blip.angle, blip.radius)
          const blipStyle = { '--blip-delay': `${((blip.angle / 360 - 1) * period).toFixed(3)}s` } as CSSProperties
          return (
            <g key={`${blip.angle}-${blip.radius}`} style={blipStyle}>
              <circle className="radar-ping" cx={point.x} cy={point.y} r="3" fill="none" stroke="var(--c-accent)" strokeWidth="1" />
              <circle className="radar-blip" cx={point.x} cy={point.y} r="3.2" fill="var(--c-accent)" />
            </g>
          )
        })}
        <circle cx={CENTER} cy={CENTER} r={compact ? 9 : 2.6} fill="var(--c-accent)" />
      </svg>
    </div>
  )
}
