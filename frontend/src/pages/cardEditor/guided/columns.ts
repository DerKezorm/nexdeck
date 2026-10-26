/**
 * The names people read for the fields of an answer: "Name" for `attributes.friendly_name`, "State" for `state`. The
 * real field name stands beside it in small type (as in the mock-up), because that is what the card is built on.
 */
import type { TFunction } from 'i18next'

import { splitPath } from '../probe'

/** The last name of a field's path, without its quotes or positions: `series.title` is `title`. */
function lastName(path: string): string {
  const parts = splitPath(path)
  const found = parts ? [...parts].reverse().find((part): part is string => typeof part === 'string') : undefined
  return found ?? path
}

/** `ProductionYear` and `last_changed` as words, for a field nobody has given a name. */
function words(name: string): string {
  const spaced = name.replace(/([a-z0-9])([A-Z])/g, '$1 $2').replace(/[_\-.]+/g, ' ').trim().toLowerCase()
  return spaced ? spaced[0].toUpperCase() + spaced.slice(1) : name
}

/** The name of a field for people. */
export function columnName(t: TFunction, path: string): string {
  if (path === '@') return path
  const last = lastName(path)
  const key = last.toLowerCase().replace(/[^a-z0-9_]/g, '')
  return t(`editor.guided.column.${key}`, { defaultValue: words(last) })
}

/** The name with the real field name behind it, for a choice in a list; just the name where they are the same. */
export function columnLabel(t: TFunction, path: string): string {
  const name = columnName(t, path)
  return name.toLowerCase() === path.toLowerCase() ? path : `${name} (${path})`
}
