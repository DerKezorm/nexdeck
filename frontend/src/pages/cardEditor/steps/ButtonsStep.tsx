import { ArrowDown, ArrowUp, Plus, Trash2 } from 'lucide-react'
import { useId, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { LucideByName } from '../../../components/ServiceIcon'
import { deleteAt, pathText, readAt, readIn, setAt, type CardPath } from '../../../lib/cardDocument'
import {
  ASK_TYPES,
  addButton,
  bodyFromRows,
  bodyRows,
  freeKey,
  isNestedBody,
  MAX_ASKS,
  MAX_BUTTONS,
  METHODS,
  moveButton,
  putPlaceholder,
  removeButton,
  buttonsOf,
  SYMBOLS,
  useButtonTarget,
  type AskType,
  type BodyRow,
} from '../buttons'
import { languagesOf, textIn, textSpots, writeText, type TextSpot } from '../texts'
import { useCardEditor, useCardField } from '../store'
import { languageName } from './TextsStep'
import { FieldProblems } from './SourceStep'
import { StepFrame } from './StepFrame'

const LABEL = 'text-[12px] font-medium text-muted break-words hyphens-auto'

/**
 * Step 4, Buttons (KARTEN-8): what the card can do with the service. One form per button: its words and symbol,
 * where it stands (on the card or on each row), what it sends and what it asks first. A field of the data goes into
 * the address or the content with "Use in button" in the tree of the Source step. Everything is written into the
 * card's own `buttons:`; whatever the form cannot show stays as written.
 */
export function ButtonsStep() {
  const { t } = useTranslation()
  const card = useCardEditor((state) => state.card ?? state.lastValid?.card ?? null)
  const editable = useCardEditor((state) => state.card !== null)
  const change = useCardEditor((state) => state.change)
  const buttons = useMemo(() => buttonsOf(card), [card])
  if (!card) return <StepFrame step="buttons" />
  const form = readAt(card, ['form'])
  const full = buttons.length >= MAX_BUTTONS
  return (
    <StepFrame step="buttons">
      {buttons.length === 0 && <p className="text-sm text-muted break-words hyphens-auto">{t('editor.buttons.none')}</p>}
      {buttons.map((_, index) => (
        <ButtonForm key={index} index={index} count={buttons.length} perRow={form === 'list' || form === 'posters'} />
      ))}
      <div className="flex flex-wrap items-center gap-2 min-w-0">
        <button type="button" className="btn" disabled={!editable || full} onClick={() => change((doc) => addButton(doc))}>
          <Plus size={15} /> {t('editor.buttons.add')}
        </button>
        {full && <span className="text-[12px] text-muted break-words hyphens-auto">{t('editor.buttons.most', { count: MAX_BUTTONS })}</span>}
      </div>
    </StepFrame>
  )
}

function ButtonForm({ index, count, perRow }: { index: number; count: number; perRow: boolean }) {
  const { t } = useTranslation()
  const ids = useId()
  const root: CardPath = ['buttons', index]
  const editable = useCardEditor((state) => state.card !== null)
  const change = useCardEditor((state) => state.change)
  const card = useCardEditor((state) => state.card ?? state.lastValid?.card ?? null)
  const [id, setId] = useCardField<string>([...root, 'id'])
  const [where, setWhere] = useCardField<string>([...root, 'where'])
  const [method, setMethod] = useCardField<string>([...root, 'method'])
  const [path, setPath] = useCardField<string>([...root, 'path'])
  const [send, setSend] = useCardField<string>([...root, 'send'])
  const [icon, setIcon] = useCardField<string>([...root, 'icon'])
  const [confirm, setConfirm] = useCardField<boolean>([...root, 'confirm'])
  const [danger, setDanger] = useCardField<boolean>([...root, 'danger'])
  const [answer, setAnswer] = useCardField<string>([...root, 'answer'])
  const setTarget = useButtonTarget((state) => state.set)
  const asks = useMemo(() => {
    const list = card ? readAt(card, [...root, 'asks']) : undefined
    return Array.isArray(list) ? list.map((one) => (one && typeof one === 'object' ? (one as Record<string, unknown>) : {})) : []
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [card, index])
  const spots = useMemo(() => (card ? textSpots(card) : []), [card])
  const labelSpot = spots.find((spot) => spot.id === `buttons.${index}.label`)
  const named = card && labelSpot ? textIn(card, labelSpot, 'en') : ''

  return (
    <fieldset className="grid gap-3 min-w-0 rounded-xl border border-line p-3" data-testid={`card-button-${index}`}>
      <legend className="px-1 text-sm font-medium break-words hyphens-auto">{t('editor.buttons.button', { number: index + 1, name: named || id || '' })}</legend>

      {labelSpot && card && <LabelFields spot={labelSpot} />}
      <FieldProblems path={[...root, 'label']} />

      <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1fr)] min-w-0">
        <label className="grid gap-1 min-w-0">
          <span className={LABEL}>{t('editor.buttons.symbol')}</span>
          <span className="flex items-center gap-2 min-w-0">
            <input className="input font-mono min-w-0 flex-1" list={`${ids}-symbols`} value={icon ?? ''} disabled={!editable} onChange={(event) => setIcon(event.target.value || undefined)} placeholder={t('editor.buttons.symbolNone')} />
            {icon ? <LucideByName name={icon} size={16} /> : null}
          </span>
          <datalist id={`${ids}-symbols`}>
            {SYMBOLS.map((name) => (
              <option key={name} value={name} />
            ))}
          </datalist>
        </label>
        <label className="grid gap-1 min-w-0">
          <span className={LABEL}>{t('editor.buttons.where')}</span>
          <select className="input" value={where ?? 'card'} disabled={!editable} onChange={(event) => setWhere(event.target.value)}>
            <option value="card">{t('editor.buttons.whereCard')}</option>
            <option value="row" disabled={!perRow && where !== 'row'}>
              {t('editor.buttons.whereRow')}
            </option>
          </select>
        </label>
        <label className="grid gap-1 min-w-0">
          <span className={LABEL}>{t('editor.buttons.id')}</span>
          <input className="input font-mono min-w-0" value={id ?? ''} disabled={!editable} onChange={(event) => setId(event.target.value)} />
        </label>
      </div>
      {!perRow && <p className="text-[12px] text-muted break-words hyphens-auto">{t('editor.buttons.rowNeedsList')}</p>}
      <FieldProblems path={[...root, 'where']} />
      <FieldProblems path={[...root, 'id']} />

      <div className="grid gap-2 sm:grid-cols-[minmax(0,9rem)_minmax(0,1fr)_minmax(0,9rem)] min-w-0">
        <label className="grid gap-1 min-w-0">
          <span className={LABEL}>{t('editor.buttons.method')}</span>
          <select className="input" value={method ?? 'POST'} disabled={!editable} onChange={(event) => setMethod(event.target.value)}>
            {METHODS.map((one) => (
              <option key={one} value={one}>
                {one}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 min-w-0">
          <span className={LABEL}>{t('editor.buttons.path')}</span>
          <input
            className="input font-mono min-w-0"
            value={path ?? ''}
            disabled={!editable}
            placeholder="/api/…"
            onFocus={() => setTarget({ index, part: 'path' })}
            onChange={(event) => setPath(event.target.value)}
          />
        </label>
        <label className="grid gap-1 min-w-0">
          <span className={LABEL}>{t('editor.buttons.send')}</span>
          <select className="input" value={send ?? 'json'} disabled={!editable} onChange={(event) => setSend(event.target.value === 'json' ? undefined : event.target.value)}>
            <option value="json">{t('editor.buttons.sendJson')}</option>
            <option value="form">{t('editor.buttons.sendForm')}</option>
          </select>
        </label>
      </div>
      <p className="text-[12px] text-muted break-words hyphens-auto">{t('editor.buttons.pathHelp')}</p>
      <FieldProblems path={[...root, 'path']} />

      <BodyRows index={index} send={send ?? 'json'} />
      <FieldProblems path={[...root, 'body']} />

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 min-w-0">
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={Boolean(confirm) || Boolean(danger)} disabled={!editable || Boolean(danger)} onChange={(event) => setConfirm(event.target.checked ? true : undefined)} />
          {t('editor.buttons.confirm')}
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={Boolean(danger)} disabled={!editable} onChange={(event) => setDanger(event.target.checked ? true : undefined)} />
          {t('editor.buttons.danger')}
        </label>
      </div>
      {danger ? <p className="text-[12px] text-muted break-words hyphens-auto">{t('editor.buttons.dangerHelp')}</p> : null}

      <Asks index={index} asks={asks} spots={spots} />

      <label className="grid gap-1 min-w-0">
        <span className={LABEL}>{t('editor.buttons.answer')}</span>
        <input className="input font-mono min-w-0" value={answer ?? ''} disabled={!editable} onChange={(event) => setAnswer(event.target.value || undefined)} placeholder={t('editor.buttons.answerNone')} />
        <span className="text-[12px] text-muted break-words hyphens-auto">{t('editor.buttons.answerHelp')}</span>
      </label>
      <FieldProblems path={[...root, 'answer']} />

      <div className="flex flex-wrap items-center justify-end gap-1 min-w-0">
        <button type="button" className="btn btn-icon btn-flat" aria-label={t('editor.buttons.up')} title={t('editor.buttons.up')} disabled={!editable || index === 0} onClick={() => change((doc) => moveButton(doc, index, -1))}>
          <ArrowUp size={15} />
        </button>
        <button type="button" className="btn btn-icon btn-flat" aria-label={t('editor.buttons.down')} title={t('editor.buttons.down')} disabled={!editable || index === count - 1} onClick={() => change((doc) => moveButton(doc, index, 1))}>
          <ArrowDown size={15} />
        </button>
        <button type="button" className="btn btn-icon btn-flat btn-danger" aria-label={t('editor.buttons.remove', { number: index + 1 })} title={t('editor.buttons.remove', { number: index + 1 })} disabled={!editable} onClick={() => change((doc) => removeButton(doc, index))}>
          <Trash2 size={15} />
        </button>
      </div>
    </fieldset>
  )
}

/** The words of one text of a button in each language the card is written in; more languages come in the Texts step. */
function LabelFields({ spot }: { spot: TextSpot }) {
  const { t, i18n } = useTranslation()
  const card = useCardEditor((state) => state.card ?? state.lastValid?.card ?? null)
  const editable = useCardEditor((state) => state.card !== null)
  const change = useCardEditor((state) => state.change)
  const spots = useMemo(() => (card ? textSpots(card) : []), [card])
  const languages = useMemo(() => (card ? languagesOf(card, spots) : ['en']), [card, spots])
  if (!card) return null
  const ui = i18n.language
  return (
    <div className="grid gap-2 sm:grid-cols-[repeat(auto-fit,minmax(180px,1fr))] min-w-0">
      {languages.map((code) => {
        const name = code === 'en' ? t('editor.texts.englishRequired') : languageName(code, ui)
        const value = textIn(card, spot, code)
        return (
          <label key={code} className="grid gap-1 min-w-0">
            <span className={LABEL} lang={ui}>
              {t('editor.buttons.label')}, {name}
            </span>
            <input
              className="input"
              lang={code}
              value={value}
              disabled={!editable}
              aria-invalid={code === 'en' && !value ? true : undefined}
              onChange={(event) => change((doc) => writeText(doc, spot, code, event.target.value), `text:${spot.id}:${code}`)}
            />
          </label>
        )
      })}
    </div>
  )
}

/** What the button sends, as lines of a name and a value; content with names inside names stays as it is. */
function BodyRows({ index, send }: { index: number; send: string }) {
  const { t } = useTranslation()
  const card = useCardEditor((state) => state.card ?? state.lastValid?.card ?? null)
  const editable = useCardEditor((state) => state.card !== null)
  const change = useCardEditor((state) => state.change)
  const setTarget = useButtonTarget((state) => state.set)
  const raw = card ? readAt(card, ['buttons', index, 'body']) : undefined
  const path: CardPath = ['buttons', index, 'body']
  if (!card) return null
  if (isNestedBody(raw)) {
    return (
      <div className="grid gap-2" role="group" aria-label={t('editor.buttons.body')} data-testid={`card-button-${index}-nested`}>
        <div className={LABEL}>{t('editor.buttons.body')}</div>
        <p className="text-[13px] text-muted break-words hyphens-auto">{t('editor.buttons.bodyNested')}</p>
        <div>
          <button type="button" className="btn" onClick={() => useCardEditor.getState().setView('yaml')}>
            {t('editor.buttons.bodyNestedOpen')}
          </button>
        </div>
      </div>
    )
  }
  const rows = bodyRows(raw)
  const write = (next: readonly BodyRow[]) =>
    change((doc) => {
      if (next.length === 0) deleteAt(doc, path)
      else setAt(doc, path, bodyFromRows(next, send))
    }, `field:${pathText(path)}`)
  return (
    <div className="grid gap-2" role="group" aria-label={t('editor.buttons.body')}>
      <div className={LABEL}>{t('editor.buttons.body')}</div>
      {rows.map(([key, value], at) => (
        <div key={at} className="grid gap-2 sm:grid-cols-[minmax(0,10rem)_minmax(0,1fr)_auto] items-start">
          <KeyInput
            value={key}
            label={t('editor.buttons.bodyKey')}
            disabled={!editable}
            taken={rows.map((row) => row[0])}
            onCommit={(next) => write(rows.map((row, i) => (i === at ? ([next, row[1]] as const) : row)))}
          />
          <input
            className="input font-mono min-w-0"
            aria-label={t('editor.buttons.bodyValue', { key })}
            value={value}
            disabled={!editable}
            onFocus={() => setTarget({ index, part: 'body', key })}
            onChange={(event) => write(rows.map((row, i) => (i === at ? ([row[0], event.target.value] as const) : row)))}
          />
          <button type="button" className="btn btn-icon btn-flat btn-danger" aria-label={t('editor.buttons.bodyRemove', { key })} disabled={!editable} onClick={() => write(rows.filter((_, i) => i !== at))}>
            <Trash2 size={15} />
          </button>
        </div>
      ))}
      <div>
        <button type="button" className="btn" disabled={!editable} onClick={() => write([...rows, [freeKey(rows), ''] as const])}>
          <Plus size={15} /> {t('editor.buttons.bodyAdd')}
        </button>
      </div>
      <Insertable index={index} />
    </div>
  )
}

/**
 * A name typed into a line of the content. It is written when the field is left (or Enter is pressed): written
 * letter by letter, a half-typed name could equal another line's and swallow it.
 */
function KeyInput({ value, label, disabled, taken, onCommit }: { value: string; label: string; disabled: boolean; taken: string[]; onCommit: (next: string) => void }) {
  const [draft, setDraft] = useState<string | null>(null)
  const shown = draft ?? value
  const commit = () => {
    const next = (draft ?? value).trim()
    setDraft(null)
    if (next && next !== value && !taken.includes(next)) onCommit(next)
  }
  return (
    <input
      className="input font-mono text-[13px] min-w-0"
      aria-label={label}
      value={shown}
      disabled={disabled}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === 'Enter') commit()
      }}
    />
  )
}

