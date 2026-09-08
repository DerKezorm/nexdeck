import { useQuery } from '@tanstack/react-query'
import { useId } from 'react'
import { useTranslation } from 'react-i18next'

import { get } from '../api/client'
import type { BoardSummary, FieldSpec, Integration } from '../api/types'
import { tAdapter } from '../i18n/texts'
import { PicturePicker } from './PicturePicker'
import { PlexSignIn } from './PlexSignIn'
import { Field, Select, Switch } from './ui'

interface Props {
  spec: FieldSpec
  value: unknown
  onChange: (value: unknown) => void
  labelOverride?: string
  /** Lets a helper fill several fields at once, such as a token and the server address. */
  onFill?: (values: Record<string, unknown>) => void
  /** The rows the card is showing right now, for a field that picks among them. */
  items?: Record<string, unknown>[]
  /** Every row the card has, so a switched-off one keeps its button. */
  allTitles?: string[]
  /** The connection a `choices` field asks for its answers. */
  integrationId?: number
}

/** The browser's own list of IANA zones; empty in browsers that cannot say. */
const TIME_ZONES: string[] = (() => {
  try {
    const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] }
    return intl.supportedValuesOf?.('timeZone') ?? []
  } catch {
    return []
  }
})()

/** Picks connections of the kinds the field names, and stores their numbers.
 *
 * The list comes from the same endpoint the settings sheet uses, which leaves
 * out connections reserved for administrators. The server checks the numbers
 * again on save; this only keeps the sheet from offering what would be
 * refused.
 */
function IntegrationPicker({ spec, value, onChange, label, help }: { spec: FieldSpec; value: unknown; onChange: (value: unknown) => void; label: string; help?: string }) {
  const { t } = useTranslation()
  const integrations = useQuery({ queryKey: ['integrations'], queryFn: () => get<Integration[]>('/integrations') })
  const kinds = spec.options.map((option) => option.value)
  const choices = (integrations.data ?? []).filter((one) => kinds.length === 0 || kinds.includes(one.kind))
  // ⚠️ One or several, decided by the field's own default, the way the select
  // field already decides it. The calendar merges sources and wants a list; a
  // button acts on one connection, and a list there would be a card that does
  // the same thing twice with no way to say so.
  const many = Array.isArray(spec.default)
  const selected = (Array.isArray(value) ? value : []).map(String)
  const one_selected = String(value ?? '')
  if (integrations.isLoading) return <Field label={label} help={help}><p className="text-sm text-muted">{t('common.loading')}</p></Field>
  if (choices.length === 0) return <Field label={label} help={help}><p className="text-sm text-muted">{t('widget.noSources')}</p></Field>
  return (
    <Field label={label} help={help}>
      <div className="flex flex-wrap gap-2">
        {choices.map((one) => {
          const id = String(one.id)
          const on = many ? selected.includes(id) : one_selected === id
          return (
            <button
              key={one.id}
              type="button"
              className="btn"
              aria-pressed={on}
              onClick={() => {
                if (!many) return onChange(on ? '' : id)
                return onChange(on ? selected.filter((v) => v !== id) : [...selected, id])
              }}
            >
              {one.name}
            </button>
          )
        })}
      </div>
    </Field>
  )
}

/**
 * Which rows of a list card are shown.
 *
 * ⚠️ Nothing ticked means all of them, and that is not laziness: the rows come
 * from the service, so a new disk or a new container appears on its own. A
 * picker that stored "these five" would quietly hide the sixth, which is the
 * one somebody would want to see.
 */
function ItemPicker({ value, onChange, label, help, items, allTitles }: {
  value: unknown
  onChange: (value: unknown) => void
  label: string
  help?: string
  items?: Record<string, unknown>[]
  /** Every row the card has, hidden ones included. */
  allTitles?: string[]
}) {
  const { t } = useTranslation()
  const chosen = (Array.isArray(value) ? value : []) as string[]
  // ⚠️ The complete list, not the visible one. Built from what the card shows,
  // switching a row off took its own button away with it and there was no way
  // back short of clearing the whole option.
  const rows = (allTitles ?? (items ?? []).map((item) => String(item.title ?? ''))).filter(Boolean)
  const unique = [...new Set([...rows, ...chosen])]
  return (
    <Field label={label} help={help}>
      {unique.length === 0 ? (
        <p className="text-[12px] text-faint">{t('widget.rows.none')}</p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {unique.map((title) => {
            const on = chosen.length === 0 || chosen.includes(title)
            return (
              <button
                key={title}
                type="button"
                className="btn btn-xs"
                aria-pressed={on}
                onClick={() => {
                  // The first click on a card that shows everything means
                  // "only not this one", so the list starts as everything.
                  const base = chosen.length === 0 ? unique : chosen
                  const next = base.includes(title) ? base.filter((one) => one !== title) : [...base, title]
                  onChange(next.length === unique.length ? [] : next)
                }}
              >
                {title}
              </button>
            )
          })}
        </div>
      )}
      <p className="text-[11px] text-faint mt-1">
        {chosen.length === 0 ? t('widget.rows.all') : t('widget.rows.some', { count: chosen.length })}
      </p>
    </Field>
  )
}

