import { Activity, BookOpen, ChefHat, Film, Moon, Palette, PartyPopper, Play, Power, Sofa, Sparkles, Square, Sun, Sunset, Target, Trash2 } from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import {
  latestScene, SCENE_COLOURS, SCENE_GRADIENTS, SCENE_STYLES, SCENES_STYLES, sceneSign,
  type ActionState, type HomeScene, type HomeScenes, type SceneColour, type SceneStyle, type ScenesStyle,
} from '../../lib/home'
import { Dialog } from '../ui'
import { Marquee } from './Marquee'
import { SensorTools } from './SensorControl'

/** How long a scene says it was set off. */
const FIRED_MS = 2500

const SIGNS: Record<string, ReactNode> = {
  film: <Film size={18} />, moon: <Moon size={18} />, book: <BookOpen size={18} />, chef: <ChefHat size={18} />, party: <PartyPopper size={18} />,
  power: <Power size={18} />, sunset: <Sunset size={18} />, sun: <Sun size={18} />, sofa: <Sofa size={18} />, target: <Target size={18} />, spark: <Sparkles size={18} />,
}

type Said = ActionState | undefined
const known = (said: Said) => (said && !said.missing ? said : null)

/** When, as a page writes it: the time today, else the date and the time. */
function when(moment: number | null | undefined, language: string): string {
  if (!moment) return ''
  const date = new Date(moment)
  const time = new Intl.DateTimeFormat(language, { hour: 'numeric', minute: '2-digit' }).format(date)
  return date.toDateString() === new Date().toDateString() ? time : `${new Intl.DateTimeFormat(language, { day: 'numeric', month: 'numeric' }).format(date)} ${time}`
}

/** A scene set off a moment ago says so; a script says while it runs. */
function useFired(): [boolean, () => void] {
  const [fired, setFired] = useState(false)
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => () => window.clearTimeout(timer.current), [])
  return [fired, () => {
    setFired(true)
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => setFired(false), FIRED_MS)
  }]
}

interface Props {
  element: HomeScene
  said: Said
  arranging: boolean
  wide: boolean
  width: number | null
  /** Null for who may only look. */
  onSetOff: ((stop?: boolean) => void) | null
  onStyle: (style: SceneStyle) => void
  onColour: (colour: SceneColour) => void
  onRemove: () => void
  haName: string
  onLabel: (label: string) => void
}

/**
 * A scene or a script: a tap sets it off. A scene has nothing to show but
 * that it was set off, a moment long, and when, in its details; a script
 * says while it runs and can be stopped.
 */
