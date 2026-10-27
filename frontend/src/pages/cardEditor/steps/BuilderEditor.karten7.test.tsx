/**
 * The builder in the Look step (KARTEN-7): the twelve blocks in four groups, the tree of the card, the settings of the
 * block chosen, all written into the card's own `blocks:`. Tapping adds under the chosen block, the arrows move, taking
 * out a block with blocks inside says how many go, the most there may be, the main value, and the warning when the
 * content does not fit.
 */
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18next from 'i18next'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { readAt } from '../../../lib/cardDocument'
import { editor, openCard, prepare, stub } from '../../../test/cardEditor'
import { SONARR_QUEUE } from '../../../test/probeAnswers'
import { useFit } from '../fit'

const BUILDER = `nexdeck-card: 1
slug: queue
name: Queue
version: "1.0.0"
requires: [sonarr]
requests:
  - id: queue
    path: /api/v3/queue
form: builder
main: total
rows: {select: records}
# the blocks
blocks:
  - type: row
    gap: m
    children:
      - {type: symbol, icon: server, color: accent}
      - {type: text, text: Queue, weight: bold}
  - {type: value, id: total, label: Total, path: totalRecords, format: number}
  - {type: divider}
  - type: list
    item:
      - {type: text, value: {path: title}}
buttons:
  - {id: all, label: All, where: card, method: POST, path: /all}
  - {id: one, label: One, where: row, method: POST, path: "/one/{id}"}
`

const SMALL = `nexdeck-card: 1
slug: queue
name: Queue
version: "1.0.0"
requires: [sonarr]
requests:
  - id: queue
    path: /api/v3/queue
form: builder
blocks:
  - {type: text, text: First}
  - {type: text, text: Second}
  - {type: text, text: Third}
`

const VALUE = `nexdeck-card: 1
slug: queue
name: Queue
version: "1.0.0"
requires: [sonarr]
requests:
  - id: queue
    path: /api/v3/queue
form: value
value: totalRecords
`

beforeEach(() => {
  prepare()
  useFit.setState({ overflowing: false })
})

afterEach(async () => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  await i18next.changeLanguage('en')
})

async function builder(text = BUILDER) {
  stub(text, { 'POST /cards/probe': { status: 200, body: SONARR_QUEUE } })
  await openCard('Queue')
  await userEvent.click(screen.getAllByRole('button', { name: /^2 [^×]/ })[0])
  await screen.findByTestId('card-builder')
}

const blocks = () => readAt(editor().card!, ['blocks']) as Record<string, unknown>[]
const node = (path: string) => document.querySelector<HTMLElement>(`[data-node="${path}"]`)!

const palette = () => within(screen.getByRole('group', { name: 'Blocks' }))

