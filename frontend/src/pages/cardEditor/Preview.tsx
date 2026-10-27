import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState, type DragEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, get, post } from '../../api/client'
import { OverflowContext } from '../../components/BuilderCard'
import { WidgetCard } from '../../components/WidgetCard'
import { useBoardCardStyle, useLook, type CardStyle } from '../../lib/appearance'
import { readAt } from '../../lib/cardDocument'
import { pickText, type CardText } from '../../lib/cardText'
import { problemText, type CardForm, type CardProblem, type CardSource } from '../../lib/customCards'
import { useGround } from '../../lib/ground'
import type { WidgetData, WidgetView } from '../../lib/types'
import { useConnections } from './connections'
import { slotName } from './DataTree'
import { FIELD_TYPE, placeDropped, readDragged } from './placing'
import { partOfProblem } from './problems'
import { useFit } from './fit'
import { pathsOfValue, slotsOf } from './slots'
import { useCardEditor } from './store'

/** How long the preview waits after the last change before it asks again. */
export const PREVIEW_MS = 400

const STYLES: CardStyle[] = ['glass', 'flat', 'outline', 'neon', 'liquid']

/** The size a card of each form is made at and the smallest it may be, as the server's card kinds say. */
const FORM_SIZES: Record<CardForm, { size: [number, number]; min: [number, number] }> = {
  value: { size: [2, 2], min: [1, 1] },
  stats: { size: [3, 2], min: [2, 1] },
  list: { size: [3, 3], min: [2, 1] },
  posters: { size: [4, 3], min: [2, 2] },
  builder: { size: [3, 3], min: [2, 2] },
}
/** A column and a row of the board on a wide screen, and the room between two, in pixels. */
const COLUMN = 92
const ROW = 68
const GAP = 12
/** The width a phone gives a board, and half of it for a small card. */
const PHONE = 358

/** The sizes a card of this form is offered in: its smallest, the one it is made at, and a larger one. */
export function sizesOf(card: { form?: unknown; size?: unknown; min_size?: unknown }): [number, number][] {
  const form = (FORM_SIZES[card.form as CardForm] ? card.form : 'value') as CardForm
  const own = (value: unknown): [number, number] | null => {
    const { w, h } = (value ?? {}) as { w?: unknown; h?: unknown }
    return typeof w === 'number' && typeof h === 'number' ? [w, h] : null
  }
  const floor = FORM_SIZES[form].min
  const min = own(card.min_size) ?? floor
  const smallest: [number, number] = [Math.max(floor[0], min[0]), Math.max(floor[1], min[1])]
  const wanted = own(card.size) ?? FORM_SIZES[form].size
  const made: [number, number] = [Math.max(smallest[0], wanted[0]), Math.max(smallest[1], wanted[1])]
  const large: [number, number] = [Math.min(12, made[0] + 2), made[1] + 1]
  const all = [smallest, made, large]
  return all.filter((one, index) => all.findIndex((other) => other[0] === one[0] && other[1] === one[1]) === index)
}

/** The pixels of a card of `w` by `h` on a wide board, or on a phone. */
export function pixelsOf([w, h]: [number, number], phone: boolean): { width: number; height: number } {
  const height = h * ROW + (h - 1) * GAP
  if (phone) return { width: w <= 2 ? (PHONE - GAP) / 2 : PHONE, height }
  return { width: w * COLUMN + (w - 1) * GAP, height }
}

function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const timer = window.setTimeout(() => setSettled(value), ms)
    return () => window.clearTimeout(timer)
  }, [value, ms])
  return settled
}

/**
 * The card as the server draws it, for the preview and for the guided way's "Result": the same question, asked once.
 * Live data of the chosen connection, or the card's example data; nothing while `enabled` is false.
 */
