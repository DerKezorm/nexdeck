import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { post } from '../../api/client'
import { Dialog, Spinner } from '../../components/ui'
import { pathText } from '../../lib/cardDocument'
import { failureOf, type Failure } from './connections'
import { FailureNote } from './FailureNote'
import { useCardEditor } from './store'

type Leaf = { path: (string | number)[]; value: string | number | boolean | null }

/** Every plain value of the examples with where it stands, in order. */
export function leavesOf(value: unknown, path: (string | number)[] = []): Leaf[] {
  if (Array.isArray(value)) return value.flatMap((item, index) => leavesOf(item, [...path, index]))
  if (value && typeof value === 'object') return Object.entries(value).flatMap(([key, item]) => leavesOf(item, [...path, key]))
  return [{ path, value: value as Leaf['value'] }]
}

/** The examples with one value changed; the rest is shared, not copied. */
export function withValue(root: unknown, path: (string | number)[], value: unknown): unknown {
  if (!path.length) return value
  const [head, ...rest] = path
  if (Array.isArray(root)) return root.map((item, index) => (index === head ? withValue(item, rest, value) : item))
  const object = (root ?? {}) as Record<string, unknown>
  return { ...object, [head]: withValue(object[head as string], rest, value) }
}

/** What was typed, as the kind of value that stood there: a number stays a number while it reads as one. */
function typed(before: Leaf['value'], text: string): Leaf['value'] {
  if (typeof before === 'number') {
    const number = Number(text.replace(',', '.'))
    return text.trim() !== '' && Number.isFinite(number) ? number : text
  }
  return text
}

/**
 * "Use this answer as demo data" (KARTEN-9 AC-10): the server asks every request of the card once and exchanges the
 * texts and numbers of the answers the way the showcase mode does; here they are shown before they become the card's
 * demo data, and every value can be changed. Nothing reaches the card before "Use as demo data".
 */
export function DemoDialog({ open, onClose, integrationId }: { open: boolean; onClose: () => void; integrationId: number | null }) {
  const { t } = useTranslation()
  const [state, setState] = useState<{ status: 'loading' } | { status: 'done'; demo: Record<string, unknown>; first: Record<string, unknown>; cut: boolean } | { status: 'failed'; failure: Failure }>({ status: 'loading' })

  useEffect(() => {
    if (!open || integrationId === null) return
    let gone = false
    setState({ status: 'loading' })
    const yaml = useCardEditor.getState().text
    post<{ demo: Record<string, unknown>; cut?: boolean }>('/cards/demo', { yaml, integration_id: integrationId })
      .then((answer) => !gone && setState({ status: 'done', demo: answer.demo, first: answer.demo, cut: Boolean(answer.cut) }))
      .catch((failure) => !gone && setState({ status: 'failed', failure: failureOf(failure) }))
    return () => {
      gone = true
    }
  }, [open, integrationId])

  const leaves = useMemo(() => (state.status === 'done' ? leavesOf(state.demo) : []), [state])
  // What each value was as it came: a number emptied on the way to another number stays a number.
  const kinds = useMemo(() => new Map(state.status === 'done' ? leavesOf(state.first).map((leaf) => [pathText(leaf.path), leaf.value] as const) : []), [state])

  const take = () => {
    if (state.status !== 'done') return
    useCardEditor.getState().set(['demo'], state.demo)
    onClose()
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      title={t('editor.demo.title')}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            {t('common.cancel')}
          </button>
          <button type="button" className="btn btn-accent" onClick={take} disabled={state.status !== 'done'}>
            {t('editor.demo.take')}
          </button>
        </>
      }
    >
      <div className="grid gap-3 min-w-0">
        <p className="text-sm text-muted break-words hyphens-auto">{t('editor.demo.body')}</p>
        {state.status === 'loading' && (
          <div className="py-6 grid place-items-center" aria-label={t('editor.demo.loading')}>
            <Spinner />
          </div>
        )}
        {state.status === 'failed' && <FailureNote failure={state.failure} />}
        {state.status === 'done' && (
          <>
            {state.cut && <p className="text-[12px] text-muted break-words hyphens-auto">{t('editor.demo.cut')}</p>}
            <div className="max-h-[50vh] overflow-y-auto grid gap-1.5 min-w-0 pr-1" role="group" aria-label={t('editor.demo.values')}>
              {leaves.map((leaf) => {
                const where = pathText(leaf.path)
                return (
                  <label key={where} className="grid sm:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-1 sm:gap-2 items-center min-w-0">
                    <span className="font-mono text-[12px] text-muted break-all">{where}</span>
                    {typeof leaf.value === 'boolean' ? (
                      <select
                        className="input !h-8 !py-0"
                        value={String(leaf.value)}
                        aria-label={where}
                        onChange={(event) => setState({ ...state, demo: withValue(state.demo, leaf.path, event.target.value === 'true') as Record<string, unknown> })}
                      >
                        <option value="true">true</option>
                        <option value="false">false</option>
                      </select>
                    ) : (
                      <input
                        className="input !h-8"
                        value={leaf.value === null ? '' : String(leaf.value)}
                        placeholder={leaf.value === null ? 'null' : undefined}
                        aria-label={where}
                        onChange={(event) => setState({ ...state, demo: withValue(state.demo, leaf.path, typed(kinds.get(where) ?? leaf.value, event.target.value)) as Record<string, unknown> })}
                      />
                    )}
                  </label>
                )
              })}
            </div>
          </>
        )}
      </div>
    </Dialog>
  )
}
