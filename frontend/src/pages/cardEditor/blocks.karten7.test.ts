/**
 * The logic of the builder (KARTEN-7): how blocks are counted, added, moved, dragged and taken out of the card's
 * document, with the most blocks and the deepest level a card may have.
 */
import { describe, expect, it } from 'vitest'

import { changeCard, parseCard, readAt, type CardDoc } from '../../lib/cardDocument'
import { adjustedInYaml, EDITOR_SHOWS } from '../../lib/cardDocument'
import { addBlock, canAdd, canDrop, countOf, dropBlock, flatten, MAX_BLOCKS, MAX_DEPTH, moveBlock, removeBlock, totalOf } from './blocks'
import { refusalOf } from './guided/guided'
import { changeForm, lostByForm } from './slots'

function open(text: string): CardDoc {
  const parsed = parseCard(`nexdeck-card: 1\nslug: x\nname: X\nversion: "1.0.0"\nform: builder\n${text}`)
  if (!parsed.ok) throw new Error('not a card')
  return parsed.card
}

const TREE = `blocks:
  - type: row
    children:
      - {type: text, text: a}
      - type: column
        children:
          - {type: text, text: b}
  - {type: text, text: c}
  - type: list
    item:
      - {type: text, text: d}
`

const kinds = (card: CardDoc) => flatten(card).map((one) => `${one.depth}${one.type}`)
const run = (card: CardDoc, edit: Parameters<typeof changeCard>[1]) => changeCard(card, edit)

describe('the blocks of a card', () => {
  it('karten7 ac5 counts a block with everything inside it', () => {
    const card = open(TREE)
    expect(totalOf(card)).toBe(7)
    expect(countOf(readAt(card, ['blocks', 0]))).toBe(4)
    expect(countOf(readAt(card, ['blocks', 2]))).toBe(2)
    expect(countOf(readAt(card, ['blocks', 1]))).toBe(1)
    expect(kinds(card)).toEqual(['1row', '2text', '2column', '3text', '1text', '1list', '2text'])
  })

  it('karten7 ac5 adds no block to a card that has one hundred', () => {
    const full = open('blocks:\n' + '  - {type: divider}\n'.repeat(MAX_BLOCKS))
    expect(canAdd(full, null, 'divider')).toBe(false)
    const one = open('blocks:\n' + '  - {type: divider}\n'.repeat(MAX_BLOCKS - 1))
    expect(canAdd(one, null, 'divider')).toBe(true)
    // Inside a row, with the ones inside it counted, the same.
    const rowed = open('blocks:\n  - type: row\n    children:\n' + '      - {type: divider}\n'.repeat(MAX_BLOCKS - 1))
    expect(totalOf(rowed)).toBe(MAX_BLOCKS)
    expect(addBlock(rowed.doc, rowed, [], 'divider')).toBeNull()
  })

  it('karten7 ec4 adds into a container and behind any other block, and a list gets the first list of the data for its rows', () => {
    const card = open('blocks:\n  - {type: text, text: a}\n  - {type: row, children: []}\n')
    const into = run(card, (doc) => void addBlock(doc, card, ['blocks', 1], 'divider'))
    expect(kinds(into)).toEqual(['1text', '1row', '2divider'])
    const behind = run(card, (doc) => void addBlock(doc, card, ['blocks', 0], 'divider'))
    expect(kinds(behind)).toEqual(['1text', '1divider', '1row'])
    const listed = run(card, (doc) => void addBlock(doc, card, null, 'list', { lists: ['records'] }))
    expect(readAt(listed, ['rows', 'select'])).toBe('records')
    // Rows the card already has are kept.
    const own = open('rows: {select: items}\nblocks: []\n')
    expect(readAt(run(own, (doc) => void addBlock(doc, own, null, 'list', { lists: ['records'] })), ['rows', 'select'])).toBe('items')
  })

  it('karten7 ac1 starts a sparkline with a short name that no other block has', () => {
    const card = open('blocks:\n  - {type: sparkline, id: trend, value: {path: a}}\n')
    const next = run(card, (doc) => void addBlock(doc, card, null, 'sparkline'))
    expect(flatten(next).map((one) => one.block.id)).toEqual(['trend', 'trend_2'])
  })

  it('karten7 ac4 allows no list inside the template of a list', () => {
    const card = open(TREE)
    expect(canAdd(card, ['blocks', 2], 'list')).toBe(false)
    expect(canAdd(card, ['blocks', 2], 'text')).toBe(true)
    expect(canAdd(card, ['blocks', 1], 'list')).toBe(true)
    // And a list that holds a row cannot be dragged into another list either.
    expect(canDrop(card, ['blocks', 2], ['blocks', 2, 'item', 0])).toBe(false)
  })

  it('karten7 ac5 keeps to six levels', () => {
    const nest = (levels: number, leaf: string): string => (levels === 1 ? leaf : `{type: column, children: [${nest(levels - 1, leaf)}]}`)
    const card = open(`blocks:
  - ${nest(MAX_DEPTH, '{type: row, children: []}')}
`)
    const row = flatten(card).find((one) => one.type === 'row')!
    expect(row.depth).toBe(MAX_DEPTH)
    // A block at the sixth level holds nothing more; the column above it still takes one at the sixth.
    expect(canAdd(card, row.path, 'divider')).toBe(false)
    const above = flatten(card).find((one) => one.depth === MAX_DEPTH - 1)!
    expect(canAdd(card, above.path, 'divider')).toBe(true)
    expect(addBlock(card.doc, card, row.path, 'divider')).toBeNull()
  })
})