export function usePreviewQuery(enabled = true) {
  const card = useCardEditor((state) => state.card ?? state.lastValid?.card ?? null)
  const text = card?.text ?? ''
  const { chosen } = useConnections()
  const wanted = useCardEditor((state) => state.previewData)
  const mode = wanted ?? (chosen ? 'live' : 'demo')
  const settled = useDebounced(text, PREVIEW_MS)
  const integrationId = mode === 'live' ? (chosen?.id ?? null) : null
  const preview = useQuery({
    queryKey: ['card-preview', settled, integrationId, mode],
    queryFn: () => post<WidgetData>('/cards/preview', integrationId !== null ? { yaml: settled, integration_id: integrationId } : { yaml: settled, demo: true }),
    enabled: enabled && Boolean(settled),
    retry: false,
    placeholderData: keepPreviousData,
    refetchOnWindowFocus: false,
  })
  return { preview, mode, integrationId, chosen }
}

type Shown = { kind: 'data'; data: WidgetData } | { kind: 'invalid'; problems: CardProblem[] } | { kind: 'none' }

/** A failed preview as the card would show it: red, with the reason (KARTEN-9 AC-9, EC-2). */
function failedData(failure: unknown): Shown {
  if (failure instanceof ApiError && failure.code === 'card_invalid') {
    const problems = failure.detail?.problems
    return { kind: 'invalid', problems: Array.isArray(problems) ? (problems as CardProblem[]) : [] }
  }
  const code = failure instanceof ApiError ? failure.code : 'network'
  const message = failure instanceof Error ? failure.message : String(failure)
  return { kind: 'data', data: { error: message, meta: { code, hint: failure instanceof ApiError ? failure.hint : undefined, custom: true } } as unknown as WidgetData }
}