describe('the builder', () => {
  it('karten7 ac1 offers twelve blocks in four groups, each with its own settings', async () => {
    await builder()
    const groups = within(screen.getByRole('group', { name: 'Blocks' })).getAllByRole('heading', { level: 3 })
    expect(groups.map((one) => one.textContent)).toEqual(['Layout', 'Content', 'Data', 'Action'])
    expect(
      palette()
        .getAllByRole('button')
        .map((one) => one.textContent),
    ).toEqual(['Row', 'Column', 'Divider', 'Text', 'Value', 'Badge', 'Symbol', 'Image', 'Progress', 'Sparkline', 'List', 'Button'])
    // A block of each kind has its own settings: a row its space and alignment, a symbol its name, a list its rows.
    await userEvent.click(node('blocks[0]'))
    expect(screen.getByLabelText('Space between')).toBeInTheDocument()
    expect(screen.getByLabelText('Alignment')).toBeInTheDocument()
    await userEvent.click(node('blocks[0].children[0]'))
    expect(screen.getByLabelText('Symbol')).toHaveValue('server')
    await userEvent.click(node('blocks[3]'))
    expect(screen.getByLabelText('Rows from')).toHaveValue('records')
  })

  it('karten7 ac1 is a form of the Look step, and a change to it asks what it takes away', async () => {
    stub(VALUE, { 'POST /cards/probe': { status: 200, body: SONARR_QUEUE } })
    await openCard('Queue')
    await userEvent.click(screen.getAllByRole('button', { name: /^2 [^×]/ })[0])
    await userEvent.click(screen.getByRole('button', { name: 'Builder' }))
    await userEvent.click(await screen.findByRole('button', { name: 'Change form' }))
    expect(readAt(editor().card!, ['form'])).toBe('builder')
    expect(readAt(editor().card!, ['value'])).toBeUndefined()
    expect(await screen.findByTestId('card-builder')).toBeInTheDocument()
    // And back: the blocks go, after a question.
    await userEvent.click(palette().getByRole('button', { name: 'Divider' }))
    await userEvent.click(screen.getByRole('button', { name: 'A number' }))
    expect(await screen.findByRole('dialog')).toHaveTextContent('blocks')
    await userEvent.click(screen.getByRole('button', { name: 'Change form' }))
    expect(readAt(editor().card!, ['form'])).toBe('value')
    expect(readAt(editor().card!, ['blocks'])).toBeUndefined()
  })

  it('karten7 ac1 shows the parts of a block it has fields for, and names the ones it has not', async () => {
    await builder(BUILDER.replace('{type: divider}', '{type: divider, shadow: deep}'))
    expect(screen.getByTestId('card-adjusted')).toHaveTextContent('blocks[2].shadow')
    expect(screen.getByTestId('card-adjusted')).not.toHaveTextContent('blocks[0]')
  })

  it('karten7 ec4 adds a block under the chosen one, into a row and behind any other', async () => {
    await builder()
    // Nothing chosen: at the end of the card.
    await userEvent.click(palette().getByRole('button', { name: 'Badge' }))
    expect(blocks().map((one) => one.type)).toEqual(['row', 'value', 'divider', 'list', 'badge'])
    // A block that is not a container: behind it.
    await userEvent.click(node('blocks[1]'))
    await userEvent.click(palette().getByRole('button', { name: 'Divider' }))
    expect(blocks().map((one) => one.type)).toEqual(['row', 'value', 'divider', 'divider', 'list', 'badge'])
    // A row: into it, at its end.
    await userEvent.click(node('blocks[0]'))
    await userEvent.click(palette().getByRole('button', { name: 'Symbol' }))
    expect((blocks()[0].children as Record<string, unknown>[]).map((one) => one.type)).toEqual(['symbol', 'text', 'symbol'])
    // The new block is the chosen one, ready for the next.
    expect(node('blocks[0].children[2]')).toHaveAttribute('aria-selected', 'true')
  })

  it('karten7 ec4 keeps the comments of the card when a block is added', async () => {
    await builder()
    await userEvent.click(palette().getByRole('button', { name: 'Divider' }))
    expect(editor().text).toContain('# the blocks')
  })

  it('karten7 ec4 does not put a list into the template of a list', async () => {
    await builder()
    await userEvent.click(node('blocks[3]'))
    expect(palette().getByRole('button', { name: 'List' })).toBeDisabled()
    expect(palette().getByRole('button', { name: 'Text' })).toBeEnabled()
  })

  it('karten7 ec4 moves a block with the buttons, and out of its row at the end', async () => {
    await builder(SMALL)
    await userEvent.click(node('blocks[0]'))
    await userEvent.click(screen.getByRole('button', { name: 'Move down' }))
    expect(blocks().map((one) => one.text)).toEqual(['Second', 'First', 'Third'])
    // The block that moved stays chosen.
    expect(node('blocks[1]')).toHaveAttribute('aria-selected', 'true')
    await userEvent.click(screen.getByRole('button', { name: 'Move up' }))
    await userEvent.click(screen.getByRole('button', { name: 'Move up' }))
    expect(blocks().map((one) => one.text)).toEqual(['First', 'Second', 'Third'])
  })

  it('karten7 ec4 reaches every place with the two arrows: out of a row to before it and after it', async () => {
    await builder()
    // The text in the row is the last one in it: down takes it behind the row.
    await userEvent.click(node('blocks[0].children[1]'))
    await userEvent.click(screen.getByRole('button', { name: 'Move down' }))
    expect(blocks().map((one) => one.type)).toEqual(['row', 'text', 'value', 'divider', 'list'])
    expect(blocks()[0].children).toHaveLength(1)
    // Up passes the row, and then it stands in front of it.
    await userEvent.click(screen.getByRole('button', { name: 'Move up' }))
    expect(blocks().map((one) => one.type)).toEqual(['text', 'row', 'value', 'divider', 'list'])
    // The first one in the row goes up out of it, in front of the row.
    await userEvent.click(node('blocks[1].children[0]'))
    await userEvent.click(screen.getByRole('button', { name: 'Move up' }))
    expect(blocks().map((one) => one.type)).toEqual(['text', 'symbol', 'row', 'value', 'divider', 'list'])
    expect(blocks()[2].children).toHaveLength(0)
  })

  it('karten7 ec5 chooses blocks with Tab and moves them with the arrow keys, from the keyboard only', async () => {
    await builder(SMALL)
    const first = node('blocks[0]')
    first.focus()
    await userEvent.keyboard('{Enter}')
    expect(first).toHaveAttribute('aria-selected', 'true')
    await userEvent.tab()
    expect(document.activeElement).toBe(node('blocks[1]'))
    await userEvent.keyboard('{Enter}')
    expect(node('blocks[1]')).toHaveAttribute('aria-selected', 'true')
    await userEvent.keyboard('{ArrowUp}')
    expect(blocks().map((one) => one.text)).toEqual(['Second', 'First', 'Third'])
    // The focus went with the block, so the next arrow acts on it again.
    expect(document.activeElement).toBe(node('blocks[0]'))
    await userEvent.keyboard('{ArrowDown}{ArrowDown}')
    expect(blocks().map((one) => one.text)).toEqual(['First', 'Third', 'Second'])
    expect(document.activeElement).toBe(node('blocks[2]'))
  })

  it('karten7 ec6 names how many blocks go with a block that holds others, and takes them all out when confirmed', async () => {
    await builder()
    await userEvent.click(node('blocks[0]'))
    await userEvent.click(screen.getByRole('button', { name: 'Remove' }))
    const dialog = await screen.findByRole('dialog')
    expect(dialog).toHaveTextContent('Removes 3 blocks')
    // Cancelled: nothing went.
    await userEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(blocks()).toHaveLength(4)
    await userEvent.click(screen.getByRole('button', { name: 'Remove' }))
    await userEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Remove' }))
    expect(blocks().map((one) => one.type)).toEqual(['value', 'divider', 'list'])
  })

  it('karten7 ec6 asks nothing for a block with nothing inside', async () => {
    await builder()
    await userEvent.click(node('blocks[2]'))
    await userEvent.click(screen.getByRole('button', { name: 'Remove' }))
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(blocks().map((one) => one.type)).toEqual(['row', 'value', 'list'])
  })

  it('karten7 ec6 counts a list with its template', async () => {
    await builder()
    await userEvent.click(node('blocks[3]'))
    await userEvent.click(screen.getByRole('button', { name: 'Remove' }))
    expect(await screen.findByRole('dialog')).toHaveTextContent('Removes 2 blocks')
  })

  it('karten7 ac5 counts the blocks and stops adding at one hundred', async () => {
    await builder(SMALL)
    expect(screen.getByTestId('card-builder-count')).toHaveTextContent('3 of 100 blocks')
    const lots = SMALL.replace(/blocks:[\s\S]*$/, 'blocks:\n' + '  - {type: divider}\n'.repeat(99))
    editor().setText(lots)
    await waitFor(() => expect(screen.getByTestId('card-builder-count')).toHaveTextContent('99 of 100 blocks'))
    await userEvent.click(palette().getByRole('button', { name: 'Divider' }))
    expect(screen.getByTestId('card-builder-count')).toHaveTextContent('100 of 100 blocks')
    expect(palette().getByRole('button', { name: 'Divider' })).toBeDisabled()
    expect(palette().getByRole('button', { name: 'Row' })).toBeDisabled()
    expect(screen.getByText('A card has at most 100 blocks.')).toBeInTheDocument()
    expect(blocks()).toHaveLength(100)
  })

  it('karten7 ac5 counts the blocks inside rows and lists too', async () => {
    await builder()
    expect(screen.getByTestId('card-builder-count')).toHaveTextContent('7 of 100 blocks')
  })

  it('karten7 ac3 chooses colour, size and space from fixed steps only', async () => {
    await builder()
    await userEvent.click(node('blocks[0].children[0]'))
    const settings = within(screen.getByTestId('card-block-blocks[0].children[0]'))
    const colour = settings.getByLabelText('Colour')
    expect(within(colour).getAllByRole('option').map((one) => one.getAttribute('value'))).toEqual(['text', 'accent', 'green', 'yellow', 'red', 'muted', 'blue', 'violet', 'pink', 'orange'])
    await userEvent.selectOptions(colour, 'red')
    expect((blocks()[0].children as Record<string, unknown>[])[0].color).toBe('red')
    expect(within(settings.getByLabelText('Size')).getAllByRole('option').map((one) => one.getAttribute('value'))).toEqual(['xs', 's', 'm', 'l', 'xl'])
    await userEvent.click(node('blocks[0]'))
    const row = within(screen.getByTestId('card-block-blocks[0]'))
    expect(within(row.getByLabelText('Space between')).getAllByRole('option').map((one) => one.getAttribute('value'))).toEqual(['none', 's', 'm', 'l'])
    await userEvent.selectOptions(row.getByLabelText('Alignment'), 'between')
    expect(blocks()[0].align).toBe('between')
  })

  it('karten7 ac1 writes the settings of a block into the card and keeps the other blocks and the comments', async () => {
    await builder()
    await userEvent.click(node('blocks[1]'))
    const path = within(screen.getByTestId('card-block-blocks[1]')).getByLabelText('Field')
    await userEvent.clear(path)
    await userEvent.type(path, 'records.size')
    expect(blocks()[1]).toMatchObject({ type: 'value', id: 'total', path: 'records.size', format: 'number' })
    expect(blocks()).toHaveLength(4)
    expect(editor().text).toContain('# the blocks')
  })

  it('karten7 ac1 shows a fixed text or a value of the data for a text, and turns one into the other', async () => {
    await builder()
    await userEvent.click(node('blocks[0].children[1]'))
    expect(screen.getByLabelText('Shows')).toHaveValue('text')
    expect(screen.getByLabelText('Text, English (required)')).toHaveValue('Queue')
    await userEvent.selectOptions(screen.getByLabelText('Shows'), 'value')
    const text = (blocks()[0].children as Record<string, unknown>[])[1]
    expect(text.text).toBeUndefined()
    expect(text.value).toEqual({ path: '@' })
  })

  it('karten7 ac1 takes a button of the card for a block, and a button of each row inside a list', async () => {
    await builder(BUILDER.replace('children: []', 'children: []') + '')
    await userEvent.click(palette().getByRole('button', { name: 'Button' }))
    const select = within(screen.getByTestId('card-block-blocks[4]')).getByLabelText(/^Button/)
    expect(within(select).getAllByRole('option').map((one) => one.getAttribute('value'))).toEqual(['all'])
    await userEvent.click(node('blocks[3]'))
    await userEvent.click(palette().getByRole('button', { name: 'Button' }))
    const inList = within(screen.getByTestId('card-block-blocks[3].item[1]')).getByLabelText(/^Button/)
    expect(within(inList).getAllByRole('option').map((one) => one.getAttribute('value'))).toEqual(['one'])
  })

  it('karten7 ac1 offers no button block while the card has no buttons', async () => {
    await builder(SMALL)
    expect(palette().getByRole('button', { name: 'Button' })).toBeDisabled()
  })
})