/**
 * A dropdown whose answers come from the service, not from the code.
 *
 * ⚠️ Some questions cannot be written into a spec. "Which switch" is answered
 * by the console, and typing a name instead works until there are fourteen of
 * them.
 */
function RemoteChoice({ spec, value, onChange, label, help, integrationId }: {
  spec: FieldSpec
  value: unknown
  onChange: (value: unknown) => void
  label: string
  help?: string
  integrationId?: number
}) {
  const { t } = useTranslation()
  const offered = useQuery({
    queryKey: ['choices', integrationId, spec.name],
    queryFn: () => get<{ value: string; label: string }[]>(`/integrations/${integrationId}/choices/${spec.name}`),
    enabled: Boolean(integrationId),
    retry: false,
  })
  if (!integrationId) {
    return (
      <Field label={label} help={help}>
        <p className="text-[12px] text-faint">{t('widget.choices.pickConnection')}</p>
      </Field>
    )
  }
  if (offered.isPending) {
    return (
      <Field label={label} help={help}>
        <p className="text-[12px] text-faint">{t('common.loading')}</p>
      </Field>
    )
  }
  const rows = offered.data ?? []
  if (offered.isError || rows.length === 0) {
    return (
      <Field label={label} help={help}>
        <p className="text-[12px] text-warn">{t('widget.choices.none')}</p>
      </Field>
    )
  }
  // ⚠️ Through the adapter dictionary, like every other adapter text. Most of
  // these labels are names from the service ("4K Mediathek", "sabnzbd") and
  // come back unchanged, because the dictionary translates by exact wording
  // and knows nothing about them. The few that are the adapter's own words,
  // such as the list of what a connection offers a button, were English on
  // screen until this line existed.
  const named = rows.map((row) => ({ value: row.value, label: tAdapter(row.label) }))
  return (
    <Field label={label} help={help}>
      <Select
        value={String(value ?? '')}
        onChange={onChange}
        options={[{ value: '', label: t('widget.choices.unset') }, ...named]}
      />
    </Field>
  )
}

/** Draws one adapter field from its spec: text, password, number, bool, select, connections, textarea or time zone. */
/**
 * One of this installation's own boards, or one page of it.
 *
 * ⚠️ Its own field type rather than the one that asks a service. The list of
 * boards is nexdeck's, not any integration's, and the field that asks a
 * service needs a connection to ask; a card that belongs to no service has
 * none.
 *
 * The value is what an address is made of later: "home", or "home/media".
 */
function BoardPicker({ value, onChange, label, help }: { value: unknown; onChange: (value: unknown) => void; label: string; help?: string }) {
  const { t } = useTranslation()
  const boards = useQuery({ queryKey: ['boards', false], queryFn: () => get<BoardSummary[]>('/boards') })
  const chosen = typeof value === 'string' ? value : ''
  const rows = boards.data ?? []
  if (boards.isPending) {
    return (
      <Field label={label} help={help}>
        <p className="text-[12px] text-faint">{t('common.loading')}</p>
      </Field>
    )
  }
  if (boards.isError || rows.length === 0) {
    return (
      <Field label={label} help={help}>
        <p className="text-[12px] text-warn">{t('widget.boardsNone')}</p>
      </Field>
    )
  }
  return (
    <Field label={label} help={help}>
      <Select
        value={chosen}
        onChange={onChange}
        options={[
          { value: '', label: t('widget.boardPick') },
          ...rows.flatMap((board) => [
            { value: board.slug, label: board.name },
            // A board with one page is that page; offering it twice would be
            // two entries that do the same thing.
            ...(board.pages.length > 1
              ? board.pages.map((page) => ({ value: `${board.slug}/${page.slug}`, label: `${board.name} \u203a ${page.name}` }))
              : []),
          ]),
        ]}
      />
    </Field>
  )
}

/**
 * A colour, or none at all.
 *
 * ⚠️ "None" has to be its own control. A colour input cannot be empty: it
 * shows black when it has no value, and picking black to mean "leave it
 * alone" is not a thing anybody guesses. So the swatch sets a colour and the
 * button next to it takes it away again.
 */
