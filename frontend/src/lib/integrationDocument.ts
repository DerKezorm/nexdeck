/**
 * What the integration editor reads out of the text of an own integration (KARTEN-3), and what it writes back.
 * The text is the one truth, as with a card; these are the parts the form has fields for.
 */
import { readAt, type CardDoc } from './cardDocument'

export type FieldType = 'text' | 'secret' | 'number' | 'switch'
export const FIELD_TYPES: FieldType[] = ['text', 'secret', 'number', 'switch']

export type AuthType = 'none' | 'header' | 'basic' | 'query' | 'session'
export const AUTH_TYPES: AuthType[] = ['none', 'header', 'basic', 'query', 'session']

/** The most fields and reads a definition carries (the server refuses more). */
export const MAX_FIELDS = 12
export const MAX_READS = 30

export interface DefinedField {
  name: string
  type: FieldType
  label: string
  help: string
  required: boolean
}

export interface DefinedRead {
  path: string
  label: string
}

const text = (value: unknown): string => (typeof value === 'string' ? value : typeof value === 'number' ? String(value) : '')
const map = (value: unknown): Record<string, unknown> => (value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {})

export function fieldsOf(card: CardDoc): DefinedField[] {
  const list = readAt(card, ['fields'])
  if (!Array.isArray(list)) return []
  return list.map((one) => {
    const field = map(one)
    const type = FIELD_TYPES.includes(field.type as FieldType) ? (field.type as FieldType) : 'text'
    return { name: text(field.name), type, label: text(field.label), help: text(field.help), required: field.required === true }
  })
}

export function readsOf(card: CardDoc): DefinedRead[] {
  const list = readAt(card, ['reads'])
  if (!Array.isArray(list)) return []
  return list.map((one) => ({ path: text(map(one).path), label: text(map(one).label) }))
}

export interface DefinedAuth {
  type: AuthType
  /** Every other part of `auth` as plain data, as the definition has it. */
  raw: Record<string, unknown>
}

export function authOf(card: CardDoc): DefinedAuth {
  const raw = map(readAt(card, ['auth']))
  const type = AUTH_TYPES.includes(raw.type as AuthType) ? (raw.type as AuthType) : 'none'
  return { type, raw }
}

/** A new `auth` of this kind, with the first field as a starting point where one is needed. */
export function authDefaults(type: AuthType, names: string[]): Record<string, unknown> {
  const first = names[0] ?? 'token'
  switch (type) {
    case 'none':
      return { type }
    case 'header':
      return { type, header: 'Authorization', value: `Bearer {${first}}` }
    case 'basic':
      return { type, user: `{${names.find((one) => /user/.test(one)) ?? first}}`, password: `{${names.find((one) => /pass/.test(one)) ?? names[1] ?? first}}` }
    case 'query':
      return { type, param: 'token', value: `{${first}}` }
    case 'session':
      return {
        type,
        login: '/api/login',
        send: 'json',
        body: { username: `{${names.find((one) => /user/.test(one)) ?? first}}`, password: `{${names.find((one) => /pass/.test(one)) ?? names[1] ?? first}}` },
        ticket: { from: 'json', at: 'token' },
        pass: { as: 'header', header: 'Authorization', value: 'Bearer {ticket}' },
      }
  }
}

/** The names between braces in a text: `Bearer {token}` names `token`. */
export function placeholdersIn(value: string): string[] {
  return [...value.matchAll(/\{([a-z][a-z0-9_]*)\}/g)].map((match) => match[1])
}

/** The next free field name: `field`, `field_2`, … */
export function freeName(names: string[], base = 'field'): string {
  if (!names.includes(base)) return base
  for (let n = 2; ; n++) if (!names.includes(`${base}_${n}`)) return `${base}_${n}`
}

/** A short name from a name as typed: lower case, letters and digits, `-` between. */
export function shortFrom(name: string): string {
  return name
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 40)
}

export const SHORT_PATTERN = /^[a-z0-9][a-z0-9_-]{0,39}$/
export const FIELD_NAME_PATTERN = /^[a-z][a-z0-9_]{0,31}$/
