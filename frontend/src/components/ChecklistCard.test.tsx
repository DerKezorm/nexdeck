/**
 * The nexnotes cards: a checklist ticked off with a tap, the pinned notes each opening itself, the last state with an
 * orange line while nexnotes cannot be reached, and a picture drawn anew only when what it shows changed.
 */
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import i18next from 'i18next'

import { DEMO_VIEWS } from '../demo/board'
import deScreen from '../i18n/de.json'
import type { Action, WidgetData, WidgetView } from '../lib/types'
import { asOfText, ChecklistCard, drawnAs } from './ChecklistCard'
import { WidgetCard } from './WidgetCard'

const LINK = 'https://notes.example.com/notes/n-shop'
const AS_OF = Date.UTC(2026, 10, 22, 9, 15) / 1000

function view(kind = 'nexnotes.note'): WidgetView {
  return { ...DEMO_VIEWS.find((one) => one.renderer === 'list')!, kind, renderer: 'checklist', title: 'Kitchen', link: '' }
}

function tick(index: number, text: string, checked: boolean): Action {
  return { id: 'check', label: checked ? 'Open again' : 'Tick off', icon: 'check', params: { note: 'n-shop', index, text, checked: !checked } }
}

function note(overrides: Partial<WidgetData['meta']> = {}, withActions = true): WidgetData {
  const rows: [number, string, boolean, number][] = [[0, 'Milk', false, 0], [2, 'Apples', false, 0], [4, 'The dark roast', false, 1], [1, 'Bread', true, 0]]
  return {
    status: 'ok',
    link: LINK,
    items: rows.map(([index, text, checked, depth]) => ({
      id: String(index), title: text, checked, depth, ...(withActions ? { actions: [tick(index, text, checked)] } : {}),
    })),
    meta: { mode: 'note', title: 'Shopping', done: 2, total: 6, more: 2, stamp: 's1', as_of: AS_OF, offline_note: true, ...overrides },
  } as WidgetData
}

async function card(data: WidgetData, more: Partial<Parameters<typeof WidgetCard>[0]> = {}) {
  const utils = render(<WidgetCard widget={view()} data={data} canAct {...more} />)
  await screen.findByTestId(data.meta?.mode === 'pinned' ? 'checklist-pinned' : 'checklist')
  return utils
}