/** A card with a button of the card and one of every row, a list and a main value, to try what the server would refuse. */
const WITH_BUTTONS = `buttons:
  - {id: reboot, label: Reboot, where: card, method: POST, path: /api/reboot}
  - {id: restart, label: Restart, where: row, method: POST, path: "/api/c/{id}/restart"}
main: cpu
rows: {select: containers}
blocks:
  - {type: value, id: cpu, path: host.cpu}
  - {type: button, button: restart}
  - {type: sparkline, id: trend, value: {path: host.cpu}}
  - type: list
    item:
      - {type: text, value: {path: name}}
      - {type: button, button: restart}
`

describe('what the server would refuse, the editor does not make (KARTEN-7 AC-1)', () => {
  it('karten7 ac1 puts no sparkline into a list, by adding or by dragging', () => {
    const card = open(WITH_BUTTONS)
    expect(canAdd(card, ['blocks', 3], 'sparkline')).toBe(false)
    expect(canAdd(card, ['blocks', 3, 'item', 0], 'sparkline')).toBe(false)
    expect(addBlock(card.doc, card, ['blocks', 3], 'sparkline')).toBeNull()
    expect(canAdd(card, ['blocks', 0], 'sparkline')).toBe(true)
    expect(canDrop(card, ['blocks', 2], ['blocks', 3])).toBe(false)
    expect(canDrop(card, ['blocks', 2], ['blocks', 3, 'item', 0])).toBe(false)
    // Not hidden inside a row either.
    const wrapped = open('rows: {select: x}\nblocks:\n  - type: row\n    children: [{type: sparkline, id: s, value: {path: a}}]\n  - {type: list, item: []}\n')
    expect(canDrop(wrapped, ['blocks', 0], ['blocks', 1])).toBe(false)
  })

  it('karten7 ac1 keeps the main value out of a list', () => {
    const card = open(WITH_BUTTONS)
    expect(canDrop(card, ['blocks', 0], ['blocks', 3])).toBe(false)
    expect(canDrop(card, ['blocks', 0], ['blocks', 3, 'item', 0])).toBe(false)
    // Any other value, and the main value anywhere outside a list, may go.
    const other = open(WITH_BUTTONS.replace('main: cpu\n', ''))
    expect(canDrop(other, ['blocks', 0], ['blocks', 3])).toBe(true)
    expect(canDrop(card, ['blocks', 0], ['blocks', 2])).toBe(true)
  })

  it('karten7 ac1 keeps the button of every row inside a list, and lets the button of the card stand anywhere', () => {
    const card = open(WITH_BUTTONS)
    // Dragged out of the list, or stepped out with the arrows.
    expect(canDrop(card, ['blocks', 3, 'item', 1], ['blocks', 0])).toBe(false)
    expect(run(card, (doc) => expect(moveBlock(doc, ['blocks', 3, 'item', 1], 1)).toBeNull())).toBe(card)
    // A row holding it cannot leave either.
    const inRow = open(
      'buttons:\n  - {id: restart, label: Restart, where: row, method: POST, path: /a}\nrows: {select: x}\nblocks:\n  - type: list\n    item:\n      - {type: row, children: [{type: button, button: restart}]}\n  - {type: divider}\n',
    )
    expect(moveBlock(inRow.doc, ['blocks', 0, 'item', 0], 1)).toBeNull()
    expect(canDrop(inRow, ['blocks', 0, 'item', 0], ['blocks', 1])).toBe(false)
    // Inside the template it may move about, and a button of the card leaves freely.
    expect(canDrop(card, ['blocks', 3, 'item', 1], ['blocks', 3, 'item', 0])).toBe(true)
    const free = open('buttons:\n  - {id: reboot, label: Reboot, where: card, method: POST, path: /a}\nrows: {select: x}\nblocks:\n  - type: list\n    item: [{type: button, button: reboot}]\n')
    expect(moveBlock(free.doc, ['blocks', 0, 'item', 0], 1)).toEqual(['blocks', 1])
  })

  it('karten7 ac1 starts a list empty, which the server takes like an empty row', () => {
    const card = open('rows: {select: x}\nblocks: []\n')
    const next = run(card, (doc) => void addBlock(doc, card, null, 'list'))
    expect(readAt(next, ['blocks', 0])).toEqual({ type: 'list', item: [] })
  })
})

