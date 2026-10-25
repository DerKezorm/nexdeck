/**
 * Custom cards on the screen (KARTEN-6, KARTEN-1 AC-5, AC-6, AC-11): the four forms drawn with the renderers every card
 * uses, the texts of the author out of the table of translations, pictures that fail, links that are only links,
 * and the keyboard.
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18next from 'i18next'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { DEMO_VIEWS } from '../demo/board'
import deScreen from '../i18n/de.json'
import de from '../i18n/texts.de.json'
import { registerTexts, type TextBundle } from '../i18n/texts'
import { PageCardsContext } from '../lib/groups'
import { forgetGivenNames, useShowcase } from '../lib/showcase'
import type { WidgetData, WidgetView } from '../lib/types'
import { useLive } from '../stores/live'
import { FiguresCard } from './FiguresCard'
import { renderWidget } from './renderers'
import { WidgetCard } from './WidgetCard'

const view = (kind: string, renderer: string, extra: Partial<WidgetView> = {}): WidgetView => ({ ...DEMO_VIEWS[0], id: 41, kind, renderer, title: 'Queue', options: {}, link: '', ...extra }) as WidgetView
const custom = (extra: Partial<WidgetData>): WidgetData => ({ status: 'ok', meta: { custom: true }, ...extra }) as WidgetData
const draw = (widget: WidgetView, data: WidgetData) => render(<MemoryRouter>{renderWidget({ widget, data })}</MemoryRouter>)

const NUMBER = (extra: Record<string, unknown> = {}) =>
  custom({ primary: { label: { en: 'Queue', de: 'Warteschlange' }, value: 12.5, unit: { en: 'items', de: 'Einträge' }, format: 'number', digits: 1, text: '12.5', ...extra } as never, metrics: { value: 12.5 } })

beforeAll(() => {
  registerTexts('de', de as TextBundle)
  i18next.addResourceBundle('de', 'translation', deScreen, true, true)
})
beforeEach(() => forgetGivenNames())
afterEach(async () => {
  await i18next.changeLanguage('en')
  useShowcase.setState({ on: false, media: false })
})

describe('one number', () => {
  it('shows the value, the unit and the label in the language of the viewer', () => {
    draw(view('custom.value', 'value'), NUMBER())
    expect(screen.getByText('12.5')).toBeInTheDocument()
    expect(screen.getByText('items')).toBeInTheDocument()
    expect(screen.getByText('Queue')).toBeInTheDocument()
  })

  it('writes the number in German when the viewer reads German, with the German words of the author', async () => {
    await i18next.changeLanguage('de')
    draw(view('custom.value', 'value'), NUMBER())
    expect(screen.getByText('12,5')).toBeInTheDocument()
    expect(screen.getByText('Einträge')).toBeInTheDocument()
    expect(screen.getByText('Warteschlange')).toBeInTheDocument()
  })

  it('does not translate a word the author wrote in English only, although nexdeck knows it (KARTEN-1 AC-6)', async () => {
    await i18next.changeLanguage('de')
    draw(view('custom.value', 'value'), NUMBER({ label: 'Used', unit: 'Queue' }))
    expect(screen.getByText('Used')).toBeInTheDocument()
    expect(screen.getByText('Queue')).toBeInTheDocument()
    expect(screen.queryByText('Belegt')).toBeNull()
    expect(screen.queryByText('Warteschlange')).toBeNull()
  })

  it('translates the same words on a card of nexdeck’s own', async () => {
    await i18next.changeLanguage('de')
    render(<MemoryRouter>{renderWidget({ widget: view('sonarr.status', 'value'), data: { status: 'ok', primary: { label: 'Used', value: 3 } } as WidgetData })}</MemoryRouter>)
    expect(screen.getByText('Belegt')).toBeInTheDocument()
  })

  it('shows a dash for a value the service did not send, and the card stays what it was', () => {
    draw(view('custom.value', 'value'), NUMBER({ value: null, text: '–' }))
    expect(screen.getByText('–')).toBeInTheDocument()
  })
})

describe('the views of a number', () => {
  const shaped = (renderer: string, meta: Record<string, unknown>) =>
    custom({ ...NUMBER(), meta: { custom: true, renderer, gauge: { share: 40, max: 31.25 }, level: 'warn', ...meta } })

  it('draws a dial with the label and the number of the author', () => {
    draw(view('custom.value', 'gauge'), shaped('gauge', {}))
    expect(screen.getByText('Queue')).toBeInTheDocument()
    expect(screen.getByText(/12\.5 items/)).toBeInTheDocument()
  })

  it('draws LEDs with the label as their name', () => {
    draw(view('custom.value', 'meter'), shaped('meter', { meter: { direction: 'across', zones: {} } }))
    expect(screen.getByRole('meter', { name: 'Queue' })).toBeInTheDocument()
    expect(screen.getByText(/12\.5 items/)).toBeInTheDocument()
  })

  it('draws seven segments with the unit and the label', () => {
    draw(view('custom.value', 'segments'), shaped('segments', {}))
    expect(screen.getByTestId('segments')).toBeInTheDocument()
    expect(screen.getByText('items')).toBeInTheDocument()
    expect(screen.getByText('Queue')).toBeInTheDocument()
  })
})

describe('several numbers', () => {
  const data = custom({
    primary: { label: { en: 'Used', de: 'Belegt' }, value: 71, unit: '%', format: 'percent', text: '71%', metric: 'stat1' } as never,
    secondary: [
      { label: 'Free', value: 5368709120, unit: '', format: 'bytes', text: '5.0 GB', metric: 'stat2' },
      { label: { en: 'Name', de: 'Name' }, value: 'nas', unit: '', format: 'text', text: 'nas', metric: 'stat3' },
    ] as never,
    metrics: { stat1: 71 },
  })

  it('shows each value beside its label, a share as a bar', () => {
    const { container } = draw(view('custom.stats', 'stats'), data)
    expect(screen.getByText('Used')).toBeInTheDocument()
    expect(screen.getByText('71%')).toBeInTheDocument()
    expect(screen.getByText('5.0 GB')).toBeInTheDocument()
    expect(screen.getByText('nas')).toBeInTheDocument()
    expect(container.querySelectorAll('.bar')).toHaveLength(3)
  })

  it('shows the unit of the second to the last number as well, in the language of the viewer', async () => {
    const withUnits = custom({
      primary: { label: 'Used', value: 71, unit: '%', format: 'percent', text: '71%', metric: 'stat1' } as never,
      secondary: [
        { label: 'Answer', value: 12, unit: { en: 'milliseconds', de: 'Millisekunden' }, format: 'number', text: '12', metric: 'stat2' },
        { label: 'Waiting', value: 3, unit: 'items', format: 'number', text: '3', metric: 'stat3' },
      ] as never,
      metrics: {},
    })
    const first = draw(view('custom.stats', 'stats'), withUnits)
    expect(screen.getByText(/^12\s*milliseconds$/)).toBeInTheDocument()
    expect(screen.getByText(/^3\s*items$/)).toBeInTheDocument()
    first.unmount()
    await i18next.changeLanguage('de')
    draw(view('custom.stats', 'stats'), withUnits)
    expect(screen.getByText(/^12\s*Millisekunden$/)).toBeInTheDocument()
    expect(screen.getByText(/^3\s*items$/)).toBeInTheDocument()
  })

  it('does not translate the labels of the author', async () => {
    await i18next.changeLanguage('de')
    draw(view('custom.stats', 'stats'), custom({ ...data, secondary: [{ ...data.secondary![0], label: 'Free' }] }))
    expect(screen.getByText('Belegt')).toBeInTheDocument()
    expect(screen.getByText('Free')).toBeInTheDocument()
    expect(screen.queryByText('Frei')).toBeNull()
  })
})

const ROWS = custom({
  items: [
    { title: 'A very long title that does not fit into a small card and is cut short by the list', subtitle: 'Used', value: '5.0 GB', status: 'warn', url: 'https://example.com/a' },
    { title: 'Second', subtitle: '', value: '', status: 'ok' },
  ],
})

describe('a list', () => {
  it('shows title, subtitle, value and status, and a link where the row has one', () => {
    draw(view('custom.list', 'list'), ROWS)
    expect(screen.getByText('Second')).toBeInTheDocument()
    expect(screen.getByText('5.0 GB')).toBeInTheDocument()
    const link = screen.getByRole('link', { name: 'Open' })
    expect(link).toHaveAttribute('href', 'https://example.com/a')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    expect(document.querySelector('.dot[data-status="warn"]')).not.toBeNull()
  })

  it('does not translate the subtitle or the value of a row', async () => {
    await i18next.changeLanguage('de')
    draw(view('custom.list', 'list'), custom({ items: [{ title: 'Disk', subtitle: 'Used', value: 'Queue', status: 'ok' }] }))
    expect(screen.getByText('Used')).toBeInTheDocument()
    expect(screen.getByText('Queue')).toBeInTheDocument()
  })

  it('cuts a long title and gives it whole on hover (KARTEN-6 EC-4)', () => {
    draw(view('custom.list', 'list'), ROWS)
    const title = screen.getByText(/A very long title/)
    expect(title.className).toContain('truncate')
    expect(title).toHaveAttribute('title', title.textContent!)
  })

  it('says what the author wrote when there are no rows, in the language of the viewer (KARTEN-6 EC-1)', async () => {
    const empty = { en: 'Nothing waiting', de: 'Nichts wartet' }
    const first = draw(view('custom.list', 'list'), custom({ items: [], meta: { custom: true, empty } }))
    expect(screen.getByText('Nothing waiting')).toBeInTheDocument()
    first.unmount()
    await i18next.changeLanguage('de')
    draw(view('custom.list', 'list'), custom({ items: [], meta: { custom: true, empty } }))
    expect(screen.getByText('Nichts wartet')).toBeInTheDocument()
  })

  it('says “Nothing here” where the author said nothing (KARTEN-6 EC-1)', async () => {
    const first = draw(view('custom.list', 'list'), custom({ items: [], meta: { custom: true, empty: null } }))
    expect(screen.getByText('Nothing here')).toBeInTheDocument()
    first.unmount()
    await i18next.changeLanguage('de')
    draw(view('custom.list', 'list'), custom({ items: [], meta: { custom: true, empty: null } }))
    expect(screen.getByText('Hier ist nichts')).toBeInTheDocument()
  })

  it('shows every row it is given and scrolls in a card too small for them (KARTEN-6 EC-8)', () => {
    const many = custom({ items: Array.from({ length: 50 }, (_, index) => ({ title: `Row ${index}`, subtitle: '', value: '', status: 'ok' })) })
    const { container } = draw(view('custom.list', 'list'), many)
    expect(container.querySelectorAll('li')).toHaveLength(50)
    expect(container.querySelector('ul')!.className).toContain('scroll')
  })

  it('takes a picture of the row through the server and leaves the row whole when it does not load (KARTEN-6 EC-2)', () => {
    const { container } = draw(view('custom.list', 'list'), custom({ items: [{ title: 'A', subtitle: '', value: '', status: 'ok', art: 'proxy:/p/a.jpg' }] }))
    const image = container.querySelector('img')!
    expect(image.getAttribute('src')).toBe('/api/v1/widgets/41/image?path=%2Fp%2Fa.jpg')
    image.dispatchEvent(new Event('error'))
    expect(image.style.display).toBe('none')
    expect(screen.getByText('A')).toBeInTheDocument()
  })
})

describe('a wall of pictures', () => {
  const COVERS = custom({
    items: [
      { title: 'Harbour', subtitle: 'Season 1', value: '', status: 'ok', art: 'proxy:/_external?u=x&s=y', url: 'https://example.com/h' },
      { title: 'Orbital', subtitle: '', value: '', status: 'ok' },
    ],
  })

  it('says what the author wrote when there are no pictures, and “Nothing here” where the author said nothing (KARTEN-6 EC-1)', async () => {
    const own = draw(view('custom.posters', 'posters'), custom({ items: [], meta: { custom: true, empty: { en: 'No covers yet', de: 'Noch keine Cover' } } }))
    expect(screen.getByText('No covers yet')).toBeInTheDocument()
    own.unmount()
    const none = draw(view('custom.posters', 'posters'), custom({ items: [], meta: { custom: true, empty: null } }))
    expect(screen.getByText('Nothing here')).toBeInTheDocument()
    none.unmount()
    await i18next.changeLanguage('de')
    draw(view('custom.posters', 'posters'), custom({ items: [], meta: { custom: true, empty: { en: 'No covers yet', de: 'Noch keine Cover' } } }))
    expect(screen.getByText('Noch keine Cover')).toBeInTheDocument()
  })

  it('shows a picture, a title and a link; a cover without a picture shows its first letters (KARTEN-6 EC-7)', () => {
    draw(view('custom.posters', 'posters'), COVERS)
    const tiles = screen.getByTestId('posters').querySelectorAll('li')
    expect(tiles).toHaveLength(2)
    expect(tiles[0].querySelector('img')!.getAttribute('src')).toBe('/api/v1/widgets/41/image?path=%2F_external%3Fu%3Dx%26s%3Dy')
    expect(within(tiles[0]).getByRole('link', { name: 'Harbour' })).toHaveAttribute('href', 'https://example.com/h')
    expect(within(tiles[1]).queryByRole('link')).toBeNull()
    expect(screen.getByText('OR')).toBeInTheDocument()
  })

  it('puts the first letters in place of a picture that does not load, and the card stays as it is (KARTEN-6 EC-2)', async () => {
    draw(view('custom.posters', 'posters'), COVERS)
    const image = screen.getByTestId('posters').querySelector('img')!
    image.dispatchEvent(new Event('error'))
    expect(await screen.findByText('HA')).toBeInTheDocument()
    expect(screen.getByText('Harbour')).toBeInTheDocument()
  })

  it('refuses a link that is not http (KARTEN-6 EC-5)', () => {
    draw(
      view('custom.posters', 'posters'),
      custom({ items: [{ title: 'Bad', subtitle: '', value: '', status: 'ok', url: 'javascript:alert(1)' }, { title: 'Relative', subtitle: '', value: '', status: 'ok', url: '/b/home' }] }),
    )
    expect(screen.queryByRole('link')).toBeNull()
  })

  it('does not translate the subtitle', async () => {
    await i18next.changeLanguage('de')
    draw(view('custom.posters', 'posters'), custom({ items: [{ title: 'T', subtitle: 'Used', value: '', status: 'ok' }] }))
    expect(screen.getByText('Used')).toBeInTheDocument()
  })
})

describe('the keyboard (KARTEN-6 EC-6)', () => {
  it('reaches the links of a list, then those of a wall of pictures, in order, and the focus rests on them', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        {renderWidget({ widget: view('custom.list', 'list'), data: ROWS })}
        {renderWidget({
          widget: view('custom.posters', 'posters', { id: 42 }),
          data: custom({ items: [{ title: 'Harbour', subtitle: '', value: '', status: 'ok', url: 'https://example.com/h' }] }),
        })}
      </MemoryRouter>,
    )
    await user.tab()
    expect(screen.getByRole('link', { name: 'Open' })).toHaveFocus()
    await user.tab()
    expect(screen.getByRole('link', { name: 'Harbour' })).toHaveFocus()
  })

  it('shows where the focus is on a cover link', () => {
    draw(view('custom.posters', 'posters'), custom({ items: [{ title: 'Harbour', subtitle: '', value: '', status: 'ok', url: 'https://example.com/h' }] }))
    expect(screen.getByRole('link', { name: 'Harbour' }).className).toContain('focus-visible:outline')
  })
})

describe('showcase mode (KARTEN-6 AC-7)', () => {
  it('makes up the addresses and the names of the home in the rows of a custom list, and keeps the rest', () => {
    useShowcase.setState({ on: true, media: false, domains: ['mydomain.example'], names: ['Morgan'] })
    draw(view('custom.list', 'list'), custom({ items: [{ title: 'sonarr', subtitle: 'sonarr.mydomain.example on 10.20.30.4', value: '', status: 'ok' }] }))
    expect(screen.getByText('sonarr')).toBeInTheDocument()
    expect(screen.getByText('host-a.example on 192.0.2.1')).toBeInTheDocument()
  })

  it('makes up the words of a value in the rows of a several-numbers card', () => {
    useShowcase.setState({ on: true, media: false, domains: ['mydomain.example'], names: [] })
    draw(
      view('custom.stats', 'stats'),
      custom({ primary: { label: 'Host', value: 'nas.mydomain.example', format: 'text', text: 'nas.mydomain.example' } as never, secondary: [] }),
    )
    expect(screen.queryByText('nas.mydomain.example')).toBeNull()
  })
})

describe('the frame of a card', () => {
  it('says there is no demo data in the language of the viewer, and the code is the key (KARTEN-1 AC-11)', async () => {
    const widget = view('custom.value', 'value')
    const data = { status: 'unknown', error: 'No demo data. The card has no example answers.', meta: { code: 'no_demo_data', hint: 'The author gave the card no example answers.' } } as WidgetData
    const first = render(
      <MemoryRouter>
        <WidgetCard widget={widget} data={data} />
      </MemoryRouter>,
    )
    expect(screen.getByTestId('card-error')).toHaveTextContent('No demo data')
    first.unmount()
    await i18next.changeLanguage('de')
    render(
      <MemoryRouter>
        <WidgetCard widget={widget} data={data} />
      </MemoryRouter>,
    )
    expect(screen.getByTestId('card-error')).toHaveTextContent('Keine Demo-Daten')
  })

  it('says the connection is missing, not just that a connection is needed, in the language of the viewer (KARTEN-2 EC-2)', async () => {
    const widget = view('custom.value', 'value')
    const data = { status: 'unknown', error: 'Connection missing. The connection of this card was deleted.', meta: { code: 'connection_missing', hint: "Pick a connection in the card's settings." } } as WidgetData
    const first = render(
      <MemoryRouter>
        <WidgetCard widget={widget} data={data} />
      </MemoryRouter>,
    )
    expect(screen.getByTestId('card-error')).toHaveTextContent('Connection missing')
    first.unmount()
    await i18next.changeLanguage('de')
    render(
      <MemoryRouter>
        <WidgetCard widget={widget} data={data} />
      </MemoryRouter>,
    )
    expect(screen.getByTestId('card-error')).toHaveTextContent('Anbindung fehlt')
  })

  it('draws a custom card inside the frame without running its texts through the table of translations', async () => {
    await i18next.changeLanguage('de')
    render(
      <MemoryRouter>
        <WidgetCard widget={view('custom.value', 'value')} data={NUMBER({ label: 'Used', unit: '' })} />
      </MemoryRouter>,
    )
    expect(screen.getByText('Used')).toBeInTheDocument()
  })
})

describe('HTML in the texts of a card is only text (KARTEN-1 EC-8)', () => {
  const HOSTILE = `<img src=x onerror="document.title='hacked'"><script>document.title="hacked"</script>`
  const nothingRuns = (container: HTMLElement) => {
    expect(container.querySelector('script')).toBeNull()
    expect(container.querySelector('[onerror]')).toBeNull()
    expect(container.querySelector('img[src="x"]')).toBeNull()
    expect(document.title).not.toBe('hacked')
  }

  it('is shown as letters in the number, the several numbers, the list and the wall of pictures', () => {
    const forms: [string, string, WidgetData][] = [
      ['custom.value', 'value', NUMBER({ label: HOSTILE, unit: HOSTILE })],
      [
        'custom.stats',
        'stats',
        custom({
          primary: { label: HOSTILE, value: 'x', unit: '', format: 'text', text: HOSTILE, metric: 'stat1' } as never,
          secondary: [{ label: HOSTILE, value: 'y', unit: HOSTILE, format: 'text', text: HOSTILE, metric: 'stat2' }] as never,
          metrics: {},
        }),
      ],
      ['custom.list', 'list', custom({ items: [{ title: HOSTILE, subtitle: HOSTILE, value: HOSTILE, status: 'ok', url: 'https://example.com/a' }] })],
      ['custom.posters', 'posters', custom({ items: [{ title: HOSTILE, subtitle: HOSTILE, value: '', status: 'ok' }] })],
    ]
    for (const [kind, renderer, data] of forms) {
      const { container, unmount } = draw(view(kind, renderer, { title: HOSTILE }), data)
      nothingRuns(container)
      expect(container.textContent, kind).toContain('<img src=x onerror=')
      unmount()
    }
  })

  it('stays text inside the frame of the card as well', () => {
    const { container } = render(
      <MemoryRouter>
        <WidgetCard widget={view('custom.list', 'list', { title: HOSTILE })} data={custom({ items: [{ title: HOSTILE, subtitle: '', value: '', status: 'ok' }] })} />
      </MemoryRouter>,
    )
    nothingRuns(container)
    expect(container.textContent).toContain('<script>')
  })
})

describe('a tile of key figures (KARTEN-6 AC-2)', () => {
  afterEach(() => useLive.setState({ data: {}, series: {} }))

  it('is a custom number card, with its value, unit and label in the language of the viewer', async () => {
    const tile = view('custom.value', 'value', { id: 5, title: '' })
    const wall = view('core.figures', 'figures', { id: 9, title: 'Wall', options: { cards: [5] } })
    useLive.setState({ data: { 5: NUMBER() }, series: {} })
    await i18next.changeLanguage('de')
    render(
      <PageCardsContext.Provider value={{ widgets: [tile, wall] }}>
        <FiguresCard widget={wall} data={{ status: 'unknown', meta: wall.options } as WidgetData} />
      </PageCardsContext.Provider>,
    )
    expect(screen.getByText('12,5')).toBeInTheDocument()
    expect(screen.getByText('Einträge')).toBeInTheDocument()
    expect(screen.getAllByText('Warteschlange').length).toBeGreaterThan(0)
  })
})