describe('the main value', () => {
  it('karten7 ac8 offers only the value blocks that have a short name, and writes the choice', async () => {
    await builder(BUILDER.replace('main: total\n', '').replace('{type: divider}', '{type: value, id: second, path: x}').replace('- {type: text, value: {path: title}}', '- {type: value, path: title}'))
    const main = within(screen.getByTestId('card-builder-main')).getByLabelText('Main value for key figures')
    expect(within(main).getAllByRole('option').map((one) => one.textContent)).toEqual(['None', 'total', 'second'])
    await userEvent.selectOptions(main, 'second')
    expect(readAt(editor().card!, ['main'])).toBe('second')
    await userEvent.selectOptions(main, '')
    expect(readAt(editor().card!, ['main'])).toBeUndefined()
  })

  it('karten7 ac8 follows the short name of the main value, and lets go of it when the block goes', async () => {
    await builder()
    await userEvent.click(node('blocks[1]'))
    const id = within(screen.getByTestId('card-block-blocks[1]')).getByLabelText('Short name (id)')
    await userEvent.clear(id)
    await userEvent.type(id, 'sum')
    await userEvent.tab()
    expect(readAt(editor().card!, ['main'])).toBe('sum')
    await userEvent.click(screen.getByRole('button', { name: 'Remove' }))
    expect(readAt(editor().card!, ['main'])).toBeUndefined()
  })

  it('karten7 ac8 says how to get a main value when no value block has a short name', async () => {
    await builder(SMALL)
    expect(screen.getByTestId('card-builder-main')).toHaveTextContent('Give a value block a short name (id)')
  })
})