export function SceneControl({ element, said, arranging, wide, width, onSetOff, onStyle, onColour, onRemove, haName, onLabel }: Props) {
  const { t, i18n } = useTranslation()
  const info = known(said)
  const [fired, fire] = useFired()
  const [details, setDetails] = useState(false)
  const [colours, setColours] = useState(false)
  const name = element.label || info?.name || element.name
  const script = element.entity_id.startsWith('script.')
  const running = Boolean(script && info?.running)
  const live = Boolean(onSetOff) && !arranging && Boolean(info) && !info?.unavailable
  const quiet = !said || said.missing || Boolean(info?.unavailable)
  const text = !said ? '…' : said.missing ? t('homePage.sensors.missing') : info?.unavailable ? t('homePage.offline')
    : running ? t('homePage.scenes.running') : fired ? t('homePage.scenes.fired') : info?.area || (script ? t('homePage.scenes.script') : '')
  const go = () => {
    if (!live || running) return
    fire()
    onSetOff?.()
  }
  const main = {
    onClick: () => (arranging ? undefined : go()),
    onContextMenu: (event: React.MouseEvent) => {
      if (arranging) return
      event.preventDefault()
      setDetails(true)
    },
    role: 'button',
    tabIndex: arranging ? -1 : 0,
    onKeyDown: (event: React.KeyboardEvent) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault()
        go()
      }
    },
    'aria-label': `${name}: ${text}`,
    'data-main': '',
  }
  const state = `scene ${fired || running ? 'is-fired' : ''} ${quiet && !said?.missing ? 'is-offline' : ''} ${said?.missing ? 'is-missing' : ''}`
  const sized = wide ? { width: '100%' } : width !== null ? { width } : undefined
  const colour = SCENE_GRADIENTS[element.colour ?? 'sunset']
  const face = element.style === 'tile' ? (
    <div className={`sensor-tile reading ${state} cursor-pointer`} style={{ background: `linear-gradient(150deg, ${colour[0]}55, ${colour[1]}33 60%, var(--nd-surface))` }} {...main}>
      <span className="text-[11.5px] text-muted truncate">{info?.area || (script ? t('homePage.scenes.script') : '')}</span>
      <Marquee text={name} className="mt-auto text-[15px] font-semibold" />
      <span className="text-[11px] text-muted" data-state>{fired || running || quiet ? text : t('homePage.scenes.tap')}</span>
    </div>
  ) : (
    <div className={`sensor-pill ${state} cursor-pointer`} style={sized} {...main}>
      <span className="sensor-icon scene-icon">{script ? <Play size={14} /> : <Sparkles size={14} />}</span>
      <Marquee text={name} className="flex-1 font-medium" />
      <span className="sensor-state" data-state>{text}</span>
      {running && live && (
        <button type="button" className="cover-button is-stop" onClick={(event) => {
          event.stopPropagation()
          onSetOff?.(true)
        }} aria-label={t('homePage.scenes.stop', { name })}>
          <Square size={10} fill="currentColor" />
        </button>
      )}
    </div>
  )
  return (
    <div className={`relative ${wide && element.style === 'pill' ? 'w-full' : 'w-fit'}`} data-scene={element.entity_id} data-style={element.style}>
      {face}
      {arranging && (
        <SensorTools styles={SCENE_STYLES} current={element.style} group="sceneStyles" onStyle={(style) => onStyle(style as SceneStyle)} onRemove={onRemove}
          removeLabel={t('homePage.scenes.remove')} width={width} wide={wide} rename={{ label: element.label ?? '', fallback: haName, onLabel }}
          extra={element.style === 'tile' && (
            <span className="relative">
              <button type="button" className="btn btn-icon h-6 w-6 rounded-full glass-strong" onClick={() => setColours((open) => !open)} aria-label={t('homePage.scenes.colour')}
                title={t('homePage.scenes.colour')} aria-expanded={colours}>
                <Palette size={12} />
              </button>
              {colours && (
                <span className="absolute right-0 top-full mt-2 z-30 glass-strong rounded-xl p-1.5 shadow-2xl flex gap-1.5" role="menu" aria-label={t('homePage.scenes.colour')}>
                  {SCENE_COLOURS.map((one) => (
                    <button key={one} type="button" role="menuitemradio" aria-checked={(element.colour ?? 'sunset') === one} aria-label={t(`homePage.scenes.colours.${one}`)}
                      className="w-6 h-6 rounded-full border border-[var(--nd-border-strong)]" style={{ background: `linear-gradient(135deg, ${SCENE_GRADIENTS[one][0]}, ${SCENE_GRADIENTS[one][1]})` }}
                      onClick={() => {
                        setColours(false)
                        onColour(one)
                      }} />
                  ))}
                </span>
              )}
            </span>
          )} />
      )}
      {details && (
        <Dialog open onClose={() => setDetails(false)} title={name} size="sm">
          <div className="grid gap-4" data-scene-details>
            <p className="text-sm text-muted">
              {script ? (running ? t('homePage.scenes.running') : t('homePage.scenes.notRunning'))
                : info?.last ? t('homePage.scenes.lastAt', { time: when(info.last, i18n.language) }) : t('homePage.scenes.never')}
            </p>
            {live && (
              <div className="flex gap-2">
                {!running && <button type="button" className="btn btn-accent" onClick={go}><Play size={14} /> {script ? t('homePage.scenes.run') : t('homePage.scenes.setOff')}</button>}
                {running && <button type="button" className="btn" onClick={() => onSetOff?.(true)}><Square size={11} fill="currentColor" /> {t('homePage.scenes.stopWord')}</button>}
              </div>
            )}
          </div>
        </Dialog>
      )}
    </div>
  )
}

interface CardProps {
  element: HomeScenes
  actions: Record<string, ActionState>
  arranging: boolean
  wide: boolean
  width: number | null
  onSetOff: ((member: string) => void) | null
  onStyle: (style: ScenesStyle) => void
  onSensors: () => void
  onRemove: () => void
}

