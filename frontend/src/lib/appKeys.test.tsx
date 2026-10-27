/**
 * Number keys for app tiles: a digit opens its tile as the click would, ?
 * shows the keys, and neither does anything where a key means something
 * else: in a field, over a dialog, with Ctrl, Alt or Meta, while arranging.
 */
import { act, fireEvent, render, screen } from '@testing-library/react'
import i18next from 'i18next'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '../api/client'
import { setLanguage } from '../i18n/index'
import { AppTile } from '../components/renderers'
import { copyNotes } from './copying'
import { appTarget, failureText, keyOf, leave, useAppKeys, useKeyMarks } from './appKeys'
import type { WidgetData, WidgetView } from './types'

function tile(id: number, key: string, extra: Partial<WidgetView> = {}): WidgetView {
  return {
    id, kind: 'core.app', title: `Tile ${id}`, icon: '', link: `https://tile${id}.example.com`, renderer: 'app',
    options: { key }, integration_id: null, refresh_seconds: null, ...extra,
  } as unknown as WidgetView
}

describe('a tile and its key', () => {
  it('is a digit from one to nine on an app tile, nothing else', () => {
    expect(keyOf(tile(1, '3'))).toBe('3')
    expect(keyOf(tile(1, ''))).toBe('')
    expect(keyOf(tile(1, '0'))).toBe('')
    expect(keyOf({ ...tile(1, '3'), kind: 'core.clock' })).toBe('')
  })

  it('leads where the click leads, in a tab of its own unless the tile says otherwise', () => {
    expect(appTarget(tile(1, '1'), { link: 'https://other.example.com' } as WidgetData)).toEqual({ href: 'https://tile1.example.com', newTab: true })
    expect(appTarget(tile(1, '1', { link: '', service_link: 'http://192.0.2.4:8989' }), undefined).href).toBe('http://192.0.2.4:8989')
    expect(appTarget(tile(1, '1'), { meta: { open_new_tab: false } } as unknown as WidgetData).newTab).toBe(false)
    expect(appTarget(tile(1, '1', { link: 'javascript:alert(1)' }), undefined).href).toBeUndefined()
  })
})

function Board({ enabled, tiles, data = {} }: { enabled: boolean; tiles: WidgetView[]; data?: Record<number, WidgetData> }) {
  useAppKeys(enabled, tiles, data)
  return <input aria-label="Search" />
}

describe('on the board', () => {
  const opened = vi.fn()
  const left = vi.fn()
  const goes = leave.to
  beforeEach(() => {
    opened.mockReset()
    left.mockReset()
    vi.stubGlobal('open', opened)
    leave.to = left
    act(() => useKeyMarks.getState().set(false))
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    leave.to = goes
    document.body.innerHTML = ''
  })

  it('opens the tile of a digit, in a new tab or in this one as its click would', () => {
    render(<Board enabled tiles={[tile(1, '1'), tile(2, '2', { options: { key: '2', open_new_tab: false } }), tile(3, '')]} data={{ 2: { meta: { open_new_tab: false } } as unknown as WidgetData }} />)
    fireEvent.keyDown(window, { key: '1' })
    expect(opened).toHaveBeenCalledWith('https://tile1.example.com', '_blank', 'noopener,noreferrer')
    fireEvent.keyDown(window, { key: '2' })
    expect(left).toHaveBeenCalledWith('https://tile2.example.com')
    fireEvent.keyDown(window, { key: '3' })
    expect(opened).toHaveBeenCalledTimes(1)
  })

  it('leaves a digit alone in a field, over a dialog, with Ctrl, Alt or Meta, and while switched off', () => {
    const view = render(<Board enabled tiles={[tile(1, '1')]} />)
    fireEvent.keyDown(screen.getByRole('textbox', { name: 'Search' }), { key: '1' })
    for (const modifier of ['ctrlKey', 'altKey', 'metaKey']) fireEvent.keyDown(window, { key: '1', [modifier]: true })
    const dialog = document.createElement('div')
    dialog.setAttribute('role', 'dialog')
    document.body.appendChild(dialog)
    fireEvent.keyDown(window, { key: '1' })
    dialog.remove()
    view.rerender(<Board enabled={false} tiles={[tile(1, '1')]} />)
    fireEvent.keyDown(window, { key: '1' })
    expect(opened).not.toHaveBeenCalled()
    // Shift is no modifier here: on some keyboards the digits need it.
    view.rerender(<Board enabled tiles={[tile(1, '1')]} />)
    fireEvent.keyDown(window, { key: '1', shiftKey: true })
    expect(opened).toHaveBeenCalledTimes(1)
  })

  it('shows the keys on the tiles with ?, hides them with ? again, and forgets them on leaving', () => {
    const tiles = [tile(1, '1'), tile(2, '')]
    const view = render(
      <>
        <Board enabled tiles={tiles} />
        <AppTile widget={tiles[0]} data={undefined} />
        <AppTile widget={tiles[1]} data={undefined} />
      </>,
    )
    expect(screen.queryByTestId('key-mark')).toBeNull()
    expect(screen.getAllByRole('link')[0].getAttribute('aria-keyshortcuts')).toBe('1')
    fireEvent.keyDown(window, { key: '?', shiftKey: true })
    expect(screen.getAllByTestId('key-mark').map((mark) => mark.textContent)).toEqual(['1'])
    fireEvent.keyDown(window, { key: '?', shiftKey: true })
    expect(screen.queryByTestId('key-mark')).toBeNull()
    fireEvent.keyDown(window, { key: '?', shiftKey: true })
    // Arranging the board, the keys do nothing, and their marks step aside.
    view.rerender(
      <>
        <Board enabled={false} tiles={tiles} />
        <AppTile widget={tiles[0]} data={undefined} editing />
      </>,
    )
    expect(screen.queryByTestId('key-mark')).toBeNull()
    view.unmount()
    expect(useKeyMarks.getState().shown).toBe(false)
  })
})

describe('what the board says', () => {
  it('names the tile that has the key, in the reader’s language', async () => {
    await setLanguage('de')
    const refused = new ApiError(400, 'key_taken', 'Key 3 already opens Wiki on this board.', undefined, { key: '3', name: 'Wiki' })
    expect(failureText(refused, i18next.t)).toBe('Die Taste 3 öffnet auf diesem Board schon Wiki. Jede Taste öffnet eine Kachel; wähl eine andere oder keine.')
    expect(failureText(new ApiError(400, 'other', 'Something else.'), i18next.t)).toBe('Something else.')
    expect(copyNotes([{ code: 'key_dropped', name: 'Wiki', key: '3' }], i18next.t)).toEqual(['Die Kopie von Wiki hat keine Taste, denn 3 öffnet auf dem Board schon eine Kachel.'])
    await setLanguage('en')
  })
})
