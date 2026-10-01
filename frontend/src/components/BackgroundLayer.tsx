/**
 * The stage behind every board: a soft aurora by default, an uploaded image
 * with blur and dim when the board has one. Fixed, behind everything, and
 * never a network request unless the owner uploaded something. It turns
 * faintly red while a card on the board is down.
 *
 * Three of the shipped grounds move: an aurora that drifts, a sky of stars,
 * and one that follows the hour. They are drawn by the browser alone, with
 * a handful of elements, so a tablet on the wall can run them for weeks;
 * with less motion asked for they hold still.
 */
import { useEffect, useState } from 'react'

export interface Background {
  kind: string
  value?: string
  blur?: number
  dim?: number
}

export const BUNDLED: Record<string, string> = {
  aurora:
    'radial-gradient(1200px 600px at 8% -10%, var(--nd-aurora-1), transparent 60%), radial-gradient(900px 520px at 92% 8%, var(--nd-aurora-2), transparent 60%), radial-gradient(900px 600px at 50% 115%, var(--nd-aurora-3), transparent 60%)',
  dusk: 'radial-gradient(1000px 600px at 20% 0%, rgba(244,114,182,0.26), transparent 60%), radial-gradient(900px 600px at 90% 100%, rgba(129,140,248,0.26), transparent 60%)',
  ember: 'radial-gradient(1000px 600px at 90% -10%, rgba(251,146,60,0.28), transparent 60%), radial-gradient(900px 600px at 0% 100%, rgba(244,63,94,0.2), transparent 60%)',
  ocean: 'radial-gradient(1100px 600px at 50% -20%, rgba(14,165,233,0.3), transparent 60%), radial-gradient(900px 600px at 100% 100%, rgba(20,184,166,0.22), transparent 60%)',
  forest: 'radial-gradient(1100px 600px at 0% 0%, rgba(34,197,94,0.24), transparent 60%), radial-gradient(900px 600px at 100% 90%, rgba(132,204,22,0.18), transparent 60%)',
  violet: 'radial-gradient(1100px 600px at 80% -10%, rgba(168,85,247,0.3), transparent 60%), radial-gradient(900px 600px at 10% 100%, rgba(99,102,241,0.24), transparent 60%)',
  mono: 'radial-gradient(1100px 600px at 50% -20%, rgba(148,163,184,0.12), transparent 60%)',
  none: 'none',
}

/** The grounds that move, with what their button shows. */
export const LIVING: Record<string, string> = {
  flow: 'radial-gradient(300px 120px at 20% 20%, var(--nd-aurora-1), transparent 70%), radial-gradient(260px 120px at 80% 70%, var(--nd-aurora-2), transparent 70%), radial-gradient(200px 100px at 50% 100%, var(--nd-aurora-3), transparent 70%)',
  stars: 'radial-gradient(1.5px 1.5px at 20% 30%, #fff, transparent), radial-gradient(1.5px 1.5px at 70% 20%, #fff, transparent), radial-gradient(1px 1px at 45% 70%, #fff, transparent), radial-gradient(1px 1px at 85% 60%, #fff, transparent), radial-gradient(600px 300px at 70% -20%, rgba(76,70,180,0.35), transparent 60%)',
  daytime: 'linear-gradient(90deg, rgba(76,70,180,0.35), rgba(251,146,60,0.3), rgba(56,189,248,0.3), rgba(249,115,22,0.3), rgba(76,70,180,0.35))',
}

/**
 * The colour of the sky at an hour: deep blue at night, rose at dawn, a clear
 * blue by day, orange at dusk. Dark enough in every hour that the cards stay
 * the brightest thing on the page.
 */
export function skyAt(hour: number): { ground: string; night: boolean } {
  if (hour < 5 || hour >= 22) {
    return { night: true, ground: 'radial-gradient(1200px 700px at 70% -20%, rgba(76,70,180,0.30), transparent 60%), radial-gradient(900px 600px at 0% 110%, rgba(30,41,90,0.35), transparent 60%)' }
  }
  if (hour < 8) {
    return { night: false, ground: 'radial-gradient(1200px 600px at 0% 110%, rgba(251,146,60,0.28), transparent 60%), radial-gradient(1000px 600px at 60% -10%, rgba(244,114,182,0.22), transparent 60%)' }
  }
  if (hour < 17) {
    return { night: false, ground: 'radial-gradient(1300px 700px at 50% -20%, rgba(56,189,248,0.24), transparent 60%), radial-gradient(900px 600px at 100% 100%, rgba(45,212,191,0.14), transparent 60%)' }
  }
  if (hour < 20) {
    return { night: false, ground: 'radial-gradient(1200px 600px at 100% 110%, rgba(249,115,22,0.30), transparent 60%), radial-gradient(1000px 600px at 20% -10%, rgba(168,85,247,0.24), transparent 60%)' }
  }
  return { night: true, ground: 'radial-gradient(1200px 600px at 100% 100%, rgba(124,58,237,0.26), transparent 60%), radial-gradient(1000px 600px at 0% -10%, rgba(30,64,175,0.28), transparent 60%)' }
}