/** C: the scenes of a room as one bar, the one set off last lit; D: a grid of scenes with a sign each. */
export function ScenesCard({ element, actions, arranging, wide, width, onSetOff, onStyle, onSensors, onRemove }: CardProps) {
  const { t } = useTranslation()
  const [choosing, setChoosing] = useState(false)
  const lit = latestScene(element.sensors, actions)
  const size = wide ? undefined : width !== null ? { width } : undefined
  const room = element.sensors.map((one) => known(actions[one.entity_id])?.area).find(Boolean)
  const title = element.title || room || t('homePage.scenes.scenes')
  const live = Boolean(onSetOff) && !arranging
  return (
    <div className={`relative ${wide ? 'w-full' : 'w-fit'}`} data-scenes={element.id} data-style={element.style}>
      {element.style === 'bar' ? (
        <div style={size}>
          <div className="text-[12px] text-muted mb-1.5 truncate">{title}</div>
          <div className="stat-card scene-bar" role="group" aria-label={title}>
            {element.sensors.map((sensor) => {
              const said = actions[sensor.entity_id]
              const info = known(said)
              const off = !info || info.unavailable
              return (
                <button key={sensor.entity_id} type="button" className={`scene-segment ${lit === sensor.entity_id ? 'is-on' : ''}`} disabled={!live || off} aria-pressed={lit === sensor.entity_id}
                  onClick={() => onSetOff?.(sensor.entity_id)} data-member={sensor.entity_id} title={said?.missing ? t('homePage.sensors.missing') : undefined}>
                  {info?.name || sensor.name}
                </button>
              )
            })}
          </div>
        </div>
      ) : (
        <div className="stat-card" style={size}>
          <b className="text-[13px] font-semibold">{title}</b>
          <div className="grid grid-cols-4 gap-2 mt-2.5">
            {element.sensors.map((sensor) => {
              const info = known(actions[sensor.entity_id])
              const name = info?.name || sensor.name
              return (
                <button key={sensor.entity_id} type="button" className={`scene-square ${lit === sensor.entity_id ? 'is-on' : ''}`} disabled={!live || !info || info.unavailable}
                  onClick={() => onSetOff?.(sensor.entity_id)} data-member={sensor.entity_id} aria-pressed={lit === sensor.entity_id}>
                  <span className="block mx-auto w-fit mb-1" aria-hidden>{SIGNS[sceneSign(name)]}</span>
                  <span className="block truncate">{name}</span>
                </button>
              )
            })}
          </div>
        </div>
      )}
      {arranging && (
        <>
          {!wide && <span className="home-grip" data-resize aria-hidden title={t('homePage.dragWidth')} />}
          <span className="absolute -top-3 -right-3 z-10 flex gap-1" data-element-tool>
            <button type="button" className="btn btn-icon h-6 w-6 rounded-full glass-strong" onClick={() => setChoosing((open) => !open)} aria-label={t('homePage.chooseStyle')}
              title={t('homePage.chooseStyle')} aria-haspopup="menu" aria-expanded={choosing}>
              <Palette size={12} />
            </button>
            <button type="button" className="btn btn-icon h-6 w-6 rounded-full glass-strong" onClick={onSensors} aria-label={t('homePage.stats.chooseSensors')} title={t('homePage.stats.chooseSensors')}>
              <Activity size={12} />
            </button>
            <button type="button" className="btn btn-icon btn-danger h-6 w-6 rounded-full glass-strong" onClick={onRemove} aria-label={t('homePage.sensors.removeCard')} title={t('homePage.sensors.removeCard')}>
              <Trash2 size={12} />
            </button>
          </span>
          {choosing && (
            <div className="absolute left-0 top-full mt-2 z-30 glass-strong rounded-xl p-1.5 shadow-2xl grid gap-1 w-64" role="menu" aria-label={t('homePage.chooseStyle')} data-element-tool>
              {SCENES_STYLES.map((style) => (
                <button key={style} type="button" role="menuitemradio" aria-checked={element.style === style}
                  className={`text-left text-[13px] px-2.5 py-1.5 rounded-lg ${element.style === style ? 'bg-[var(--nd-accent-soft)] text-accent font-medium' : 'hover:bg-[var(--nd-surface-hover)]'}`}
                  onClick={() => {
                    setChoosing(false)
                    onStyle(style)
                  }}>
                  {t(`homePage.scenes.cardStyles.${style}`)}
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
