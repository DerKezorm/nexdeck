/**
 * The editor's store (KARTEN-9 EC-10, KARTEN-10 AC-1, AC-3 to AC-5, EC-6): one text, read as a document, with every
 * step back since opening, and the last valid version while the text is broken.
 */
import { beforeEach, describe, expect, it } from 'vitest'

import { readAt } from '../../lib/cardDocument'
import { isDirty, TYPING_MS, useCardEditor } from './store'

const CARD = `nexdeck-card: 1
slug: queue
# what the card is called
name: Queue
version: "1.0.0"
requires: [sonarr]
requests:
  - id: queue
    path: /api/v3/queue
form: value
value: totalRecords
`

let now = 1_000_000
const editor = () => useCardEditor.getState()

beforeEach(() => {
  now = 1_000_000
  useCardEditor.setState({ now: () => now })
  editor().open({ slug: 'queue', text: CARD, base: '2026-10-25T10:00:00Z', saved: CARD })
})

describe('karten10: editor and YAML are one text', () => {
  it('karten10 AC-1 AC-4: a change in the editor is in the YAML at once, the comment above stays', () => {
    editor().set(['name'], 'Waiting')
    expect(editor().text).toContain('# what the card is called\nname: Waiting\n')
    expect(editor().text.replace('name: Waiting', 'name: Queue')).toBe(CARD)
  })

  it('karten10 AC-3: a change in the YAML is in the editor at once', () => {
    editor().setText(CARD.replace('path: /api/v3/queue', 'path: /api/v3/queue/details'))
    expect(readAt(editor().card!, ['requests', 0, 'path'])).toBe('/api/v3/queue/details')
  })

  it('karten10 AC-5 EC-5: broken YAML keeps the last valid version, closes the editor, and names the line', () => {
    editor().set(['name'], 'Waiting')
    const validAt = now
    now += 60_000
    editor().setView('yaml')
    editor().setText(`${editor().text}value:\n\tpath: x\n`)
    expect(editor().card).toBeNull()
    expect(editor().problems).toEqual([{ code: 'yaml_tab', line: 13 }])
    expect(readAt(editor().lastValid!.card, ['name'])).toBe('Waiting')
    expect(editor().lastValid!.at).toBe(validAt)
    expect(editor().setView('editor')).toBe(false)
    expect(editor().view).toBe('yaml')
  })

  it('karten10 AC-5: a field cannot change a broken text', () => {
    editor().setText('nexdeck-card: [1\n')
    const broken = editor().text
    editor().set(['name'], 'Other')
    expect(editor().text).toBe(broken)
  })

  it('karten10: a text that is broken on opening opens in the YAML view', () => {
    editor().open({ slug: 'queue', text: 'name: [a\n', base: null, saved: 'name: [a\n' })
    expect(editor().view).toBe('yaml')
  })
})

describe('karten9 EC-10: every step back since opening', () => {
  it('takes back changes from the editor and the YAML alike, and forward again', () => {
    editor().set(['name'], 'One')
    editor().setText(editor().text.replace('every', 'every').replace('totalRecords', 'records'))
    editor().set(['version'], '1.1.0')
    expect(editor().past).toHaveLength(3)
    editor().undo()
    expect(readAt(editor().card!, ['version'])).toBe('1.0.0')
    editor().undo()
    expect(readAt(editor().card!, ['value'])).toBe('totalRecords')
    editor().undo()
    expect(editor().text).toBe(CARD)
    editor().undo()
    expect(editor().text).toBe(CARD)
    editor().redo()
    editor().redo()
    expect(readAt(editor().card!, ['value'])).toBe('records')
    expect(readAt(editor().card!, ['name'])).toBe('One')
  })

  it('makes typing in one field one step, and a pause or another field a new one', () => {
    for (const name of ['Q', 'Qu', 'Que', 'Queu']) {
      now += 200
      editor().set(['name'], name, 'field:name')
    }
    expect(editor().past).toHaveLength(1)
    now += TYPING_MS + 1
    editor().set(['name'], 'Queue!', 'field:name')
    expect(editor().past).toHaveLength(2)
    now += 10
    editor().set(['version'], '2.0.0', 'field:version')
    expect(editor().past).toHaveLength(3)
    editor().undo()
    editor().undo()
    expect(readAt(editor().card!, ['name'])).toBe('Queu')
    editor().undo()
    expect(editor().text).toBe(CARD)
  })

  it('a new change after stepping back drops the steps forward', () => {
    editor().set(['name'], 'One')
    editor().undo()
    editor().set(['name'], 'Two')
    expect(editor().future).toEqual([])
    editor().redo()
    expect(readAt(editor().card!, ['name'])).toBe('Two')
  })

  it('a step back to a broken text closes the editor again', () => {
    editor().setText('name: [a\n')
    editor().setText(CARD)
    editor().undo()
    expect(editor().card).toBeNull()
  })
})

describe('karten9 AC-11: what is unsaved', () => {
  it('is nothing on opening, something after a change, nothing after saving or stepping back to it', () => {
    expect(isDirty(editor())).toBe(false)
    editor().set(['name'], 'Waiting')
    expect(isDirty(editor())).toBe(true)
    editor().undo()
    expect(isDirty(editor())).toBe(false)
    editor().set(['name'], 'Waiting')
    editor().saved('queue', editor().text, '2026-10-25T11:00:00Z')
    expect(isDirty(editor())).toBe(false)
    expect(editor().base).toBe('2026-10-25T11:00:00Z')
  })

  it('is always something for a card never saved', () => {
    editor().open({ slug: null, text: CARD, base: null, saved: null })
    expect(isDirty(editor())).toBe(true)
  })
})

describe('karten10 EC-6: a card near the limit of 60,000 characters', () => {
  it('reads every settled text in good time, and a field changes it without waiting long', () => {
    let rows = ''
    for (let index = 0; rows.length < 57_000; index += 1) rows += `      - {name: guest-${index}, node: pve, type: lxc, vmid: ${100 + index}, mem: 536870912}\n`
    const big = `${CARD}demo:\n  queue:\n    records:\n${rows}`
    expect(big.length).toBeGreaterThan(57_000)
    editor().open({ slug: 'queue', text: big, base: null, saved: big })
    // What the YAML view hands over when typing settles (every 250 ms at most): generous limits, a slow machine passes.
    const started = performance.now()
    for (let index = 0; index < 10; index += 1) editor().setText(big.replace('name: Queue', `name: Queue ${index}`), 'yaml')
    const perText = (performance.now() - started) / 10
    expect(perText).toBeLessThan(250)
    const field = performance.now()
    editor().set(['name'], 'Big')
    expect(performance.now() - field).toBeLessThan(1500)
    expect(editor().text.length).toBe(big.length - 'Queue'.length + 'Big'.length)
  })
})