describe('dragging', () => {
  function transfer() {
    const data = new Map<string, string>()
    return {
      setData: (type: string, value: string) => void data.set(type, value),
      getData: (type: string) => data.get(type) ?? '',
      get types() {
        return [...data.keys()]
      },
      effectAllowed: 'all',
      dropEffect: 'none',
    }
  }

  it('karten7 ec4 drops a block in front of another, and into a row on a computer', async () => {
    await builder(SMALL.replace('blocks:', 'blocks:\n  - {type: row, children: []}'))
    const dataTransfer = transfer()
    fireEvent.dragStart(node('blocks[3]'), { dataTransfer })
    fireEvent.dragOver(node('blocks[0]'), { dataTransfer })
    fireEvent.drop(node('blocks[0]'), { dataTransfer })
    expect((blocks()[0].children as Record<string, unknown>[]).map((one) => one.text)).toEqual(['Third'])
    expect(blocks().map((one) => one.type)).toEqual(['row', 'text', 'text'])
  })

  it('karten7 ec4 drops a new block from the list onto the tree', async () => {
    await builder(SMALL)
    const dataTransfer = transfer()
    fireEvent.dragStart(palette().getByRole('button', { name: 'Divider' }), { dataTransfer })
    fireEvent.drop(node('blocks[1]'), { dataTransfer })
    expect(blocks().map((one) => one.type)).toEqual(['text', 'text', 'divider', 'text'])
  })

  it('karten7 ec4 does not drop a block into itself', async () => {
    await builder()
    const dataTransfer = transfer()
    fireEvent.dragStart(node('blocks[0]'), { dataTransfer })
    fireEvent.drop(node('blocks[0].children[1]'), { dataTransfer })
    expect(blocks().map((one) => one.type)).toEqual(['row', 'value', 'divider', 'list'])
    expect(blocks()[0].children).toHaveLength(2)
  })
})