function ColourPicker({ value, onChange, label, help }: { value: unknown; onChange: (value: unknown) => void; label: string; help?: string }) {
  const { t } = useTranslation()
  const chosen = typeof value === 'string' ? value : ''
  return (
    <Field label={label} help={help}>
      <div className="flex items-center gap-2">
        <input
          type="color"
          className="h-8 w-12 rounded-lg border border-line bg-transparent p-0.5"
          value={chosen || '#22d3ee'}
          aria-label={label}
          onChange={(event) => onChange(event.target.value)}
        />
        <span className="num text-[12px] text-muted w-20">{chosen || t('widget.colourNone')}</span>
        <button type="button" className="btn btn-xs" disabled={!chosen} onClick={() => onChange('')}>
          {t('widget.colourClear')}
        </button>
      </div>
    </Field>
  )
}

export function FieldInput({ spec, value, onChange, labelOverride, onFill, items, allTitles, integrationId }: Props) {
  const { t } = useTranslation()
  const id = useId()
  // Adapters speak English; the field is shown in the user's language.
  const label = labelOverride ?? tAdapter(spec.label)
  const help = tAdapter(spec.help) || undefined
  if (spec.type === 'bool') {
    return <Switch checked={Boolean(value ?? spec.default ?? false)} onChange={onChange} label={label} description={help} />
  }
  if (spec.type === 'integrations') {
    return <IntegrationPicker spec={spec} value={value} onChange={onChange} label={label} help={help} />
  }
  if (spec.type === 'choices') {
    return <RemoteChoice spec={spec} value={value} onChange={onChange} label={label} help={help} integrationId={integrationId} />
  }
  if (spec.type === 'pictures') {
    return <PicturePicker value={value} onChange={onChange} label={label} help={help} />
  }
  if (spec.type === 'board') {
    return <BoardPicker value={value} onChange={onChange} label={label} help={help} />
  }
  if (spec.type === 'colour') {
    return <ColourPicker value={value} onChange={onChange} label={label} help={help} />
  }
  if (spec.type === 'items') {
    return <ItemPicker value={value} onChange={onChange} label={label} help={help} items={items} allTitles={allTitles} />
  }
  if (spec.type === 'select') {
    const options = spec.options.map((option) => ({ value: option.value, label: tAdapter(option.label) }))
    if (Array.isArray(spec.default)) {
      // Multi-select rendered as checkboxes: used for merged sources.
      const selected = (Array.isArray(value) ? value : []) as string[]
      return (
        <Field label={label} help={help}>
          <div className="flex flex-wrap gap-2">
            {options.map((option) => {
              const on = selected.includes(option.value)
              return (
                <button key={option.value} type="button" className="btn" aria-pressed={on} onClick={() => onChange(on ? selected.filter((v) => v !== option.value) : [...selected, option.value])}>
                  {option.label}
                </button>
              )
            })}
          </div>
        </Field>
      )
    }
    return (
      <Field label={label} help={help} htmlFor={id} required={spec.required}>
        <Select id={id} value={String(value ?? spec.default ?? spec.options[0]?.value ?? '')} onChange={onChange} options={options} />
      </Field>
    )
  }
  if (spec.type === 'textarea') {
    return (
      <Field label={label} help={help} htmlFor={id} required={spec.required}>
        <textarea id={id} className="input" value={String(value ?? spec.default ?? '')} placeholder={spec.placeholder} onChange={(event) => onChange(event.target.value)} />
      </Field>
    )
  }
  if (spec.type === 'timezone') {
    const current = String(value ?? '')
    const unknown = current !== '' && TIME_ZONES.length > 0 && !TIME_ZONES.includes(current)
    return (
      <Field label={label} help={help} htmlFor={id} required={spec.required}>
        <input id={id} className="input" list={`${id}-zones`} value={current} placeholder={t('widget.timezoneBrowser')} autoComplete="off" onChange={(event) => onChange(event.target.value)} />
        <datalist id={`${id}-zones`}>
          {TIME_ZONES.map((zone) => (
            <option key={zone} value={zone} />
          ))}
        </datalist>
        {unknown && <p className="text-[11px] mt-1 text-warn">{t('widget.timezoneUnknown')}</p>}
      </Field>
    )
  }
  const inputType = spec.type === 'password' ? 'password' : spec.type === 'number' ? 'number' : spec.type === 'url' ? 'url' : 'text'
  return (
    <Field label={label} help={help} htmlFor={id} required={spec.required}>
      <input
        id={id}
        className="input"
        type={inputType}
        step={spec.type === 'number' ? 'any' : undefined}
        value={value === undefined || value === null ? '' : String(value)}
        placeholder={spec.secret && value === '********' ? '********' : spec.placeholder}
        autoComplete={spec.type === 'password' ? 'new-password' : 'off'}
        onChange={(event) => onChange(spec.type === 'number' ? (event.target.value === '' ? '' : Number(event.target.value)) : event.target.value)}
      />
      {spec.helper === 'plex-signin' && <PlexSignIn onFill={(values) => (onFill ? onFill(values) : onChange(values[spec.name]))} />}
    </Field>
  )
}