/** The hour, read again every ten minutes: the sky does not need the second. */
function useHour(enabled: boolean): number {
  const [hour, setHour] = useState(() => new Date().getHours())
  useEffect(() => {
    if (!enabled) return
    const timer = window.setInterval(() => setHour(new Date().getHours()), 10 * 60_000)
    return () => window.clearInterval(timer)
  }, [enabled])
  return hour
}

/**
 * Stars as a few layers of box shadows on one dot each, not as a hundred
 * elements: the same picture for a fraction of the work. The places are the
 * same on every load, so the sky does not jump on a reload.
 */
function starShadows(seed: number, count: number): string {
  let state = seed
  const next = () => {
    state = (state * 1103515245 + 12345) % 2147483648
    return state / 2147483648
  }
  const dots: string[] = []
  for (let index = 0; index < count; index += 1) dots.push(`${(next() * 100).toFixed(2)}vw ${(next() * 100).toFixed(2)}vh 0 ${next() < 0.15 ? 1 : 0}px rgba(255,255,255,${(0.5 + next() * 0.5).toFixed(2)})`)
  return dots.join(', ')
}
export const STARS = [starShadows(7, 70), starShadows(19, 60), starShadows(43, 50)]

/** Each layer twinkles at its own pace; written out, so the class guard can find them. */
const LAYERS = ['nd-star-layer-1', 'nd-star-layer-2', 'nd-star-layer-3']

function Stars() {
  return (
    <div className="nd-stars absolute inset-0" data-testid="background-stars">
      {STARS.map((shadows, index) => (
        <i key={index} className={`nd-star-layer ${LAYERS[index]}`} style={{ boxShadow: shadows }} />
      ))}
    </div>
  )
}

function Flow() {
  return (
    <div className="absolute inset-0" data-testid="background-flow">
      <i className="nd-blob nd-blob-1" />
      <i className="nd-blob nd-blob-2" />
      <i className="nd-blob nd-blob-3" />
    </div>
  )
}


/** The red behind a board with a card down: two soft glows, like the aurora but in the colour of trouble. */
const ALARM =
  'radial-gradient(1100px 600px at 85% -10%, color-mix(in srgb, var(--nd-bad) 26%, transparent), transparent 60%), radial-gradient(900px 600px at 0% 110%, color-mix(in srgb, var(--nd-bad) 16%, transparent), transparent 60%)'

export function BackgroundLayer({ background, alarm = false }: { background?: Background; alarm?: boolean }) {
  const kind = background?.kind ?? 'bundled'
  const blur = background?.blur ?? 18
  const dim = background?.dim ?? 45
  const isImage = kind === 'upload' || kind === 'url'
  const name = kind === 'bundled' || kind === 'gradient' ? (background?.value ?? 'aurora') : 'aurora'
  const living = !isImage && name in LIVING ? name : ''
  const hour = useHour(living === 'daytime')
  const sky = skyAt(hour)
  const gradient = BUNDLED[name] ?? BUNDLED.aurora
  return (
    <div className="fixed inset-0 -z-10 overflow-hidden" aria-hidden="true" data-background>
      <div className="absolute inset-0" style={{ background: 'var(--nd-bg)' }} />
      {isImage && background?.value ? (
        <div
          className="absolute -inset-6 bg-cover bg-center"
          style={{
            backgroundImage: `url(${background.value})`,
            filter: `blur(${blur}px)`,
            transform: 'scale(1.05)',
          }}
        />
      ) : living === 'flow' ? (
        <Flow />
      ) : living === 'stars' ? (
        <>
          <div className="absolute inset-0 opacity-50" style={{ background: BUNDLED.aurora }} />
          <Stars />
        </>
      ) : living === 'daytime' ? (
        <>
          <div className="absolute inset-0 transition-[background] duration-1000" style={{ background: sky.ground }} data-testid="background-sky" data-hour={hour} />
          {sky.night && <Stars />}
        </>
      ) : (
        <div className="absolute inset-0" style={{ background: gradient }} />
      )}
      {isImage && <div className="absolute inset-0" style={{ background: `rgba(6,9,14,${dim / 100})` }} />}
      {/* A card on the board is red: the room turns a little red as well, so a
          wall display says it from across the room. Faded in and out, never
          blinking, and always there so the fade has something to run on. */}
      <div className="absolute inset-0 transition-opacity duration-[1200ms]" style={{ opacity: alarm ? 1 : 0, background: ALARM }} data-testid="background-alarm" data-on={alarm ? 'true' : 'false'} />
      <div
        className="absolute inset-0 opacity-[0.35]"
        style={{
          backgroundImage:
            'linear-gradient(color-mix(in srgb, var(--nd-text) 4%, transparent) 1px, transparent 1px), linear-gradient(90deg, color-mix(in srgb, var(--nd-text) 4%, transparent) 1px, transparent 1px)',
          backgroundSize: '48px 48px',
          maskImage: 'radial-gradient(ellipse at 50% 0%, black 20%, transparent 75%)',
        }}
      />
    </div>
  )
}
