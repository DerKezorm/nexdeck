import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

/**
 * What a wall display shows while nobody is looking: the time, large, the
 * day, the weather when the board has it, and whether anything is down,
 * on black. Every minute it moves a few pixels, so a screen that shows it
 * for nights on end does not burn the numbers in. A touch brings the board
 * back.
 */
export interface Rest {
  weather?: { value: number | string; unit: string; condition: string; place: string } | null
  /** The names of the cards that are down. */
  down: string[]
}

/** Where the picture stands this minute: a few pixels off the middle, a new place each time. */
export function nudge(random: () => number = Math.random): { x: number; y: number } {
  return { x: Math.round((random() - 0.5) * 48), y: Math.round((random() - 0.5) * 32) }
}

export function WallRest({ rest, onWake }: { rest: Rest; onWake: () => void }) {
  const { t, i18n } = useTranslation()
  const [now, setNow] = useState(() => new Date())
  const [place, setPlace] = useState({ x: 0, y: 0 })
  useEffect(() => {
    const clock = window.setInterval(() => setNow(new Date()), 15_000)
    const wander = window.setInterval(() => setPlace(nudge()), 60_000)
    return () => {
      window.clearInterval(clock)
      window.clearInterval(wander)
    }
  }, [])
  const time = now.toLocaleTimeString(i18n.language, { hour: '2-digit', minute: '2-digit' })
  const day = now.toLocaleDateString(i18n.language, { weekday: 'long', day: 'numeric', month: 'long' })
  return (
    <div className="fixed inset-0 z-[60] bg-black text-slate-100 cursor-none select-none" onPointerDown={onWake} role="button" tabIndex={0} aria-label={t('kiosk.restWake')} data-testid="wall-rest">
      <div className="absolute left-1/2 top-1/2 text-center transition-transform duration-[3000ms] ease-in-out" style={{ transform: `translate(calc(-50% + ${place.x}px), calc(-50% + ${place.y}px))` }}>
        <div className="num font-semibold leading-none tracking-tight text-[clamp(72px,16vw,220px)]">{time}</div>
        <div className="mt-2 text-[clamp(16px,2.4vw,30px)] text-slate-400">{day}</div>
        <div className="mt-10 flex flex-wrap items-center justify-center gap-x-10 gap-y-3 text-[clamp(15px,2vw,24px)] text-slate-300">
          {rest.weather && (
            <span>
              <span className="num">{String(rest.weather.value)}</span>
              {rest.weather.unit} · <span className="capitalize">{rest.weather.condition.replace('-', ' ')}</span>
              {rest.weather.place ? ` · ${rest.weather.place}` : ''}
            </span>
          )}
          <span className="flex items-center gap-3" data-testid="rest-state">
            <span className="h-3 w-3 rounded-full" style={{ background: rest.down.length ? 'var(--nd-bad)' : 'var(--nd-ok)' }} />
            {rest.down.length ? `${t('kiosk.restDown', { count: rest.down.length })} · ${rest.down.slice(0, 3).join(', ')}` : t('kiosk.restFine')}
          </span>
        </div>
      </div>
      <div className="absolute bottom-4 inset-x-0 text-center text-[12px] text-slate-700">{t('kiosk.restWake')}</div>
    </div>
  )
}