describe('moving and taking out', () => {
  it('karten7 ec4 swaps with a neighbour and steps out at the end of a row, column or list', () => {
    const card = open(TREE)
    const swapped = run(card, (doc) => void moveBlock(doc, ['blocks', 1], -1))
    expect(kinds(swapped)).toEqual(['1text', '1row', '2text', '2column', '3text', '1list', '2text'])
    // The last in a column steps out behind the column, inside the row.
    const out = run(card, (doc) => void moveBlock(doc, ['blocks', 0, 'children', 1, 'children', 0], 1))
    expect(kinds(out)).toEqual(['1row', '2text', '2column', '2text', '1text', '1list', '2text'])
    // And the first one steps out in front of it.
    const before = run(card, (doc) => void moveBlock(doc, ['blocks', 0, 'children', 1, 'children', 0], -1))
    expect(kinds(before)).toEqual(['1row', '2text', '2text', '2column', '1text', '1list', '2text'])
    // The first on the card and the last cannot go further.
    expect(run(card, (doc) => expect(moveBlock(doc, ['blocks', 0], -1)).toBeNull())).toBe(card)
  })

  it('karten7 ec4 keeps the comments of the blocks that move', () => {
    const card = open('blocks:\n  # first\n  - {type: text, text: a}\n  # second\n  - {type: text, text: b}\n')
    const moved = run(card, (doc) => void moveBlock(doc, ['blocks', 0], 1))
    expect(moved.text).toContain('# first')
    expect(moved.text.indexOf('{type: text, text: b}')).toBeLessThan(moved.text.indexOf('{type: text, text: a}'))
  })

  it('karten7 ec6 takes a block out with everything inside it, and the main value with the block', () => {
    const card = open('main: m\nblocks:\n  - type: row\n    children:\n      - {type: value, id: m, path: x}\n      - {type: text, text: a}\n  - {type: text, text: b}\n')
    const next = run(card, (doc) => removeBlock(doc, ['blocks', 0]))
    expect(kinds(next)).toEqual(['1text'])
    expect(readAt(next, ['main'])).toBeUndefined()
    // Another block going leaves the main value alone.
    const other = run(card, (doc) => removeBlock(doc, ['blocks', 1]))
    expect(readAt(other, ['main'])).toBe('m')
  })

  it('karten7 ec4 drops a block after another one, and into a container at its end, and not into itself', () => {
    const card = open(TREE)
    const into = run(card, (doc) => void dropBlock(doc, card, ['blocks', 1], ['blocks', 0]))
    expect(kinds(into)).toEqual(['1row', '2text', '2column', '3text', '2text', '1list', '2text'])
    // Dropped on a block in the same list further on: it goes behind it, whatever the index did meanwhile.
    const same = open('blocks:\n  - {type: text, text: a}\n  - {type: text, text: b}\n  - {type: text, text: c}\n')
    const after = run(same, (doc) => void dropBlock(doc, same, ['blocks', 0], ['blocks', 1]))
    expect(flatten(after).map((one) => one.block.text)).toEqual(['b', 'a', 'c'])
    const back = run(same, (doc) => void dropBlock(doc, same, ['blocks', 2], ['blocks', 0]))
    expect(flatten(back).map((one) => one.block.text)).toEqual(['a', 'c', 'b'])
    expect(canDrop(card, ['blocks', 0], ['blocks', 0])).toBe(false)
    expect(canDrop(card, ['blocks', 0], ['blocks', 0, 'children', 1, 'children', 0])).toBe(false)
    // A block dropped into a container further down: the container's place has moved up by the one that left.
    const down = run(card, (doc) => void dropBlock(doc, card, ['blocks', 1], ['blocks', 2]))
    expect(kinds(down)).toEqual(['1row', '2text', '2column', '3text', '1list', '2text', '2text'])
    expect(flatten(down).map((one) => one.block.text ?? '')).toEqual(['', 'a', '', 'b', '', 'd', 'c'])
    // A block dropped on a row from further down shifts the places of what is below it.
    const lower = run(card, (doc) => void dropBlock(doc, card, ['blocks', 0, 'children', 0], ['blocks', 2]))
    expect(kinds(lower)).toEqual(['1row', '2column', '3text', '1text', '1list', '2text', '2text'])
  })
})

