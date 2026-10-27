/**
 * The question an action asks before it runs: "sure?", and, when the card left
 * blanks, what to fill them with.
 *
 * One component for the board and the wall display. They used to carry the
 * same confirmation twice, and the day a card first needed a pick list only
 * one of the two would have learned it: a press on the wall would have gone
 * out with the blanks empty and come back refused.
 *
 * Under the question stands what the button would hit, where nexdeck knows
 * it (roadmap M3): streams that end, downloads that stop, lights a scene
 * switches. Asked when the question opens; without an answer it is left out.
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { post } from '../api/client'
import { tLabel } from '../i18n/texts'
import { factText, type Fact } from '../lib/assistant'
import type { Action } from '../lib/types'
import { numberProblem, unanswered } from '../lib/unanswered'
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
  const [facts, setFacts] = useState<Fact[]>([])
  // One string, so the question is asked again only when the button changes.
  const asked = pending ? JSON.stringify([pending.widgetId, pending.action.id, pending.action.params ?? {}]) : ''
  useEffect(() => {
    setFacts([])
    if (!asked) return
    const [widgetId, actionId, params] = JSON.parse(asked) as [number, string, Record<string, unknown>]
    let dropped = false
    void post<{ impact: Fact[] }>(`/widgets/${widgetId}/actions/${actionId}/impact`, { params })
      .then((answer) => {
        if (!dropped) setFacts(answer.impact)
      })
      .catch(() => undefined)
    return () => {
      dropped = true
    }
  }, [asked])
  // ⚠️ A number outside its range is as unfinished as an empty field: it never
  // goes out, and the field says why.
  const incomplete =
    pending !== null &&
    blanks.some((blank) => {
      const value = String(pending.values[blank.name] ?? '')
      return !value.trim() || numberProblem(blank, value) !== null
    })

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
        // A number goes out as a number, not as the text that was typed.
        const typed = Object.fromEntries(Object.entries(pending.values).map(([name, text]) => [name, blanks.find((blank) => blank.name === name)?.kind === 'number' ? Number(text) : text]))
        onRun(pending.widgetId, { ...pending.action, params: { ...(pending.action.params ?? {}), ...typed } })
      }}
    >
      {facts.length > 0 && (
        <ul className="mt-2 text-[12.5px] text-muted" data-testid="action-impact">
          {facts.map((fact, index) => (
            <li key={index}>{factText(t, fact)}</li>
          ))}
        </ul>
      )}
      {pending && blanks.length > 0 && (
        <div className="flex flex-col gap-3 mt-3">
          {blanks.map((blank) => {
            const value = pending.values[blank.name] ?? ''
            const set = (next: string) => onChange({ ...pending, values: { ...pending.values, [blank.name]: next } })
            const wrong = numberProblem(blank, value)
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
                ) : blank.kind === 'number' ? (
                  <>
                    <input
                      className="input"
                      type="number"
                      inputMode="decimal"
                      value={value}
                      min={blank.min}
                      max={blank.max}
                      step={blank.step ?? 'any'}
                      placeholder={blank.placeholder || undefined}
                      aria-invalid={wrong ? true : undefined}
                      onChange={(event) => set(event.target.value)}
                    />
                    {wrong && (
                      <span className="text-bad text-xs" role="alert">
                        {t(`board.number.${wrong}`, { min: blank.min, max: blank.max })}
                      </span>
                    )}
                  </>
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
