/**
 * What the integration editor reads out of a definition and the starting points it writes (KARTEN-3 AC-2 to AC-6),
 * the words of a failed test (AC-9), and which kinds carry the mark "Custom" (AC-8).
 */
import { describe, expect, it } from 'vitest'

import { parseCard } from './cardDocument'
import { isOwnKind } from './customCards'
import { AUTH_TYPES, authDefaults, authOf, fieldsOf, freeName, placeholdersIn, readsOf, shortFrom, SHORT_PATTERN } from './integrationDocument'
import { testResultText } from './testResult'

const read = (text: string) => {
  const parsed = parseCard(text)
  if (!parsed.ok) throw new Error('not a document')
  return parsed.card
}

const TEXT = `nexdeck: integration
short: memos
name: Memos
fields:
  - name: token
    type: secret
    label: Access token
    help: Settings > Access tokens.
    required: true
  - name: strict
    type: switch
auth:
  type: header
  header: Authorization
  value: "Bearer {token}"
reads:
  - path: /api/v1/memos?pageSize=10
    label: Latest notes
`

describe('what the editor reads from the text', () => {
  it('karten3 ac2: the fields with type, label, help and whether they are required', () => {
    expect(fieldsOf(read(TEXT))).toEqual([
      { name: 'token', type: 'secret', label: 'Access token', help: 'Settings > Access tokens.', required: true },
      { name: 'strict', type: 'switch', label: '', help: '', required: false },
    ])
  })

  it('karten3 ac2: a type nobody knows is read as text; a text without fields has none', () => {
    expect(fieldsOf(read('name: x\nfields:\n  - name: a\n    type: weird\n'))[0].type).toBe('text')
    expect(fieldsOf(read('name: x\n'))).toEqual([])
  })

  it('karten3 ac3: the sign-in kind and its parts', () => {
    const auth = authOf(read(TEXT))
    expect(auth.type).toBe('header')
    expect(auth.raw).toMatchObject({ header: 'Authorization', value: 'Bearer {token}' })
    expect(authOf(read('name: x\n')).type).toBe('none')
  })

  it('karten3: what nexdeck can ask', () => {
    expect(readsOf(read(TEXT))).toEqual([{ path: '/api/v1/memos?pageSize=10', label: 'Latest notes' }])
  })
})

describe('the starting point of each kind of sign-in', () => {
  it('karten3 ac3 to ac6: every kind begins with its own parts and names fields, never a key', () => {
    for (const type of AUTH_TYPES) {
      const made = authDefaults(type, ['username', 'password'])
      expect(made.type).toBe(type)
      expect(JSON.stringify(made)).not.toMatch(/secret|password":"[^{]/)
    }
    expect(authDefaults('basic', ['username', 'password'])).toMatchObject({ user: '{username}', password: '{password}' })
    expect(authDefaults('query', ['key'])).toMatchObject({ param: 'token', value: '{key}' })
    expect(authDefaults('session', ['username', 'password'])).toMatchObject({
      login: expect.any(String),
      send: 'json',
      body: { username: '{username}', password: '{password}' },
      ticket: { from: 'json' },
      pass: { as: 'header', value: 'Bearer {ticket}' },
    })
  })

  it('karten3: with no field yet the starting point names a field that is still to make', () => {
    expect(authDefaults('header', [])).toMatchObject({ value: 'Bearer {token}' })
  })
})

describe('small helpers', () => {
  it('names between braces', () => {
    expect(placeholdersIn('Bearer {token} {ticket}')).toEqual(['token', 'ticket'])
    expect(placeholdersIn('nothing here {Bad} {}')).toEqual([])
  })

  it('the next free name', () => {
    expect(freeName([])).toBe('field')
    expect(freeName(['field', 'field_2'])).toBe('field_3')
  })

  it('karten3 ec1: a short name made from a name fits the pattern', () => {
    for (const name of ['Wiki Äpfel', '  Memos!  ', 'a'.repeat(80), 'Über-Wiki 2']) expect(shortFrom(name)).toMatch(SHORT_PATTERN)
    expect(shortFrom('Wiki Äpfel')).toBe('wiki-apfel')
    expect(shortFrom('!!!')).toBe('')
  })
})

describe('the mark Custom', () => {
  it('karten3 ac8: a kind with the prefix or the flag carries it, a built-in one does not', () => {
    expect(isOwnKind({ kind: 'custom:memos' })).toBe(true)
    expect(isOwnKind({ kind: 'memos', custom: true })).toBe(true)
    expect(isOwnKind({ kind: 'sonarr' })).toBe(false)
    expect(isOwnKind({ kind: 'custom' })).toBe(false)
  })
})

describe('the words of a test', () => {
  const t = ((key: string, options?: { defaultValue?: string }) => `<${key}>${options?.defaultValue ? '|' + options.defaultValue : ''}`) as never

  it('karten3 ac9: each code of an own integration has a sentence and a hint of its own', () => {
    for (const code of ['auth_failed', 'unreachable', 'unexpected_answer', 'sign_in_no_ticket', 'sign_in_failed', 'sign_in_web_page']) {
      const said = testResultText(t, { ok: false, code, message: 'M', hint: 'H' })
      expect(said.message).toContain(`settings.integrations.testCode.${code}`)
      expect(said.hint).toContain(`settings.integrations.testHint.${code}`)
    }
  })

  it('karten3 ec4: the pause, a green test and an unknown code keep the words of the server', () => {
    expect(testResultText(t, { ok: false, code: 'sign_in_paused', message: 'Paused until 14:05.', hint: 'wait' })).toEqual({ message: 'Paused until 14:05.', hint: 'wait' })
    expect(testResultText(t, { ok: true, code: 'auth_failed', message: 'Fine.' })).toEqual({ message: 'Fine.', hint: undefined })
    expect(testResultText(t, { ok: false, message: 'Something else.' })).toEqual({ message: 'Something else.', hint: undefined })
  })
})