describe('the guided way and the preview', () => {
  it('karten7 ac1 opens a builder card in All settings, with the reason, and the guided way points there', async () => {
    stub(BUILDER, {})
    await openCard('Queue', 'guided')
    expect(editor().view).toBe('editor')
    expect(editor().refusal).toBe('parts')
  })

  it('karten7 ac1 shows in the guided way one line: free layout, in All settings', async () => {
    stub(VALUE, { 'POST /cards/probe': { status: 200, body: SONARR_QUEUE } })
    await openCard('Queue', 'guided')
    editor().setGuidedStep('display')
    await userEvent.click(await screen.findByRole('button', { name: 'Free layout: in All settings' }))
    expect(editor().view).toBe('editor')
    expect(editor().step).toBe('look')
  })

  it('karten7 ac7 warns when the preview says that the content does not fit the card, and not otherwise', async () => {
    vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockReturnValue(400)
    vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(100)
    stub(SMALL, {
      'POST /cards/preview': {
        status: 200,
        body: { status: 'ok', meta: { custom: true, renderer: 'builder', blocks: [{ type: 'text', value: { text: 'First' }, size: 'm', weight: 'normal', color: 'text' }] } },
      },
    })
    await openCard('Queue')
    await userEvent.click(screen.getAllByRole('button', { name: /^2 [^×]/ })[0])
    expect(await screen.findByTestId('card-builder-overflow', undefined, { timeout: 3000 })).toHaveTextContent('larger than the card')
    // The blocks fit: the warning goes.
    vi.restoreAllMocks()
    vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockReturnValue(100)
    vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(100)
    useFit.getState().report(false)
    await waitFor(() => expect(screen.queryByTestId('card-builder-overflow')).toBeNull())
  })

  it('karten7 ac7 says nothing while the content fits', async () => {
    await builder(SMALL)
    expect(screen.queryByTestId('card-builder-overflow')).toBeNull()
    useFit.getState().report(true)
    expect(await screen.findByTestId('card-builder-overflow')).toBeInTheDocument()
  })
})

describe('the words of the blocks', () => {
  it('karten7 ac6 puts a fixed text into the Texts step, in every language the card is written in', async () => {
    stub(SMALL.replace('text: First', 'text: {en: First, de: Erster}'), {})
    await openCard('Queue')
    await userEvent.click(screen.getByRole('button', { name: '5 Texts' }))
    const field = await screen.findByLabelText(/Block 1: text, German|Block 1: text, Deutsch/)
    expect(field).toHaveValue('Erster')
  })

  it('karten7 ac6 has the words of the builder in every language', async () => {
    await i18next.changeLanguage('de')
    await builder(SMALL)
    expect(screen.getByRole('group', { name: 'Bausteine' })).toBeInTheDocument()
    expect(screen.getByTestId('card-builder-count')).toHaveTextContent('3 von 100 Bausteinen')
  })
})
