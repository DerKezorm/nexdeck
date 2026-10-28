/**
 * The own list on screen: the summary filters, the search, the full error
 * under its row, "Build a card", and the choice of list or categories kept
 * per browser.
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18next from 'i18next'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { AdapterSpec, Integration } from '../../../api/types'
import de from '../../../i18n/texts.de.json'
import { registerTexts, type TextBundle } from '../../../i18n/texts'
import { OwnList, type OwnListProps } from './OwnList'
import type { VersionReading } from './own'

function connection(id: number, name: string, extra: Partial<Integration> = {}): Integration {
  return {
    id, kind: 'sonarr', label: 'Sonarr', icon: 'sonarr', beta: false, name, config: {}, enabled: true, demo: false, admin_only: false,
    muted: false, last_ok_at: '2026-10-27T10:00:00Z', last_error: '', widget_count: 2, created_at: '2026-10-01T10:00:00Z', ...extra,
  }
}

const ADAPTERS = [
  { kind: 'sonarr', category: 'downloads' },
  { kind: 'qbittorrent', category: 'downloads' },
  { kind: 'plex', category: 'media' },
] as AdapterSpec[]

const ERROR = 'Could not connect: timed out after 10 s at http://192.0.2.31:8080, check that the service runs'

const LIST = [
  connection(1, 'Sonarr'),
  connection(2, 'qBittorrent VPN', { kind: 'qbittorrent', label: 'qBittorrent', last_error: ERROR }),
  connection(3, 'Plex Living Room', { kind: 'plex', label: 'Plex', widget_count: 0 }),
  connection(4, 'Plex Cellar', { kind: 'plex', label: 'Plex', muted: true }),
]
const VERSIONS: Record<string, VersionReading> = {
  1: { running: '4.0.15', newest: '4.0.16', url: 'https://example.com/r', problem: '', state: 'behind', major: false, upstream: 'Sonarr/Sonarr', unread: false, asked: true },
}

function show(extra: Partial<OwnListProps> = {}) {
  const props: OwnListProps = {
    integrations: LIST, adapters: ADAPTERS, versions: VERSIONS, versionsLoading: false, admin: true,
    onBell: vi.fn(), onEdit: vi.fn(), onRemove: vi.fn(), onBuildCard: vi.fn(), onSearchCatalog: vi.fn(), ...extra,
  }
  render(<OwnList {...props} />)
  return props
}

const names = () => screen.getAllByRole('listitem').map((row) => row.querySelector('.truncate')?.textContent)

beforeEach(() => localStorage.clear())

describe('the summary', () => {
  it('counts each filter and leaves out the empty ones', () => {
    show()
    const chips = within(screen.getByRole('group', { name: 'Filter the list' })).getAllByRole('button')
    expect(chips.map((chip) => chip.textContent)).toEqual(['4connections', '1failing', '1update', '1without a card', '1muted'])
  })

  it('filters with one click and lets go with the next', async () => {
    show()
    const failing = screen.getByRole('button', { name: /failing/ })
    await userEvent.click(failing)
    expect(failing).toHaveAttribute('aria-pressed', 'true')
    expect(names()).toEqual(['qBittorrent VPN'])
    expect(screen.getByText('1 of 4 shown, 6 cards together.')).toBeInTheDocument()
    await userEvent.click(failing)
    expect(names()).toHaveLength(4)
  })
})

describe('the list', () => {
  it('puts the failing connection first and the one with an update next', () => {
    show()
    expect(names()).toEqual(['qBittorrent VPN', 'Sonarr', 'Plex Cellar', 'Plex Living Room'])
  })

  it('shows the whole error under its row, not cut off in the line above', () => {
    show()
    const row = screen.getAllByRole('listitem')[0]
    const error = within(row).getByText(ERROR)
    expect(error.className).not.toContain('truncate')
    expect(row).toHaveAttribute('data-failing', 'true')
  })

  it('gives a newer version a line of its own, for the phone', () => {
    show()
    expect(screen.getByText('newer 4.0.16, runs 4.0.15')).toBeInTheDocument()
  })

  it('offers to build a card where there is none, and only to an administrator', async () => {
    const props = show()
    const build = screen.getAllByRole('button', { name: 'Build a card' })
    expect(build).toHaveLength(1)
    await userEvent.click(build[0])
    expect(props.onBuildCard).toHaveBeenCalledWith(expect.objectContaining({ id: 3 }))
  })

  it('says in the language of the page why a version is not known', async () => {
    registerTexts('de', de as TextBundle)
    await i18next.changeLanguage('de')
    try {
      const silent: VersionReading = { running: null, newest: null, url: '', problem: 'The service does not say which version it runs.', state: 'unknown', major: false, upstream: '', unread: false, asked: true }
      show({ versions: { ...VERSIONS, 3: silent } })
      const row = screen.getAllByRole('listitem').find((item) => item.textContent?.includes('Plex Living Room'))
      expect(row?.querySelector('[data-version] [title]')).toHaveAttribute('title', 'Der Dienst nennt seine Version nicht.')
    } finally {
      await i18next.changeLanguage('en')
    }
  })

  it('has no buttons for somebody who may not change a connection', () => {
    show({ admin: false })
    expect(screen.queryByRole('button', { name: 'Build a card' })).toBeNull()
    expect(screen.queryByRole('button', { name: /Edit / })).toBeNull()
    expect(screen.getByText(ERROR)).toBeInTheDocument()
  })
})

describe('the search', () => {
  it('narrows the list and offers the catalog when nothing of your own matches', async () => {
    const props = show()
    await userEvent.type(screen.getByRole('textbox', { name: 'Search your connections' }), 'plex cellar')
    expect(names()).toEqual(['Plex Cellar'])
    await userEvent.clear(screen.getByRole('textbox', { name: 'Search your connections' }))
    await userEvent.type(screen.getByRole('textbox', { name: 'Search your connections' }), 'immich')
    expect(screen.getByText('None of your connections matches “immich”.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Search the catalog for “immich”' }))
    expect(props.onSearchCatalog).toHaveBeenCalledWith('immich')
  })
})

describe('by category', () => {
  it('groups under the categories with their marks, folds, and is remembered', async () => {
    show()
    await userEvent.click(screen.getByRole('button', { name: 'By category' }))
    expect(localStorage.getItem('nexdeck.integrations.view')).toBe('category')
    const downloads = screen.getByRole('region', { name: 'Downloads' })
    expect(within(downloads).getByText('1 failing')).toBeInTheDocument()
    expect(within(downloads).getByText('1 update')).toBeInTheDocument()
    const head = within(downloads).getByRole('button', { name: /Downloads/ })
    await userEvent.click(head)
    expect(head).toHaveAttribute('aria-expanded', 'false')
    expect(within(downloads).queryByRole('listitem')).toBeNull()
  })

  it('opens the way this browser left it', () => {
    localStorage.setItem('nexdeck.integrations.view', 'category')
    show()
    expect(screen.getByRole('button', { name: 'By category' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('region', { name: 'Media' })).toBeInTheDocument()
  })
})
