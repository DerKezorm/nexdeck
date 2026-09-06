import { useQuery } from '@tanstack/react-query'
import { useId } from 'react'
import { useTranslation } from 'react-i18next'

import { get } from '../api/client'
import type { FieldSpec, Integration } from '../api/types'
import { tAdapter } from '../i18n/texts'
import { PlexSignIn } from './PlexSignIn'
import { Field, Select, Switch } from './ui'

interface Props {
  spec: FieldSpec
  value: unknown
  onChange: (value: unknown) => void
  labelOverride?: string
  /** Lets a helper fill several fields at once, such as a token and the server address. */
  onFill?: (values: Record<string, unknown>) => void
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
  const selected = (Array.isArray(value) ? value : []).map(String)
  if (integrations.isLoading) return <Field label={label} help={help}><p className="text-sm text-muted">{t('common.loading')}</p></Field>
  if (choices.length === 0) return <Field label={label} help={help}><p className="text-sm text-muted">{t('widget.noSources')}</p></Field>
  return (
    <Field label={label} help={help}>
      <div className="flex flex-wrap gap-2">
        {choices.map((one) => {
          const id = String(one.id)
          const on = selected.includes(id)
          return (
            <button key={one.id} type="button" className="btn" aria-pressed={on} onClick={() => onChange(on ? selected.filter((v) => v !== id) : [...selected, id])}>
              {one.name}
            </button>
          )
        })}
      </div>
    </Field>
  )
}

/** Draws one adapter field from its spec: text, password, number, bool, select, connections, textarea or time zone. */
export function FieldInput({ spec, value, onChange, labelOverride, onFill }: Props) {
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
