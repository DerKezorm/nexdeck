/**
 * Suggestions in the YAML view (KARTEN-10 AC-2), from the schema the server hands out. The fixture is the output of
 * `backend/app/cards/schema.py: json_schema()`.
 */
import { describe, expect, it } from 'vitest'

import schema from '../test/cardSchema.json'
import { suggestionsAt, type SchemaNode } from './cardSchemaCompletion'

const SCHEMA = schema as SchemaNode

/** Suggestions where `|` stands. */
function at(textWithCursor: string) {
  const offset = textWithCursor.indexOf('|')
  const text = textWithCursor.replace('|', '')
  const found = suggestionsAt(SCHEMA, text, offset)
  return found ? { from: found.from, labels: found.options.map((one) => one.label) } : null
}

describe('karten10 AC-2: suggestions while typing', () => {
  it('offers the keys of a card at the top, without the ones already written', () => {
    const found = at('nexdeck-card: 1\nslug: a\n|')
    expect(found?.labels).toContain('name')
    expect(found?.labels).toContain('requests')
    expect(found?.labels).not.toContain('slug')
    expect(found?.labels).not.toContain('nexdeck-card')
  })

  it('narrows the keys at the top to the form written, and replaces only the word begun', () => {
    const found = at('form: list\nro|')
    expect(found).toEqual({ from: 11, labels: ['rows'] })
    expect(at('form: value\nru|')).toEqual({ from: 12, labels: ['rules'] })
    expect(at('form: value\nro|')).toBeNull()
  })

  it('offers the keys of a nested map from the indentation above', () => {
    const found = at('form: list\nitem:\n  title: name\n  |')
    expect(found?.labels).toEqual(expect.arrayContaining(['subtitle', 'value', 'status', 'link', 'image']))
    expect(found?.labels).not.toContain('title')
    expect(found?.labels).not.toContain('rows')
  })

  it('offers the keys of a list item, indented or not', () => {
    expect(at('requests:\n  - id: a\n    |')?.labels).toEqual(['path', 'every'])
    expect(at('requests:\n- id: a\n  pa|')?.labels).toEqual(['path'])
    expect(at('requests:\n  - |')?.labels).toEqual(['id', 'path', 'every'])
  })

  it('offers the keys of a value inside a list item two levels down', () => {
    const found = at('form: stats\nstats:\n  - path: a\n    rules:\n      - op: ">"\n        |')
    expect(found?.labels).toEqual(['value', 'formula', 'than', 'then'])
  })

  it('offers the values a key allows after its colon', () => {
    expect(at('form: |')?.labels).toEqual(['value', 'stats', 'list', 'posters'])
    expect(at('form: value\nvalue:\n  path: a\n  format: by|')).toEqual({ from: 39, labels: ['bytes'] })
    expect(at('form: list\nitem:\n  status:\n    - then: |')?.labels).toEqual(['ok', 'warn', 'bad'])
  })

  it('offers nothing in the middle of a value or under an unknown key', () => {
    expect(at('name: My ca|')).toBeNull()
    expect(at('unknown:\n  |')).toBeNull()
  })
})
