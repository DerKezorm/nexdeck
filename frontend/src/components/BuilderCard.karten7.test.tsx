/**
 * What a card put together from blocks draws (KARTEN-7): the tree the server sends, arranged in rows and columns, in
 * fixed steps and the colours of the theme, empty where there is no value, cut where it does not fit.
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { DEMO_VIEWS } from '../demo/board'
import backend from '../test/builderBackend.json'
import type { Block } from '../lib/blocks'
import { localizeCustom } from '../lib/customCard'
import type { Action, WidgetData, WidgetView } from '../lib/types'
import { OverflowContext } from './BuilderCard'
import { renderWidget } from './renderers'

const text = (value: string | null, extra: Record<string, unknown> = {}): Block =>
  ({ type: 'text', value: value === null ? null : { text: value }, size: 's', weight: 'normal', color: 'text', ...extra }) as Block

const widget = { ...DEMO_VIEWS[0], id: 41, renderer: 'builder', kind: 'custom.builder' } as WidgetView

function draw(blocks: Block[], extra: { series?: Record<string, number[]>; canAct?: boolean; onAction?: (action: Action) => void; lang?: string } = {}) {
  let data = { status: 'ok', meta: { custom: true, blocks } } as unknown as WidgetData
  if (extra.lang) data = localizeCustom(data, extra.lang) as WidgetData
  return render(<>{renderWidget({ widget, data, series: extra.series, canAct: extra.canAct ?? true, onAction: extra.onAction })}</>)
}

afterEach(() => vi.restoreAllMocks())

describe('a card put together from blocks', () => {
  it('karten7 ac2 arranges blocks in rows and columns', () => {
    draw([
      { type: 'row', gap: 'm', align: 'between', wrap: true, children: [text('Name', { weight: 'bold' }), { type: 'badge', value: { text: 'up' }, color: 'green' }] },
      { type: 'column', gap: 's', children: [text('first'), text('second')] },
    ] as Block[])
    const row = screen.getByText('Name').closest('[data-block="row"]') as HTMLElement
    expect(row.className).toContain('flex-row')
    expect(row.className).toContain('justify-between')
    expect(row.className).toContain('gap-2')
    expect(within(row).getByText('up')).toBeInTheDocument()
    const column = screen.getByText('first').closest('[data-block="column"]') as HTMLElement
    expect(column.className).toContain('flex-col')
    expect(column.className).toContain('gap-1')
    expect(within(column).getByText('second')).toBeInTheDocument()
  })

  it('karten7 ac2 draws a bar, a symbol and the history of a number', () => {
    draw(
      [
        { type: 'progress', value: { text: '40%', number: 40 }, max: 100, color: 'accent' },
        { type: 'symbol', icon: 'server', color: 'accent', size: 'm' },
        { type: 'sparkline', id: 'trend', value: { text: '4', number: 4 }, metric: 'b_trend' },
      ] as Block[],
      { series: { b_trend: [1, 2, 3, 5, 4, 6] } },
    )
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '40')
    expect((screen.getByRole('progressbar').firstElementChild as HTMLElement).style.width).toBe('40%')
    expect(document.querySelector('[data-block="symbol"] svg')).not.toBeNull()
    expect(screen.getByTestId('block-sparkline').querySelector('svg')).not.toBeNull()
  })

  it('karten7 ac3 colours a block with the theme only and reads an unknown name as the text colour', () => {
    draw([
      text('green one', { color: 'green' }),
      text('free one', { color: '#ff00ff' }),
      text('script one', { color: 'red; background: url(x)' }),
      { type: 'value', value: { text: '7', status: 'error' }, size: 'm', color: 'green' },
    ] as Block[])
    expect(screen.getByText('green one')).toHaveStyle({ color: 'var(--nd-ok)' })
    expect(screen.getByText('free one')).toHaveStyle({ color: 'var(--nd-text)' })
    expect(screen.getByText('script one')).toHaveStyle({ color: 'var(--nd-text)' })
    // The status the server set wins over the block's own colour.
    expect(screen.getByText('7')).toHaveStyle({ color: 'var(--nd-bad)' })
  })

  it('karten7 ac3 gives sizes and gaps in fixed steps', () => {
    draw([text('big', { size: 'xl' }), text('small', { size: 'xs' }), { type: 'column', gap: 'l', children: [text('in')] }] as Block[])
    expect(screen.getByText('big').className).toContain('text-2xl')
    expect(screen.getByText('small').className).toContain('text-[11px]')
    expect(screen.getByText('in').closest('[data-block="column"]')!.className).toContain('gap-4')
  })

  it('karten7 ac4 repeats the template for each row, with its own button', async () => {
    const onAction = vi.fn()
    const pause = (id: string): Action => ({ id: 'button:pause', label: 'Pause', params: { id } })
    const rows = ['alpha', 'beta', 'gamma'].map((name) => ({
      blocks: [{ type: 'row', gap: 'm', align: 'between', wrap: true, children: [text(name), { type: 'button', action: pause(name) }] }],
      actions: [pause(name)],
    }))
    draw([{ type: 'list', rows, empty: 'Nothing' }] as Block[], { onAction })
    expect(screen.getAllByRole('listitem')).toHaveLength(3)
    await userEvent.click(within(screen.getByText('beta').closest('li')!).getByRole('button', { name: 'Pause' }))
    expect((onAction.mock.calls[0] as [Action])[0].params).toEqual({ id: 'beta' })
  })

  it('karten7 ac4 says so when a list has no rows', () => {
    draw([{ type: 'list', rows: [], empty: 'Nothing to show' }] as Block[])
    expect(screen.getByText('Nothing to show')).toBeInTheDocument()
  })

  it('karten7 ac6 writes the texts in the language of whoever looks', () => {
    draw([{ type: 'value', label: { en: 'Load', de: 'Last' }, value: { text: '3' }, size: 'm', color: 'text' }, { type: 'list', rows: [], empty: { en: 'Empty', de: 'Leer' } }] as unknown as Block[], { lang: 'de' })
    expect(screen.getByText('Last')).toBeInTheDocument()
    expect(screen.getByText('Leer')).toBeInTheDocument()
  })

  it('karten7 ac6 writes a fixed text in several languages, as the server sends it, in the language of whoever looks', () => {
    const data = backend as unknown as WidgetData
    const german = render(<>{renderWidget({ widget, data: localizeCustom(data, 'de') as WidgetData, canAct: true })}</>)
    expect(screen.getByText('Hallo')).toBeInTheDocument()
    expect(screen.getByText('Fest')).toBeInTheDocument()
    expect(screen.getByText('Plain')).toBeInTheDocument()
    expect(screen.queryByText('Hello')).toBeNull()
    german.unmount()
    // A language the author did not write is English, the way every other text of a card falls back.
    render(<>{renderWidget({ widget, data: localizeCustom(data, 'it') as WidgetData, canAct: true })}</>)
    expect(screen.getByText('Hello')).toBeInTheDocument()
    expect(screen.getByText('Fixed')).toBeInTheDocument()
  })

  it('karten7 ac6 writes numbers, units and times as the server sends them in the language and zone of whoever looks', () => {
    const data = backend as unknown as WidgetData
    const seen = (lang: string, zone: string) =>
      (localizeCustom(data, lang, zone)!.meta!.blocks as Block[]).flatMap((block) => (block.type === 'value' ? [(block.value as { text: string }).text.replace(/[  ]/g, ' ')] : []))
    // The server's own text is English and in its own zone; what the viewer reads follows the viewer.
    expect(seen('de', 'UTC')).toEqual(['1.234.567,89', '4,2 Stück', '12,5 %', '5.0 GB', '27.10.2025, 22:20', '27.10.2025', 'up'])
    expect(seen('en', 'Asia/Tokyo')).toEqual(['1,234,567.89', '4.2 items', '12.5%', '5.0 GB', 'Oct 28, 2025, 7:20 AM', 'Oct 28, 2025', 'up'])
    render(<>{renderWidget({ widget, data: localizeCustom(data, 'de', 'UTC') as WidgetData, canAct: true })}</>)
    expect(screen.getByText('1.234.567,89')).toBeInTheDocument()
  })

  it('karten7 ac6 shows the button of the card in the language of whoever looks, and nothing for a button that is not offered', async () => {
    const onAction = vi.fn()
    const action = { id: 'button:go', label: { en: 'Go', de: 'Los' } } as unknown as Action
    draw([{ type: 'button', action }, { type: 'button', action: null }] as Block[], { onAction, lang: 'de' })
    expect(screen.getAllByRole('button')).toHaveLength(1)
    await userEvent.click(screen.getByRole('button', { name: 'Los' }))
    expect(onAction).toHaveBeenCalledTimes(1)
  })

  it('karten7 ac6 shows no button to somebody who may not act', () => {
    draw([{ type: 'button', action: { id: 'button:go', label: 'Go' } }] as Block[], { canAct: false })
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('karten7 ac7 tells whoever asks that the content is larger than the card, and that it fits when it does', () => {
    const report = vi.fn()
    const data = { status: 'ok', meta: { custom: true, blocks: [text('hello')] } } as unknown as WidgetData
    vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockReturnValue(300)
    vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(100)
    const first = render(<OverflowContext.Provider value={report}>{renderWidget({ widget, data })}</OverflowContext.Provider>)
    expect(report).toHaveBeenLastCalledWith(true)
    first.unmount()
    vi.restoreAllMocks()
    vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockReturnValue(100)
    vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(100)
    report.mockClear()
    render(<OverflowContext.Provider value={report}>{renderWidget({ widget, data })}</OverflowContext.Provider>)
    expect(report).toHaveBeenLastCalledWith(false)
  })

  it('karten7 ac7 cuts what does not fit and lets only the list scroll', () => {
    draw([text('top'), { type: 'list', rows: [{ blocks: [text('row')] }] }] as Block[])
    const card = screen.getByTestId('builder-card')
    expect(card.className).toContain('overflow-hidden')
    expect(screen.getByRole('list').className).toContain('scroll')
    expect(screen.getByText('top').className).toContain('shrink-0')
  })

  it('karten7 ec1 keeps the place of a block without a value, empty', () => {
    draw([
      { type: 'row', gap: 'm', align: 'start', wrap: true, children: [text(null), { type: 'badge', value: null, color: 'green' }] },
      { type: 'value', label: 'CPU', value: null, size: 'm', color: 'text' },
    ] as Block[])
    const row = document.querySelector('[data-block="row"]') as HTMLElement
    // Both blocks are there, each holding a blank, so the rest does not move.
    expect(row.children).toHaveLength(2)
    expect(row.children[0].textContent).toBe(' ')
    expect(row.children[1].textContent).toBe(' ')
    expect(screen.getByText('CPU')).toBeInTheDocument()
    expect(screen.getByTestId('builder-card').textContent).not.toContain('null')
    expect(screen.getByTestId('builder-card').textContent).not.toContain('undefined')
  })

  it('karten7 ec2 cuts a very long text with an ellipsis and keeps the whole of it as the title', () => {
    const long = 'x'.repeat(400)
    draw([text(long)])
    const shown = screen.getByText(long)
    expect(shown.className).toContain('truncate')
    expect(shown.className).toContain('min-w-0')
    expect(shown).toHaveAttribute('title', long)
  })

  it('karten7 ec3 lets the blocks of a row break into lines on a narrow card', () => {
    draw([
      { type: 'row', gap: 's', align: 'start', wrap: true, children: [text('a'), text('b')] },
      { type: 'row', gap: 's', align: 'start', wrap: false, children: [text('c')] },
    ] as Block[])
    const rows = document.querySelectorAll('[data-block="row"]')
    expect(rows[0].className).toContain('flex-wrap')
    expect(rows[0].className).toContain('min-w-0')
    expect(rows[1].className).toContain('flex-nowrap')
  })

  it('karten7 ec7 shows the placeholder for a picture without an address, with a foreign scheme or that does not load', () => {
    draw([
      { type: 'image', src: null, height: 'm' },
      { type: 'image', src: 'javascript:alert(1)', height: 's' },
      { type: 'image', src: 'mailto:someone@example.com', height: 's' },
      { type: 'image', src: 'https://example.com/a.png', height: 'l' },
    ] as Block[])
    expect(screen.getAllByTestId('block-image-placeholder')).toHaveLength(3)
    expect(document.querySelectorAll('img')).toHaveLength(1)
    expect(document.querySelector('img')).toHaveAttribute('src', 'https://example.com/a.png')
  })
})
