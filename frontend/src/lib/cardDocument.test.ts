import { describe, expect, it } from 'vitest'

import {
  adjustedInYaml,
  changeCard,
  deleteAt,
  diffLines,
  expandValueRef,
  lineOf,
  mergeLines,
  parseCard,
  pathText,
  readAt,
  setAt,
  writingOf,
  type CardDoc,
} from './cardDocument'

/** A card the way people write it: comments above fields and at line ends, flow maps, lists not indented. */
const COMMENTED = `# Guests of the cluster, written by hand.
nexdeck-card: 1
slug: proxmox-guests
name: {en: Guests, de: Gäste}
version: "1.0.0"
# only Proxmox
requires: [proxmox]
requests:
- id: guests
  path: /api2/json/cluster/resources?type=vm   # every guest
  every: 60s
form: list
rows: {select: data, sort: {field: name}, limit: 20}

# what an empty card says
empty: {en: No guests, de: Keine Gäste}
item:
  title: name
  # node, type and number
  subtitle: {template: "{node}, {type} {vmid}"}
  value: {path: mem, format: bytes}
demo:
  guests:
    data:
    - {name: web, node: pve, type: lxc, vmid: 101, mem: 536870912}
`

function card(text: string): CardDoc {
  const parsed = parseCard(text)
  if (!parsed.ok) throw new Error(JSON.stringify(parsed.problems))
  return parsed.card
}

/** The lines of `after` that are not in `before` and the other way round. */
function changedLines(before: string, after: string): { gone: string[]; added: string[] } {
  const hunks = diffLines(before.split('\n'), after.split('\n')) ?? []
  const a = before.split('\n')
  const b = after.split('\n')
  return {
    gone: hunks.flatMap((hunk) => a.slice(hunk.aStart, hunk.aEnd)),
    added: hunks.flatMap((hunk) => b.slice(hunk.bStart, hunk.bEnd)),
  }
}

describe('karten10: the card as one document', () => {
  it('karten10 AC-4: a change in the editor touches only its own line; comments, order and every other line stay character for character', () => {
    const before = card(COMMENTED)
    const after = changeCard(before, (doc) => setAt(doc, ['rows', 'limit'], 10))
    expect(changedLines(COMMENTED, after.text)).toEqual({
      gone: ['rows: {select: data, sort: {field: name}, limit: 20}'],
      added: ['rows: {select: data, sort: {field: name}, limit: 10}'],
    })
  })

  it('karten10 AC-4: a new field comes in as new lines and nothing else moves', () => {
    const after = changeCard(card(COMMENTED), (doc) => setAt(doc, ['description'], 'Every guest with its memory.'))
    const { gone, added } = changedLines(COMMENTED, after.text)
    expect(gone).toEqual([])
    expect(added).toEqual(['description: Every guest with its memory.'])
    expect(readAt(after, ['description'])).toBe('Every guest with its memory.')
  })

  it('karten10 AC-4: a value inside a list item changes in its line only, with its comment at the end of the line', () => {
    const after = changeCard(card(COMMENTED), (doc) => setAt(doc, ['requests', 0, 'every'], '5m'))
    expect(changedLines(COMMENTED, after.text)).toEqual({ gone: ['  every: 60s'], added: ['  every: 5m'] })
    expect(after.text).toContain('path: /api2/json/cluster/resources?type=vm   # every guest')
  })

  it('karten10 EC-1: the comment above a field stays above it when the editor changes the field', () => {
    const after = changeCard(card(COMMENTED), (doc) => setAt(doc, ['item', 'subtitle', 'template'], '{node} {vmid}'))
    expect(after.text).toContain('  # node, type and number\n  subtitle: {template: "{node} {vmid}"}')
  })

  it('karten10 EC-1: a plain value keeps its quotes when it changes', () => {
    const after = changeCard(card(COMMENTED), (doc) => setAt(doc, ['version'], '1.1.0'))
    expect(changedLines(COMMENTED, after.text)).toEqual({ gone: ['version: "1.0.0"'], added: ['version: "1.1.0"'] })
  })

  it('karten10 EC-2: a field deleted in the editor takes its comment with it', () => {
    const after = changeCard(card(COMMENTED), (doc) => deleteAt(doc, ['item', 'subtitle']))
    expect(after.text).not.toContain('node, type and number')
    expect(after.text).not.toContain('subtitle')
    const { gone } = changedLines(COMMENTED, after.text)
    expect(gone).toEqual(['  # node, type and number', '  subtitle: {template: "{node}, {type} {vmid}"}'])
  })

  it('karten10 EC-2: a top-level field with a blank line and a comment above goes with its comment', () => {
    const after = changeCard(card(COMMENTED), (doc) => deleteAt(doc, ['empty']))
    expect(after.text).not.toContain('what an empty card says')
    expect(after.text).not.toContain('Keine Gäste')
    expect(after.text).toContain('# Guests of the cluster, written by hand.')
  })

  it('karten10 AC-4: the author indents lists his own way, and the editor writes new list items the same way', () => {
    expect(writingOf(COMMENTED).indentSeq).toBe(false)
    expect(writingOf('a:\n  - 1\n').indentSeq).toBe(true)
    const after = changeCard(card(COMMENTED), (doc) => setAt(doc, ['requests', 1], { id: 'nodes', path: '/api2/json/nodes' }))
    expect(after.text).toContain('- id: nodes\n  path: /api2/json/nodes\n')
    expect(readAt(after, ['requests', 1, 'id'])).toBe('nodes')
    expect(after.text.startsWith('# Guests of the cluster, written by hand.\nnexdeck-card: 1\n')).toBe(true)
  })

  it('karten10 AC-4: no change, no difference at all', () => {
    const before = card(COMMENTED)
    expect(changeCard(before, (doc) => setAt(doc, ['form'], 'list')).text).toBe(COMMENTED)
  })

  it('karten9 AC-8: a short value becomes its long form to carry a label, and keeps its path', () => {
    const text = 'nexdeck-card: 1\nform: value\nvalue: queue.total\n'
    const after = changeCard(card(text), (doc) => {
      expandValueRef(doc, ['value'])
      setAt(doc, ['value', 'label'], 'Waiting')
    })
    expect(readAt(after, ['value'])).toEqual({ path: 'queue.total', label: 'Waiting' })
  })

  it('finds the line of a field, of a list item and of a missing one', () => {
    const one = card(COMMENTED)
    expect(lineOf(one, ['slug'])).toBe(3)
    expect(lineOf(one, ['requests', 0])).toBe(9)
    expect(lineOf(one, ['item', 'subtitle'])).toBe(20)
    expect(lineOf(one, ['nothing'])).toBeNull()
    expect(pathText(['stats', 1, 'label'])).toBe('stats[1].label')
  })
})

