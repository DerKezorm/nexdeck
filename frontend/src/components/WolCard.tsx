/**
 * Wake-on-LAN, drawn two ways.
 *
 * `detail` is the card as it was: what the machine is doing, its address, and
 * a button. `icon` is the whole card as one button, for somebody who wants a
 * small tile in a corner and already knows which machine it is.
 */
import { Power } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import type { Action } from '../lib/types'
import type { RenderProps } from './renderers'

export function WolCard({ widget, data, canAct, onAction }: RenderProps) {
  const { t } = useTranslation()
  const wake = (data?.actions as Action[] | undefined)?.find((one) => one.id === 'wake')
  const awake = data?.meta?.awake as boolean | null | undefined
  const mac = data?.secondary?.find((row) => row.label === 'MAC')?.value
  const host = String(data?.primary?.value ?? '')
  const state = awake === true ? 'ok' : awake === false ? 'warn' : 'unknown'

  function press() {
    if (wake && canAct && onAction) onAction(wake)
  }

  if (data?.meta?.view === 'icon') {
    return (
      <div className="flex-1 min-h-0 flex flex-col items-center justify-center gap-1.5 px-2 pb-3">
        <button
          type="button"
          className="btn btn-icon h-12 w-12 rounded-full"
          data-status={state}
          disabled={!wake || !canAct}
          // The whole card is the button, so it says what it does and to what.
          aria-label={t('card.wol.wake', { name: widget.title })}
          title={t('card.wol.wake', { name: widget.title })}
          onClick={press}
        >
          <Power size={20} />
        </button>
        <span className="dot" data-status={state} aria-hidden="true" />
        <span className="text-[11px] text-muted truncate max-w-full">
          {awake === true ? t('card.wol.awake') : awake === false ? t('card.wol.asleep') : t('card.wol.unknown')}
        </span>
      </div>
    )
  }

  return (
    <div className="flex-1 min-h-0 flex flex-col justify-center gap-1 px-4 pb-3">
      <div className="flex items-baseline gap-2">
        <span className="text-[22px] font-semibold leading-none">
          {awake === true ? t('card.wol.awake') : awake === false ? t('card.wol.asleep') : t('card.wol.unknown')}
        </span>
        <span className="dot" data-status={state} aria-hidden="true" />
      </div>
      {host && <div className="text-xs text-muted truncate">{host}</div>}
      {mac && <div className="num text-[11px] text-faint truncate">{String(mac)}</div>}
      {wake && canAct && onAction && (
        <button type="button" className="btn h-7 px-2 text-xs mt-2 self-start" onClick={press}>
          <Power size={13} /> {t('card.wol.wakeShort')}
        </button>
      )}
    </div>
  )
}