describe('the form builder in the editor', () => {
  it('karten7 ac1 takes the blocks away with a change to another form, and says so first', () => {
    const card = open(TREE + 'main: x\n')
    expect(lostByForm(card, 'list').map((one) => one.join('.'))).toEqual(['blocks', 'main'])
    const next = run(card, (doc) => changeForm(doc, 'value'))
    expect(readAt(next, ['blocks'])).toBeUndefined()
    expect(readAt(next, ['main'])).toBeUndefined()
    // A card with no block has nothing to lose.
    expect(lostByForm(open('blocks: []\n'), 'list')).toEqual([])
  })

  it('karten7 ac1 keeps the rows when a card becomes a builder, and takes what only a list has', () => {
    const list = parseCard('nexdeck-card: 1\nslug: x\nname: X\nversion: "1.0.0"\nform: list\nrows: {select: records}\nitem: {title: title}\nempty: nothing\n')
    if (!list.ok) throw new Error('no')
    expect(lostByForm(list.card, 'builder').map((one) => one.join('.'))).toEqual(['item', 'empty'])
    const next = run(list.card, (doc) => changeForm(doc, 'builder'))
    expect(readAt(next, ['rows', 'select'])).toBe('records')
    expect(readAt(next, ['item'])).toBeUndefined()
    expect(readAt(next, ['form'])).toBe('builder')
  })

  it('karten7 ac1 sends a builder card to All settings even before it has a block', () => {
    expect(refusalOf(open(''))).toBe('parts')
    expect(refusalOf(open(TREE))).toBe('parts')
  })

  it('karten7 ac1 shows every setting of a block and names the ones it has not', () => {
    const card = open('blocks:\n  - {type: value, id: a, path: x, format: number, size: l, color: red, rules: [{op: ">", than: 1, then: warn}]}\n  - {type: divider, glow: 1}\n  - type: row\n    children: [{type: text, text: a, bad: 1}]\n')
    expect(adjustedInYaml(card, EDITOR_SHOWS).map((one) => one.path.join('.'))).toEqual(['blocks.1.glow', 'blocks.2.children.0.bad'])
  })
})