function Switch<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: { value: T; label: string; title?: string }[]; onChange: (value: T) => void }) {
  return (
    <div className="inline-flex flex-wrap rounded-lg bg-surface p-0.5 gap-0.5" role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          title={option.title}
          aria-pressed={value === option.value}
          className={`px-2.5 h-7 rounded-md text-[12px] break-words hyphens-auto ${value === option.value ? 'bg-accent-soft text-ink font-medium' : 'text-muted'}`}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}

/**
 * Where the card is shown while it is built (KARTEN-9 AC-4, AC-9): beside the step on a wide screen, below it on a
 * phone (EC-5). It shows the last valid version, and says so while the text is not valid.
 *
 * The card is drawn from `POST /cards/preview` with the frame and the renderers of the board, so it looks as it will
 * there. Switches: live data of the chosen connection or the card's demo data, light or dark, the card style, the
 * sizes of its form, and a phone. Below it, the places of the card: a field of the answer dragged onto one goes there.
 */
export function Preview({ guided = false }: { guided?: boolean }) {
  const { t, i18n } = useTranslation()
  const stale = useCardEditor((state) => state.card === null)
  const card = useCardEditor((state) => state.card ?? state.lastValid?.card ?? null)
  const { kinds } = useConnections()
  // The guided way shows a card once it has a display: before that it would be the start's whole answer.
  const waiting = useCardEditor((state) => guided && (state.shapedPath === null || state.pendingShape !== null))
  const ground = useGround((state) => state.mode)
  const installed = useLook((state) => state.cards)
  const [theme, setTheme] = useState<'dark' | 'light' | null>(null)
  const [style, setStyle] = useState<CardStyle | null>(null)
  const [sizeIndex, setSizeIndex] = useState(1)
  const [phone, setPhone] = useState(false)
  const [over, setOver] = useState<string | null>(null)
  // A press on a button of the card: it does nothing here, and the card says so until it is changed.
  const [pressed, setPressed] = useState(false)
  const text = useCardEditor((state) => state.text)
  useEffect(() => setPressed(false), [text])
  const sources = useQuery({ queryKey: ['cards-sources'], queryFn: () => get<CardSource[]>('/cards/sources'), staleTime: 60_000 })

  const { preview, mode, integrationId, chosen } = usePreviewQuery(!waiting)
  // A card of blocks tells whether it fits; the builder shows the warning (KARTEN-7 AC-7).
  const report = useFit((state) => state.report)
  const setWanted = (value: 'live' | 'demo') => useCardEditor.setState({ previewData: value })
  const shownTheme = theme ?? ground
  const shownStyle = style ?? installed
  // The preview is a board of its own while it stands: its card style, the installation's after.
  useBoardCardStyle(style)

  const plain = useMemo(() => (card ? (card.doc.toJS() as Record<string, unknown>) : {}), [card])
  const form = ((card ? readAt(card, ['form']) : undefined) ?? 'value') as CardForm
  useEffect(() => () => report(false), [report, form])
  const sizes = sizesOf(plain)
  const size = sizes[Math.min(sizeIndex, sizes.length - 1)]
  const pixels = pixelsOf(size, phone)
  const slots = useMemo(() => slotsOf(card), [card])

  const shown: Shown = preview.isError ? failedData(preview.error) : preview.data ? { kind: 'data', data: { ...preview.data, meta: { ...preview.data.meta, custom: true } } } : { kind: 'none' }
  const widget: WidgetView = {
    id: 0,
    kind: `custom.${form}`,
    title: pickText(plain.name as CardText, i18n.language),
    icon: sources.data?.find((one) => one.kind === kinds[0])?.icon || 'lucide:layout-dashboard',
    link: '',
    renderer: FORM_SIZES[form] ? form : 'value',
    options: {},
    integration_id: integrationId,
    refresh_seconds: null,
    default_size: size,
  }

  const onDrop = (event: DragEvent<HTMLElement>, slotIndex: number) => {
    event.preventDefault()
    setOver(null)
    const field = readDragged(event.dataTransfer)
    if (field) placeDropped(field, slots[slotIndex])
  }

  return (
    <section className="glass rounded-2xl p-4 sm:p-5 min-w-0 grid gap-3" aria-labelledby="card-preview-title" data-testid="card-preview">
      <div className="flex flex-wrap items-center justify-between gap-2 min-w-0">
        <h2 id="card-preview-title" className="font-semibold text-[15px] break-words hyphens-auto">
          {stale ? t('editor.preview.lastValid') : t('editor.preview.title')}
        </h2>
        <Switch
          label={t('editor.preview.data')}
          value={mode}
          onChange={setWanted}
          options={[
            ...(chosen ? [{ value: 'live' as const, label: t('editor.preview.live'), title: chosen.name }] : []),
            { value: 'demo' as const, label: t('editor.preview.demo') },
          ]}
        />
      </div>
      <div className="flex flex-wrap gap-2 min-w-0">
        <Switch
          label={t('editor.preview.theme')}
          value={shownTheme}
          onChange={setTheme}
          options={[
            { value: 'dark', label: t('editor.preview.dark') },
            { value: 'light', label: t('editor.preview.light') },
          ]}
        />
        <Switch
          label={t('editor.preview.size')}
          value={phone ? 'phone' : String(Math.min(sizeIndex, sizes.length - 1))}
          onChange={(value) => {
            if (value === 'phone') setPhone(true)
            else {
              setPhone(false)
              setSizeIndex(Number(value))
            }
          }}
          options={[
            ...sizes.map((one, index) => ({ value: String(index), label: `${one[0]} × ${one[1]}` })),
            { value: 'phone', label: t('editor.preview.phone') },
          ]}
        />
      </div>

      {/* Live data asked for, demo mode answered: without this the switch would say one thing and the card show another. */}
      {mode === 'live' && preview.data?.meta?.demo_mode === true ? (
        <p className="text-[12px] text-muted break-words hyphens-auto" role="note" data-testid="card-preview-demo-mode">
          {t('editor.preview.demoMode')}
        </p>
      ) : null}
      <div
        className="nd-stage rounded-xl p-3 overflow-x-auto min-w-0"
        data-theme={shownTheme !== ground ? shownTheme : undefined}
        style={{ background: 'var(--nd-bg)', color: 'var(--nd-text)' }}
        data-testid="card-preview-stage"
        data-size={phone ? `phone ${size[0]}x${size[1]}` : `${size[0]}x${size[1]}`}
      >
        {waiting ? (
          <div className="min-h-[160px] grid place-items-center text-center text-[12px] text-muted px-4 break-words hyphens-auto" data-testid="card-preview-empty">
            {t('editor.guided.preview.empty')}
          </div>
        ) : shown.kind === 'invalid' ? (
          <div className="grid gap-1 text-sm" role="alert" data-testid="card-preview-invalid">
            <p className="font-medium text-bad break-words hyphens-auto">{t('editor.preview.invalid')}</p>
            {shown.problems.map((problem, index) => (
              <p key={index} className="text-[12px] text-muted break-words hyphens-auto">
                {guided ? (
                  partOfProblem(t, problem.path) ? <span>{partOfProblem(t, problem.path)}: </span> : null
                ) : problem.path ? (
                  <span className="font-mono">{problem.path}: </span>
                ) : null}
                {problemText(t, problem)}
              </p>
            ))}
          </div>
        ) : shown.kind === 'data' ? (
          <div style={{ width: pixels.width, height: pixels.height }} className="max-w-none" data-testid="card-preview-card">
            {/* Buttons are drawn, the way a board draws them, and do nothing here (KARTEN-8). */}
            <OverflowContext.Provider value={form === 'builder' ? report : null}>
              <WidgetCard widget={widget} data={shown.data} canAct onAction={() => setPressed(true)} />
            </OverflowContext.Provider>
          </div>
        ) : (
          <div style={{ width: pixels.width, height: pixels.height }} className="grid place-items-center text-[12px] text-muted">
            {t('editor.preview.waiting')}
          </div>
        )}
      </div>

      {pressed && (
        <p className="text-[12px] text-muted break-words hyphens-auto" role="status" data-testid="card-preview-buttons">
          {t('editor.preview.buttonsNothing')}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2 min-w-0">
        <span className="text-[12px] text-muted break-words hyphens-auto">{t('editor.preview.style')}</span>
        <Switch label={t('editor.preview.style')} value={shownStyle} onChange={setStyle} options={STYLES.map((one) => ({ value: one, label: t(`editor.preview.styles.${one}`) }))} />
      </div>

      {guided && <p className="text-[12px] text-faint break-words hyphens-auto">{t('editor.guided.preview.hint')}</p>}

      {!guided && !stale && slots.length > 0 && (
        <div className="grid gap-1.5 min-w-0" role="group" aria-labelledby="card-places-title">
          <h3 id="card-places-title" className="text-[12px] font-medium text-muted break-words hyphens-auto">
            {t('editor.preview.places')}
          </h3>
          <ul className="flex flex-wrap gap-1.5">
            {slots.map((slot, index) => {
              const value = card ? readAt(card, slot.path) : undefined
              const paths = pathsOfValue(value)
              return (
                <li
                  key={slot.id}
                  className={`rounded-lg border px-2 py-1 text-[12px] min-w-0 break-words hyphens-auto ${over === slot.id ? 'border-accent bg-accent-soft' : 'border-dashed border-line'}`}
                  data-testid={`card-place-${slot.id}`}
                  onDragOver={(event) => {
                    if (!event.dataTransfer.types.includes(FIELD_TYPE)) return
                    event.preventDefault()
                    event.dataTransfer.dropEffect = 'copy'
                    setOver(slot.id)
                  }}
                  onDragLeave={() => setOver(null)}
                  onDrop={(event) => onDrop(event, index)}
                >
                  <span className="text-muted">{slotName(t, slot)}</span> <span className="font-mono">{value === undefined ? t('editor.preview.free') : paths.join(', ') || t('editor.preview.worked')}</span>
                </li>
              )
            })}
          </ul>
          <p className="text-[11px] text-faint break-words hyphens-auto">{t('editor.preview.dropHelp')}</p>
        </div>
      )}
    </section>
  )
}
