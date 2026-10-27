import { Info, Plus, Trash2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Confirm } from '../../../components/ui'
import { deleteAt, pathText, readAt, setAt, type CardPath } from '../../../lib/cardDocument'
import type { CardForm } from '../../../lib/customCards'
import { slotName } from '../DataTree'
import { missingOf, treesOf } from '../hints'
import { changeForm, FORMS, lostByForm, MAX_STATS, MIN_STATS, slotsOf } from '../slots'
import { useCardEditor } from '../store'
import { BuilderEditor } from './BuilderEditor'
import { RowsFields, useHints, ValueFields } from './fields'
import { StepFrame } from './StepFrame'

const FORM_MARK: Record<CardForm, string> = { value: '12', stats: '3 · 7', list: '≡', posters: '▭▭', builder: '▤' }

/**
 * Step 2, Look (KARTEN-9 AC-4 to AC-7): the form of the card, and exactly the fields that form has: one value, two to
 * six numbers, or the rows of a list or a wall of pictures with what each row shows. A change of form that would take
 * something away asks first. A placed field the probe's answer lacks is named.
 */
export function LookStep() {
  const { t } = useTranslation()
  const card = useCardEditor((state) => state.card ?? state.lastValid?.card ?? null)
  const editable = useCardEditor((state) => state.card !== null)
  const change = useCardEditor((state) => state.change)
  const probes = useCardEditor((state) => state.probes)
  const hints = useHints()
  const [asking, setAsking] = useState<{ to: CardForm; lost: CardPath[] } | null>(null)
  const missing = useMemo(() => missingOf(card, treesOf(probes), hints), [card, probes, hints])

  if (!card) return <StepFrame step="look" />
  const form = readAt(card, ['form']) as CardForm | undefined
  const slots = slotsOf(card)
  const stats = readAt(card, ['stats'])
  const statCount = Array.isArray(stats) ? stats.length : 0

  // Rows for a list or pictures: the ones the card has, else the first list a probe showed.
  const rowsFor = (to: CardForm) => (to === 'list' || to === 'posters') && typeof readAt(card, ['rows', 'select']) !== 'string' ? hints.lists[0] : undefined
  const choose = (to: CardForm) => {
    const lost = lostByForm(card, to)
    if (lost.length) setAsking({ to, lost })
    else change((doc) => changeForm(doc, to, rowsFor(to)))
  }

  return (
    <StepFrame step="look">
      <div className="grid gap-2 min-w-0">
        <h3 className="text-sm font-semibold break-words hyphens-auto" id="card-look-form">
          {t('editor.look.form')}
        </h3>
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-2" role="group" aria-labelledby="card-look-form">
          {FORMS.map((one) => (
            <button
              key={one}
              type="button"
              aria-pressed={form === one}
              disabled={!editable}
              onClick={() => choose(one)}
              className={`min-h-14 rounded-xl border px-2 py-1.5 grid place-items-center gap-0.5 text-center ${form === one ? 'border-accent/60 bg-accent-soft text-ink' : 'border-line text-muted hover:bg-surface-hover'}`}
            >
              <span aria-hidden="true" className="text-[15px]">
                {FORM_MARK[one]}
              </span>
              <span className="text-[12px] break-words hyphens-auto">{t(`editor.look.forms.${one}`)}</span>
            </button>
          ))}
        </div>
      </div>

      {missing.map((one) => (
        <div key={`${one.slot.id}:${one.path}`} className="rounded-xl border border-warn/40 px-3 py-2 flex gap-2 items-start text-sm min-w-0" role="status" data-testid="card-missing">
          <Info size={16} className="text-warn flex-none mt-0.5" aria-hidden="true" />
          <p className="min-w-0 break-words hyphens-auto">
            {one.row !== null
              ? t('editor.look.missingInRow', { row: one.row, field: one.path, place: slotName(t, one.slot) })
              : t('editor.look.missing', { field: one.path, place: slotName(t, one.slot) })}
          </p>
        </div>
      ))}

      {form === 'builder' && <BuilderEditor />}

      {form === 'value' && <ValueFields path={['value']} title={t('editor.slot.value')} required />}

      {form === 'stats' && (
        <>
          {slots
            .filter((slot) => readAt(card, slot.path) !== undefined)
            .map((slot, index) => (
              <div key={slot.id} className="grid gap-1 min-w-0">
                <ValueFields path={slot.path} title={slotName(t, slot)} required={index < MIN_STATS} />
                {statCount > MIN_STATS && (
                  <button type="button" className="btn btn-flat btn-danger justify-self-start" disabled={!editable} onClick={() => change((doc) => deleteAt(doc, slot.path))}>
                    <Trash2 size={14} />
                    {t('editor.look.removeStat', { number: index + 1 })}
                  </button>
                )}
              </div>
            ))}
          {statCount < MIN_STATS && <p className="text-[12px] text-warn break-words hyphens-auto">{t('editor.look.statsAtLeast', { count: MIN_STATS })}</p>}
          {statCount < MAX_STATS && (
            <button
              type="button"
              className="btn btn-flat justify-self-start"
              disabled={!editable}
              onClick={() => change((doc) => setAt(doc, ['stats', statCount], { path: hints.fields[0] ?? '@' }))}
            >
              <Plus size={14} />
              {t('editor.look.addStat')}
            </button>
          )}
        </>
      )}

      {(form === 'list' || form === 'posters') && (
        <>
          <div className="grid gap-2 min-w-0">
            <h3 className="text-sm font-semibold break-words hyphens-auto">{t('editor.look.eachRow')}</h3>
            {slots.map((slot) => (
              <ValueFields key={slot.id} path={slot.path} row title={slotName(t, slot)} required={slot.required} />
            ))}
          </div>
          <div className="grid gap-2 min-w-0">
            <h3 className="text-sm font-semibold break-words hyphens-auto">{t('editor.look.whichRows')}</h3>
            <RowsFields path={['rows']} lists={hints.lists} />
          </div>
        </>
      )}

      <Confirm
        open={asking !== null}
        title={t('editor.form.loseTitle')}
        body={asking ? t('editor.form.loseBody', { parts: asking.lost.map((part) => pathText(part)).join(', ') }) : ''}
        danger
        confirmLabel={t('editor.form.loseConfirm')}
        onCancel={() => setAsking(null)}
        onConfirm={() => {
          if (asking) change((doc) => changeForm(doc, asking.to, rowsFor(asking.to)))
          setAsking(null)
        }}
      />
    </StepFrame>
  )
}