/** The blanks of the button as words to put into the path or content: `{ask.kib}`. */
function Insertable({ index }: { index: number }) {
  const { t } = useTranslation()
  const card = useCardEditor((state) => state.card ?? state.lastValid?.card ?? null)
  const target = useButtonTarget((state) => state.target)
  const change = useCardEditor((state) => state.change)
  const asks = card ? readAt(card, ['buttons', index, 'asks']) : undefined
  const names = Array.isArray(asks) ? asks.map((one) => (one && typeof one === 'object' ? String((one as Record<string, unknown>).name ?? '') : '')).filter(Boolean) : []
  if (!names.length) return null
  return (
    <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label={t('editor.buttons.insertAsk')}>
      <span className="text-[12px] text-muted">{t('editor.buttons.insertAsk')}</span>
      {names.map((name) => (
        <button
          key={name}
          type="button"
          className="chip !py-0 font-mono hover:bg-surface-hover disabled:opacity-50"
          disabled={!target || target.index !== index}
          title={target && target.index === index ? undefined : t('editor.buttons.insertWhere')}
          onClick={() => target && change((doc) => void putPlaceholder(doc, target, `{ask.${name}}`))}
        >
          {`{ask.${name}}`}
        </button>
      ))}
    </div>
  )
}

/** What the person who presses is asked first: a number inside a range, a short text or one of a list. */
function Asks({ index, asks, spots }: { index: number; asks: Record<string, unknown>[]; spots: TextSpot[] }) {
  const { t } = useTranslation()
  const editable = useCardEditor((state) => state.card !== null)
  const change = useCardEditor((state) => state.change)
  const add = () =>
    change((doc) => {
      const have = readIn(doc, ['buttons', index, 'asks'])
      const list = Array.isArray(have) ? have : []
      const taken = list.map((one) => String((one as Record<string, unknown> | null)?.name ?? ''))
      let name = 'value'
      for (let n = 2; taken.includes(name); n += 1) name = `value_${n}`
      setAt(doc, ['buttons', index, 'asks', list.length], { name, label: 'Value', type: 'number', min: 0, max: 100, step: 1 })
    })
  return (
    <div className="grid gap-2 min-w-0" role="group" aria-label={t('editor.buttons.asks')}>
      <div className={LABEL}>{t('editor.buttons.asks')}</div>
      {asks.length === 0 && <p className="text-[12px] text-muted break-words hyphens-auto">{t('editor.buttons.asksNone')}</p>}
      {asks.map((_, at) => (
        <AskForm key={at} button={index} index={at} spots={spots} />
      ))}
      <div>
        <button type="button" className="btn" disabled={!editable || asks.length >= MAX_ASKS} onClick={add}>
          <Plus size={15} /> {t('editor.buttons.askAdd')}
        </button>
        {asks.length >= MAX_ASKS && <span className="text-[12px] text-muted ml-2 break-words hyphens-auto">{t('editor.buttons.askMost', { count: MAX_ASKS })}</span>}
      </div>
    </div>
  )
}

