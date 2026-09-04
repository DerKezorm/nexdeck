import { useId } from 'react'

import type { FieldSpec } from '../api/types'
import { Field, Select, Switch } from './ui'

interface Props {
  spec: FieldSpec
  value: unknown
  onChange: (value: unknown) => void
  labelOverride?: string
}

/** Draws one adapter field from its spec: text, password, number, bool, select or textarea. */
export function FieldInput({ spec, value, onChange, labelOverride }: Props) {
  const id = useId()
  const label = labelOverride ?? spec.label
  if (spec.type === 'bool') {
    return <Switch checked={Boolean(value ?? spec.default ?? false)} onChange={onChange} label={label} description={spec.help || undefined} />
  }
  if (spec.type === 'select') {
    if (Array.isArray(spec.default)) {
      // Multi-select rendered as checkboxes: used for merged sources.
      const selected = (Array.isArray(value) ? value : []) as string[]
      return (
        <Field label={label} help={spec.help}>
          <div className="flex flex-wrap gap-2">
            {spec.options.map((option) => {
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
      <Field label={label} help={spec.help} htmlFor={id} required={spec.required}>
        <Select id={id} value={String(value ?? spec.default ?? spec.options[0]?.value ?? '')} onChange={onChange} options={spec.options} />
      </Field>
    )
  }
  if (spec.type === 'textarea') {
    return (
      <Field label={label} help={spec.help} htmlFor={id} required={spec.required}>
        <textarea id={id} className="input" value={String(value ?? spec.default ?? '')} placeholder={spec.placeholder} onChange={(event) => onChange(event.target.value)} />
      </Field>
    )
  }
  const inputType = spec.type === 'password' ? 'password' : spec.type === 'number' ? 'number' : spec.type === 'url' ? 'url' : 'text'
  return (
    <Field label={label} help={spec.help} htmlFor={id} required={spec.required}>
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
    </Field>
  )
}
