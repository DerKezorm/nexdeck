/**
 * The question an action asks before it runs: "sure?", and, when the card left
 * blanks, what to fill them with.
 *
 * One component for the board and the wall display. They used to carry the
 * same confirmation twice, and the day a card first needed a pick list only
 * one of the two would have learned it: a press on the wall would have gone
 * out with the blanks empty and come back refused.
 */
import { useTranslation } from 'react-i18next'

import { tLabel } from '../i18n/texts'
import type { Action } from '../lib/types'
import { unanswered } from '../lib/unanswered'
import { Confirm } from './ui'

export interface PendingAction {
  widgetId: number
  action: Action
  /** What has been picked or typed for the blanks, by parameter name. */
  values: Record<string, string>
}

export function ActionSheet({
  pending,
  onChange,
  onCancel,
  onRun,
}: {
  pending: PendingAction | null
  onChange: (next: PendingAction) => void
  onCancel: () => void
  onRun: (widgetId: number, action: Action) => void
}) {
  const { t } = useTranslation()
  const blanks = pending ? unanswered(pending.action) : []
  const incomplete = pending !== null && blanks.some((blank) => !String(pending.values[blank.name] ?? '').trim())

  return (
    <Confirm
      open={pending !== null}
      title={pending ? `${tLabel(pending.action.label)}?` : ''}
      body={blanks.length ? t('board.chooseBeforeAction') : t('board.confirmAction')}
      danger={pending?.action.danger}
      confirmDisabled={incomplete}
      onCancel={onCancel}
      onConfirm={() => {
        if (!pending || incomplete) return
        onRun(pending.widgetId, { ...pending.action, params: { ...(pending.action.params ?? {}), ...pending.values } })
      }}
    >
      {pending && blanks.length > 0 && (
        <div className="flex flex-col gap-3 mt-3">
          {blanks.map((blank) => {
            const value = pending.values[blank.name] ?? ''
            const set = (next: string) => onChange({ ...pending, values: { ...pending.values, [blank.name]: next } })
            return (
              <label key={blank.name} className="flex flex-col gap-1 text-sm">
                <span className="text-muted">{tLabel(blank.label)}</span>
                {blank.kind === 'choice' ? (
                  <select className="input" value={value} onChange={(event) => set(event.target.value)}>
                    {/* ⚠️ No silent first entry. "Nobody chose" must not turn
                        into a folder a title then lands in. */}
                    <option value="" disabled>
                      {t('board.pickOne')}
                    </option>
                    {(blank.options ?? []).map((one) => (
                      <option key={one.value} value={one.value}>
                        {one.label}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    className="input"
                    type="text"
                    value={value}
                    placeholder={blank.placeholder || undefined}
                    maxLength={blank.max_length || undefined}
                    onChange={(event) => set(event.target.value)}
                  />
                )}
              </label>
            )
          })}
        </div>
      )}
    </Confirm>
  )
}