function AskForm({ button, index, spots }: { button: number; index: number; spots: TextSpot[] }) {
  const { t } = useTranslation()
  const root: CardPath = ['buttons', button, 'asks', index]
  const editable = useCardEditor((state) => state.card !== null)
  const change = useCardEditor((state) => state.change)
  const [name, setName] = useCardField<string>([...root, 'name'])
  const [type] = useCardField<string>([...root, 'type'])
  const [min, setMin] = useCardField<number>([...root, 'min'])
  const [max, setMax] = useCardField<number>([...root, 'max'])
  const [step, setStep] = useCardField<number>([...root, 'step'])
  const [maxLength, setMaxLength] = useCardField<number>([...root, 'max_length'])
  const [options] = useCardField<{ value?: unknown; label?: unknown }[]>([...root, 'options'])
  const spot = spots.find((one) => one.id === `buttons.${button}.asks.${index}.label`)
  const kind = (ASK_TYPES as readonly string[]).includes(type ?? '') ? (type as AskType) : 'text'
  const number = (setter: (value: number | undefined) => void) => (event: { target: { value: string } }) => setter(event.target.value === '' ? undefined : Number(event.target.value))

  const changeType = (next: AskType) =>
    change((doc) => {
      setAt(doc, [...root, 'type'], next)
      for (const part of ['min', 'max', 'step']) if (next !== 'number') deleteAt(doc, [...root, part])
      if (next !== 'text') deleteAt(doc, [...root, 'max_length'])
      if (next !== 'choice') deleteAt(doc, [...root, 'options'])
      else if (readIn(doc, [...root, 'options']) === undefined) setAt(doc, [...root, 'options'], [{ value: 'a', label: 'A' }])
    })
  const writeOption = (at: number, part: 'value' | 'label', text: string) => change((doc) => setAt(doc, [...root, 'options', at, part], text), `field:${pathText(root)}.options.${at}.${part}`)
  const addOption = () => change((doc) => setAt(doc, [...root, 'options', Array.isArray(options) ? options.length : 0], { value: '', label: '' }))
  const removeOption = (at: number) => change((doc) => deleteAt(doc, [...root, 'options', at]))

  return (
    <div className="grid gap-2 rounded-lg border border-line p-2.5 min-w-0" role="group" aria-label={t('editor.buttons.ask', { number: index + 1 })} data-testid={`card-button-${button}-ask-${index}`}>
      <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] items-end min-w-0">
        <label className="grid gap-1 min-w-0">
          <span className={LABEL}>{t('editor.buttons.askName')}</span>
          <input className="input font-mono min-w-0" value={name ?? ''} disabled={!editable} onChange={(event) => setName(event.target.value)} />
        </label>
        <label className="grid gap-1 min-w-0">
          <span className={LABEL}>{t('editor.buttons.askType')}</span>
          <select className="input" value={kind} disabled={!editable} onChange={(event) => changeType(event.target.value as AskType)}>
            {ASK_TYPES.map((one) => (
              <option key={one} value={one}>
                {t(`editor.buttons.askTypes.${one}`)}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="btn btn-icon btn-flat btn-danger" aria-label={t('editor.buttons.askRemove', { number: index + 1 })} title={t('editor.buttons.askRemove', { number: index + 1 })} disabled={!editable} onClick={() => change((doc) => {
          deleteAt(doc, root)
          const left = readIn(doc, ['buttons', button, 'asks'])
          if (Array.isArray(left) && left.length === 0) deleteAt(doc, ['buttons', button, 'asks'])
        })}>
          <Trash2 size={15} />
        </button>
      </div>
      {spot && <LabelFields spot={spot} />}
      {kind === 'number' && (
        <div className="grid gap-2 grid-cols-3 min-w-0">
          <label className="grid gap-1 min-w-0">
            <span className={LABEL}>{t('editor.buttons.askMin')}</span>
            <input className="input" type="number" value={min ?? ''} disabled={!editable} onChange={number(setMin)} />
          </label>
          <label className="grid gap-1 min-w-0">
            <span className={LABEL}>{t('editor.buttons.askMax')}</span>
            <input className="input" type="number" value={max ?? ''} disabled={!editable} onChange={number(setMax)} />
          </label>
          <label className="grid gap-1 min-w-0">
            <span className={LABEL}>{t('editor.buttons.askStep')}</span>
            <input className="input" type="number" value={step ?? ''} disabled={!editable} onChange={number(setStep)} />
          </label>
        </div>
      )}
      {kind === 'text' && (
        <label className="grid gap-1 min-w-0 sm:max-w-[12rem]">
          <span className={LABEL}>{t('editor.buttons.askLength')}</span>
          <input className="input" type="number" min={1} max={400} value={maxLength ?? ''} disabled={!editable} onChange={number(setMaxLength)} />
        </label>
      )}
      {kind === 'choice' && (
        <div className="grid gap-2 min-w-0" role="group" aria-label={t('editor.buttons.askOptions')}>
          {(Array.isArray(options) ? options : []).map((one, at) => (
            <div key={at} className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] items-start">
              <input className="input font-mono min-w-0" aria-label={t('editor.buttons.askOptionValue', { number: at + 1 })} value={one?.value === undefined || one.value === null ? '' : String(one.value)} disabled={!editable} onChange={(event) => writeOption(at, 'value', event.target.value)} />
              <input className="input min-w-0" aria-label={t('editor.buttons.askOptionLabel', { number: at + 1 })} value={typeof one?.label === 'string' ? one.label : ''} disabled={!editable} onChange={(event) => writeOption(at, 'label', event.target.value)} />
              <button type="button" className="btn btn-icon btn-flat btn-danger" aria-label={t('editor.buttons.askOptionRemove', { number: at + 1 })} disabled={!editable} onClick={() => removeOption(at)}>
                <Trash2 size={15} />
              </button>
            </div>
          ))}
          <div>
            <button type="button" className="btn" disabled={!editable} onClick={addOption}>
              <Plus size={15} /> {t('editor.buttons.askOptionAdd')}
            </button>
          </div>
        </div>
      )}
      <FieldProblems path={root} />
    </div>
  )
}
