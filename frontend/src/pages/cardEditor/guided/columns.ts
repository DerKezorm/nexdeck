/**
 * The names people read for the fields of an answer: "Name" for `attributes.friendly_name`, "State" for `state`. The
 * real field name stands beside it in small type (as in the mock-up), because that is what the card is built on.
 *
 * ⚠️ A name for people belongs to the one field it was written for, found by its whole path: `context.id` is no
 * "ID" because `entity_id` is. A field nobody has named keeps its field name, and in one table or list no two columns
 * carry the same name (`columnNames`).
 */
import type { TFunction } from 'i18next'

/** A top-level field nobody has named as words (`ProductionYear` is "Production year"); a deeper one stays as it is. */
function words(name: string): string {
  const spaced = name.replace(/([a-z0-9])([A-Z])/g, '$1 $2').replace(/[_\-.]+/g, ' ').trim().toLowerCase()
  return spaced ? spaced[0].toUpperCase() + spaced.slice(1) : name
}

/** The word under which a field's name for people is kept: the whole path, `attributes.friendly_name` is `attributes_friendly_name`. */
const keyOf = (path: string) => path.toLowerCase().replace(/[^a-z0-9_]+/g, '_').replace(/^_+|_+$/g, '')

/** The name of a field for people, taken for itself. */
export function columnName(t: TFunction, path: string): string {
  if (path === '@') return path
  const nested = /[.[]/.test(path.replace(/"[^"]*"/g, ''))
  return t(`editor.guided.column.${keyOf(path)}`, { defaultValue: nested ? path : words(path.replace(/^"|"$/g, '')) })
}

/**
 * The names of the fields of one table or list, none of them twice: where two fields would carry the same name, each
 * of them shows its field name instead. Keyed by path.
 */
export function columnNames(t: TFunction, paths: string[]): Record<string, string> {
  const names = paths.map((path) => columnName(t, path))
  const count = (name: string) => names.filter((one) => one.toLowerCase() === name.toLowerCase()).length
  return Object.fromEntries(paths.map((path, at) => [path, count(names[at]) > 1 ? path : names[at]]))
}

/** The names with the real field name behind them, for the choices of a list; just the name where they are the same. */
export function columnLabels(t: TFunction, paths: string[]): Record<string, string> {
  const names = columnNames(t, paths)
  return Object.fromEntries(paths.map((path) => [path, names[path].toLowerCase() === path.toLowerCase() ? path : `${names[path]} (${path})`]))
}
