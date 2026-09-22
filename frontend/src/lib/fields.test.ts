/**
 * ⚠️ A field that belongs to the other choice must not be on screen. The SNMP
 * sheet asks for a v3 user or a v2c community, never both, and a form that
 * shows both reads as "fill in all of it".
 */
import { describe, expect, it } from 'vitest'

import type { FieldSpec } from '../api/types'
import { shownField } from './fields'

const FIELDS = [
  { name: 'version', label: 'SNMP version', type: 'select', default: '3' },
  { name: 'community', label: 'Community', type: 'password', only_when: ['version', '2c'] },
  { name: 'username', label: 'User', type: 'text', only_when: ['version', '3'] },
  { name: 'host', label: 'Host', type: 'text' },
] as unknown as FieldSpec[]

const shown = (values: Record<string, unknown>) =>
  FIELDS.filter((field) => shownField(field, FIELDS, values)).map((field) => field.name)

describe('shownField', () => {
  it('shows a field without a condition', () => {
    expect(shown({ version: '2c' })).toContain('host')
  })

  it('follows what is chosen', () => {
    expect(shown({ version: '2c' })).toEqual(['version', 'community', 'host'])
    expect(shown({ version: '3' })).toEqual(['version', 'username', 'host'])
  })

  it('counts the default while nobody has chosen anything', () => {
    // The server fills the default in too, so the form has to show the same
    // fields it will be saved with.
    expect(shown({})).toEqual(['version', 'username', 'host'])
  })
})
