import { Activity, ChevronDown, ChevronUp, Palette, Square, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { COVERS_STYLES, sceneHolds, type CoverState, type CoversStyle, type CoverWish, type HomeCovers } from '../../lib/home'
import { coverWords } from './CoverControl'

interface Props {
  element: HomeCovers
  covers: Record<string, CoverState>
  /** Positions asked and not yet answered, by entity id. */
  aims: Record<string, number>
  arranging: boolean
  wide: boolean
  width: number | null
  /** Null for who may only look. */
  onWish: ((wish: CoverWish) => void) | null
  /** The details of one cover of the card. */
  onDetails: (entity: string) => void
  onStyle: (style: CoversStyle) => void
  onSensors: () => void
  onRemove: () => void
}

/**
 * F: covers moved together, all up, stop or all down, each with where it
 * stands and its details at a tap; G: positions of the card's own, a tap sends
 * every cover of the card there, and the one they all stand at is lit.
 */
export function CoversCard({ element, covers, aims, arranging, wide, width, onWish, onDetails, onStyle, onSensors, onRemove }: Props) {
  const { t } = useTranslation()
  const [choosing, setChoosing] = useState(false)
  const live = Boolean(onWish) && !arranging
  const states = element.sensors.map((sensor) => covers[sensor.entity_id])
  const size = wide ? undefined : width !== null ? { width } : undefined
  const stoppable = states.some((one) => one && !one.missing && one.stoppable)
  const title = element.title || (element.style === 'scenes' ? t('homePage.covers.allCovers') : t('homePage.covers.group'))
  return (
    <div className={`relative ${wide ? 'w-full' : 'w-fit'}`} data-covers={element.id} data-style={element.style}>
      <div className="stat-card" style={size}>
        <div className="flex items-center gap-2">
          <b className="text-[13px] font-semibold truncate">{title}</b>
          {element.style === 'group' && live && (
            <span className="ml-auto flex gap-1.5">
              <button type="button" className="cover-button" onClick={() => onWish?.({ action: 'open' })} aria-label={t('homePage.covers.raiseAll')}><ChevronUp size={15} /></button>
              {stoppable && <button type="button" className="cover-button" onClick={() => onWish?.({ action: 'stop' })} aria-label={t('homePage.covers.stopAll')}><Square size={10} fill="currentColor" /></button>}
              <button type="button" className="cover-button" onClick={() => onWish?.({ action: 'close' })} aria-label={t('homePage.covers.lowerAll')}><ChevronDown size={15} /></button>
            </span>
          )}
        </div>
        {element.style === 'group' ? (
          <ul className="grid gap-1.5 mt-2.5">
            {element.sensors.map((sensor) => {
              const said = covers[sensor.entity_id]
              const words = coverWords(said, aims[sensor.entity_id], t)
              const name = said && !said.missing && said.name ? said.name : sensor.name
              return (
                <li key={sensor.entity_id}>
                  <button type="button" className={`w-full flex items-center gap-2 text-[12.5px] text-left rounded-lg px-1 -mx-1 hover:bg-[var(--nd-surface-hover)] ${words.quiet ? 'text-muted' : ''}`}
                    onClick={() => !arranging && onDetails(sensor.entity_id)} data-member={sensor.entity_id} disabled={arranging}>
                    <span className="truncate flex-1 min-w-0">{name}</span>
                    {!words.quiet && <span className="cover-track-row" aria-hidden><i style={{ width: `${words.position ?? 0}%` }} /></span>}
                    <small className={`num text-[11px] whitespace-nowrap min-w-10 text-right ${words.missing ? 'text-bad' : words.moving ? 'cover-moving-text' : 'text-muted'}`}>
                      {words.quiet || words.moving ? words.text : `${words.position} %`}
                    </small>
                  </button>
                </li>
              )
            })}
          </ul>
        ) : (
          <div className="grid grid-cols-3 gap-2 mt-2.5">
            {(element.scenes ?? []).map((scene, index) => {
              const on = sceneHolds(scene, states)
              return (
                <button key={index} type="button" className={`cover-scene ${on ? 'is-on' : ''}`} disabled={!live} onClick={() => onWish?.({ scene: index })} aria-pressed={on} data-scene={index}>
                  <span className="truncate block">{scene.name}</span>
                  <b className="num block text-[16px] mt-0.5">{scene.position} %</b>
                </button>
              )
            })}
          </div>
        )}
      </div>
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
              {COVERS_STYLES.map((style) => (
                <button key={style} type="button" role="menuitemradio" aria-checked={element.style === style}
                  className={`text-left text-[13px] px-2.5 py-1.5 rounded-lg ${element.style === style ? 'bg-[var(--nd-accent-soft)] text-accent font-medium' : 'hover:bg-[var(--nd-surface-hover)]'}`}
                  onClick={() => {
                    setChoosing(false)
                    onStyle(style)
                  }}>
                  {t(`homePage.covers.cardStyles.${style}`)}
                </button>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
