/**
 * The music player on this device: where what plays is shown, and how much
 * of the sound is fetched.
 *
 * ⚠️ Kept in the browser, not with the account, like the quality has been from
 * the start: a phone on the way wants less of the sound and has no top bar,
 * a desktop at home wants the original and may want the top bar.
 */
import { ArrowDownLeft, ArrowDownRight, ArrowUpLeft, ArrowUpRight, type LucideIcon } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { QUALITIES, type Quality } from '../../api/music'
import { Switch } from '../../components/ui'
import { BAR_CORNERS, usePlayer, type BarCorner, type BarStyle } from '../../stores/player'
import { SettingsCard } from './SettingsCard'

const CORNER_ICONS: Record<BarCorner, LucideIcon> = {
  'top-left': ArrowUpLeft,
  'top-right': ArrowUpRight,
  'bottom-left': ArrowDownLeft,
  'bottom-right': ArrowDownRight,
}

const CORNER_KEYS: Record<BarCorner, string> = {
  'top-left': 'topLeft',
  'top-right': 'topRight',
  'bottom-left': 'bottomLeft',
  'bottom-right': 'bottomRight',
}

export function PlayerSettings() {
  const { t } = useTranslation()
  const style = usePlayer((state) => state.barStyle)
  const corner = usePlayer((state) => state.barCorner)
  const collapsed = usePlayer((state) => state.barCollapsed)
  const quality = usePlayer((state) => state.quality)
  const player = usePlayer.getState()

  return (
    <>
      <SettingsCard title={t('settings.player.showTitle')} description={t('settings.player.showHelp')}>
        <div className="flex flex-wrap gap-2" role="group" aria-label={t('settings.player.showTitle')}>
          {(['floating', 'header'] as BarStyle[]).map((one) => (
            <button key={one} type="button" className="btn" aria-pressed={style === one} onClick={() => player.setBarStyle(one)}>
              {t(`settings.player.style.${one}`)}
            </button>
          ))}
        </div>
        {style === 'header' && <p className="text-[12px] text-muted mt-2">{t('settings.player.headerHint')}</p>}

        <div className="mt-5">
          <p className="text-sm font-medium mb-1">{t('settings.player.corner')}</p>
          <p className="text-[12px] text-muted mb-2">{t('settings.player.cornerHelp')}</p>
          {/* The four corners laid out as the screen is. */}
          <div className="grid grid-cols-2 gap-2 w-fit" role="group" aria-label={t('settings.player.corner')}>
            {BAR_CORNERS.map((one) => {
              const Icon = CORNER_ICONS[one]
              return (
                <button key={one} type="button" className="btn justify-start min-w-36" aria-pressed={corner === one} onClick={() => player.setBarCorner(one)}>
                  <Icon size={14} /> {t(`settings.player.corners.${CORNER_KEYS[one]}`)}
                </button>
              )
            })}
          </div>
        </div>

        <div className="mt-5 max-w-md">
          <Switch checked={collapsed} onChange={(value) => player.setBarCollapsed(value)} label={t('settings.player.collapsed')} description={t('settings.player.collapsedHelp')} />
        </div>
      </SettingsCard>

      <SettingsCard title={t('settings.player.qualityTitle')} description={t('settings.player.qualityHelp')}>
        <div className="flex flex-wrap gap-2" role="group" aria-label={t('settings.player.qualityTitle')}>
          {QUALITIES.map((one: Quality) => (
            <button key={one} type="button" className="btn" aria-pressed={quality === one} onClick={() => player.setQuality(one)}>
              {t(`player.quality.${one}`)}
            </button>
          ))}
        </div>
      </SettingsCard>
    </>
  )
}
