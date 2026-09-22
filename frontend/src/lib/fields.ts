import type { FieldSpec } from '../api/types'

/**
 * Whether a field applies to what else is chosen, by its ``only_when``.
 *
 * A value nobody set yet counts as the other field's default, which is what
 * the server will use for it too.
 */
export function shownField(field: FieldSpec, fields: FieldSpec[], values: Record<string, unknown>): boolean {
  if (!field.only_when) return true
  const [name, wanted] = field.only_when
  const current = values[name] ?? fields.find((other) => other.name === name)?.default
  return String(current ?? '') === wanted
}