describe('karten10: what the local check refuses', () => {
  it('karten10 EC-7: a tab in the indentation is named at its line', () => {
    const parsed = parseCard('nexdeck-card: 1\nvalue:\n\tpath: x\n')
    expect(parsed).toEqual({ ok: false, problems: [{ code: 'yaml_tab', line: 3 }] })
  })

  it('karten10 EC-7: a tab inside a value is no indentation and passes', () => {
    expect(parseCard('nexdeck-card: 1\nname: "a\tb"\n').ok).toBe(true)
  })

  it('karten10 EC-3: an anchor and an alias are refused at their lines', () => {
    const parsed = parseCard('nexdeck-card: 1\nrules: &same\n  - {op: ">", than: 1, then: warn}\nvalue:\n  path: x\n  rules: *same\n')
    expect(parsed.ok).toBe(false)
    if (parsed.ok) return
    expect(parsed.problems.map((one) => [one.code, one.line])).toEqual([
      ['yaml_anchor', 2],
      ['yaml_alias', 6],
    ])
  })

  it('karten10 EC-3: a second document is refused at the line of its marker', () => {
    const parsed = parseCard('nexdeck-card: 1\nslug: a\n---\nnexdeck-card: 1\nslug: b\n')
    expect(parsed.ok).toBe(false)
    if (!parsed.ok) expect(parsed.problems).toEqual([{ code: 'yaml_documents', line: 3 }])
  })

  it('karten10 AC-2: broken YAML is named at its line with the reason', () => {
    const parsed = parseCard('nexdeck-card: 1\nname: [a, b\nslug: x\n')
    expect(parsed.ok).toBe(false)
    if (parsed.ok) return
    expect(parsed.problems[0].code).toBe('yaml_syntax')
    expect(parsed.problems[0].line).toBeGreaterThanOrEqual(2)
    expect(parsed.problems[0].reason).toBeTruthy()
    expect(parsed.problems[0].reason).not.toMatch(/at line/)
  })

  it('karten10: a text that is not a map, or nothing at all, is no card', () => {
    expect(parseCard('- a\n- b\n')).toEqual({ ok: false, problems: [{ code: 'yaml_not_map', line: 1 }] })
    expect(parseCard('  \n')).toEqual({ ok: false, problems: [{ code: 'yaml_empty', line: null }] })
  })

  it('karten10: a duplicate key is refused', () => {
    expect(parseCard('slug: a\nslug: b\n').ok).toBe(false)
  })
})

describe('karten9 AC-12: what the editor leaves to the YAML view', () => {
  it('names the parts it has no field for, with their lines, and nothing else', () => {
    const text = `${COMMENTED}buttons:\n  - {label: Restart}\n`
    const parts = adjustedInYaml(card(text))
    expect(parts).toEqual([{ path: ['buttons'], line: 26 }])
  })

  it('names a row filter written as an expression, which the Look step cannot pick from the tree', () => {
    const text = 'nexdeck-card: 1\nform: list\nrows:\n  select: "@[?hasFile == `false`] | sort_by(@, &airDateUtc)"\nitem: {title: series.title}\n'
    expect(adjustedInYaml(card(text))).toEqual([{ path: ['rows', 'select'], line: 4 }])
    expect(adjustedInYaml(card('nexdeck-card: 1\nform: list\nrows: {select: records}\nitem: {title: a}\n'))).toEqual([])
  })

  it('names an unknown key deep inside a value, and takes the short form of a value', () => {
    const text = 'nexdeck-card: 1\nform: stats\nstats:\n  - a.b\n  - {path: c, colour: red}\n'
    expect(adjustedInYaml(card(text))).toEqual([{ path: ['stats', 1, 'colour'], line: 5 }])
  })
})

describe('the line merge', () => {
  it('keeps what only the author changed and takes what only the editor changed', () => {
    expect(mergeLines('a\nb\nc\nd', 'a\nB\nc\nd', 'a\nb\nc\nD')).toBe('a\nB\nc\nD')
  })

  it('lets the change win where both touch the same lines', () => {
    expect(mergeLines('a\nb\nc', 'a\nB\nc', 'a\nX\nc')).toBe('a\nX\nc')
  })

  it('diffs equal texts to nothing and finds an insertion', () => {
    expect(diffLines(['a', 'b'], ['a', 'b'])).toEqual([])
    expect(diffLines(['a', 'c'], ['a', 'b', 'c'])).toEqual([{ aStart: 1, aEnd: 1, bStart: 1, bEnd: 2 }])
  })
})
