/**
 * A field and a button: the one card where the value comes from whoever is
 * standing in front of the board rather than from a list the service handed
 * over.
 *
 * The adapter declares the blank as part of the action (`action.ask`), and the
 * server checks the typed value against that declaration before any adapter
 * sees it. This component only fills the blank in and hands the action back
 * the same way every other card does.
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { tLabel } from '../i18n/texts'
import type { Action } from '../lib/types'
import type { RenderProps } from './renderers'
import { LucideByName } from './ServiceIcon'

export function AskCard({ data, canAct, onAction, editing }: RenderProps) {
  const { t } = useTranslation()
  const [text, setText] = useState('')

  const action = (data?.actions as Action[] | undefined)?.find((one) => one.ask)
  const ask = action?.ask
  const items = data?.items ?? []
  // In edit mode the card is being dragged, not used.
  const usable = Boolean(action && ask && canAct && onAction && !editing)

  function send() {
    const value = text.trim()
    if (!usable || !value) return
    onAction!({ ...action!, params: { ...(action!.params ?? {}), [ask!.name]: value } })
    setText('')
  }

  if (!action || !ask) {
    // The card is fine; it has nothing to hand a word to yet.
    return <Hint>{data?.error ? t('card.nothing') : t('card.ask.noField')}</Hint>
  }

  const label = tLabel(ask.label)

  return (
    <div className="flex-1 min-h-0 flex flex-col gap-2 px-3 pb-3">
      <form
        className="flex-none flex items-center gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          send()
        }}
      >
        <input
          type="text"
          className="input flex-1 min-w-0"
          value={text}
          placeholder={ask.placeholder || label}
          aria-label={label}
          maxLength={ask.max_length || undefined}
          disabled={!canAct || editing}
          onChange={(event) => setText(event.target.value)}
        />
        <button
          type="submit"
          className="btn h-8 px-3 text-xs shrink-0"
          disabled={!usable || !text.trim()}
          title={canAct ? undefined : t('card.ask.notAllowed')}
        >
          {action.icon ? <LucideByName name={action.icon} size={13} /> : null}
          <span>{tLabel(action.label)}</span>
        </button>
      </form>
      {!canAct && <div className="text-[11px] text-faint">{t('card.ask.notAllowed')}</div>}
      {items.length > 0 && (
        // What the button has already set going, so pressing it shows something.
        <ul className="flex-1 min-h-0 scroll -mx-1 px-1">
          {items.map((item, index) => (
            <li key={String(item.id ?? index)} className="flex items-center gap-2 py-1">
              <span className="dot" data-status={item.status === 'bad' ? 'bad' : 'warn'} />
              <div className="min-w-0 flex-1">
                <div className="text-[12px] truncate">{String(item.title ?? '')}</div>
                {item.subtitle ? <div className="text-[11px] text-muted truncate">{tLabel(String(item.subtitle))}</div> : null}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Hint({ children }: { children: React.ReactNode }) {
  return <div className="flex-1 flex items-center justify-center text-xs text-faint px-3 pb-3 text-center">{children}</div>
}