describe('ChecklistCard', () => {
  let opened: string[] = []
  const original = window.open
  beforeEach(() => {
    opened = []
    window.open = ((url: string | URL | undefined) => {
      opened.push(String(url))
      return null
    }) as typeof window.open
  })
  afterEach(async () => {
    window.open = original
    await i18next.changeLanguage('en')
  })

  it('shows the note with its progress, the open items first, and how many more there are', async () => {
    await card(note())
    expect(screen.getByText('Shopping')).toBeInTheDocument()
    expect(screen.getByTestId('checklist-progress')).toHaveTextContent('2 of 6')
    const rows = screen.getAllByRole('listitem')
    expect(rows.map((row) => row.textContent)).toEqual(['Milk', 'Apples', 'The dark roast', 'Bread'])
    expect(rows[2]).toHaveStyle({ paddingLeft: '14px' })
    expect(rows[3]).toHaveAttribute('data-checked', 'true')
    expect(screen.getByTestId('checklist-more')).toHaveTextContent('+2 more')
  })

  it('ticks an item with a tap, shows it ticked at once and does not open the note', async () => {
    const pressed: Action[] = []
    let finish: () => void = () => undefined
    const onAction = (action: Action) => {
      pressed.push(action)
      return new Promise<void>((resolve) => { finish = resolve })
    }
    await card(note(), { onAction })
    const milk = screen.getByRole('button', { name: 'Tick off Milk' })
    expect(milk).toHaveAttribute('aria-pressed', 'false')
    fireEvent.click(milk)
    expect(pressed).toEqual([tick(0, 'Milk', false)])
    expect(opened).toEqual([])
    const now = screen.getByRole('button', { name: 'Open Milk again' })
    expect(now).toHaveAttribute('aria-pressed', 'true')
    expect(now).toBeDisabled()
    fireEvent.click(now)
    expect(pressed).toHaveLength(1)
    await act(async () => finish())
  })

  it('opens the note from the title and the free space, never from an item', async () => {
    await card(note(), { onAction: () => undefined, widget: { ...view(), link: '' } })
    fireEvent.click(screen.getByText('Shopping'))
    expect(opened).toEqual([LINK])
  })

  it('offers no ticking without the right to act or without the item allowing it, and says why', async () => {
    const { unmount } = await card(note(), { canAct: false, onAction: () => undefined })
    expect(screen.queryAllByRole('button', { name: /Tick off|again/ })).toEqual([])
    unmount()
    await card(note({ check_note: 'Read only: ticking off needs an API token with Read and write.' }, false), { onAction: () => undefined })
    expect(screen.queryAllByRole('button', { name: /Tick off|again/ })).toEqual([])
    expect(screen.getByTestId('checklist-note')).toHaveTextContent('Read only: ticking off needs an API token with Read and write.')
  })

  it('keeps the last state with an orange line while nexnotes cannot be reached, and lets nothing be ticked', async () => {
    const offline = { ...note({ offline: true, code: 'unreachable' }), error: 'The service could not be reached.', status: 'unknown' } as WidgetData
    await card(offline, { onAction: () => undefined })
    expect(screen.queryByTestId('card-error')).toBeNull()
    expect(screen.getByRole('img', { name: /^Warning/ })).toHaveAttribute('data-status', 'warn')
    expect(screen.getAllByRole('listitem')).toHaveLength(4)
    expect(screen.queryAllByRole('button', { name: /Tick off|again/ })).toEqual([])
    expect(screen.getByTestId('checklist-offline')).toHaveTextContent(`nexnotes cannot be reached right now · as of ${asOfText(AS_OF, 'en')}`)
  })

  it('covers any other failure in red as every card does', async () => {
    render(<WidgetCard widget={view()} data={{ status: 'unknown', error: 'This note is locked in the vault; the card shows nothing of it.', meta: { code: 'note_locked' } } as WidgetData} canAct />)
    expect(await screen.findByTestId('card-error')).toHaveTextContent('This note is locked in the vault')
  })

  it('names an untitled note and shows the first lines of a note without a checklist', async () => {
    await card({ status: 'ok', items: [], meta: { mode: 'note', title: '', lines: ['The password is on the fridge.'], stamp: 's', empty: 'This note is empty.' } } as WidgetData)
    expect(screen.getByText('Untitled note')).toBeInTheDocument()
    expect(screen.getByTestId('checklist-lines')).toHaveTextContent('The password is on the fridge.')
  })

  it('lists the pinned notes, each opening itself, with progress and whose it is', async () => {
    const pinned = {
      status: 'ok', link: 'https://notes.example.com',
      items: [
        { id: 'n-shop', title: 'Shopping', subtitle: 'Milk', url: LINK, done: 2, total: 6 },
        { id: 'n-trip', title: 'Packing', subtitle: 'Passports', url: 'https://notes.example.com/notes/n-trip', done: 1, total: 2, owner: 'Sam' },
        { id: 'n-wifi', title: '', subtitle: 'The password is on the fridge.', url: 'javascript:alert(1)' },
      ],
      meta: { mode: 'pinned', more: 3, stamp: 'p', as_of: AS_OF },
    } as WidgetData
    await card(pinned)
    const links = screen.getAllByRole('link').filter((link) => link.closest('[data-testid="checklist-pinned"]'))
    expect(links.map((link) => link.getAttribute('href'))).toEqual([LINK, 'https://notes.example.com/notes/n-trip'])
    const trip = within(links[1])
    expect(trip.getByText('Passports · from Sam')).toBeInTheDocument()
    expect(trip.getByTestId('checklist-progress')).toHaveTextContent('1/2')
    expect(trip.getByTestId('checklist-progress')).toHaveAttribute('title', '1 of 2')
    expect(screen.getByText('Untitled note')).toBeInTheDocument()
    expect(screen.getByTestId('checklist-more')).toHaveTextContent('+3 more')
  })

  it('speaks German', async () => {
    i18next.addResourceBundle('de', 'translation', deScreen, true, true)
    await i18next.changeLanguage('de')
    await card({ ...note({ offline: true }), error: 'down' } as WidgetData)
    expect(screen.getByTestId('checklist-progress')).toHaveTextContent('2 von 6')
    expect(screen.getByTestId('checklist-more')).toHaveTextContent('+2 weitere')
    expect(screen.getByTestId('checklist-offline')).toHaveTextContent('nexnotes gerade nicht erreichbar · Stand von')
  })
})

describe('drawing anew', () => {
  it('draws the same picture for the same answer and a new one when an item changed', () => {
    const props = { widget: view(), data: note(), canAct: true }
    expect(drawnAs(props)).toBe(drawnAs({ ...props, data: note() }))
    const ticked = note()
    ticked.items = [{ ...ticked.items![0], checked: true }, ...ticked.items!.slice(1)]
    expect(drawnAs({ ...props, data: ticked })).not.toBe(drawnAs(props))
    expect(drawnAs({ ...props, data: note({ stamp: 's2' }) })).not.toBe(drawnAs(props))
    expect(drawnAs({ ...props, canAct: false })).not.toBe(drawnAs(props))
  })

  it('keeps a tap drawn through an answer with the same stamp and lets the next stamp say how it is', async () => {
    const onAction = () => new Promise<void>(() => undefined)
    const { rerender } = render(<ChecklistCard widget={view()} data={note()} canAct onAction={onAction} />)
    fireEvent.click(screen.getByRole('button', { name: 'Tick off Milk' }))
    rerender(<ChecklistCard widget={view()} data={note()} canAct onAction={onAction} />)
    expect(screen.getByRole('button', { name: 'Open Milk again' })).toHaveAttribute('aria-pressed', 'true')
    rerender(<ChecklistCard widget={view()} data={note({ stamp: 's2' })} canAct onAction={onAction} />)
    expect(screen.getByRole('button', { name: 'Tick off Milk' })).toHaveAttribute('aria-pressed', 'false')
  })
})
