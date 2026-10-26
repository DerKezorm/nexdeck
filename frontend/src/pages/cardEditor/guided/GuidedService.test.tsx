/**
 * The step "Service" names the kind of a service, never a connection of the person (dienst-art D1 to D5): one tile for
 * each kind, those with a connection first, a search over both groups, and the connection the card is tried with
 * as a choice that stays out of the card.
 */
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18next from 'i18next'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import de from '../../../i18n/editor.de.json'
import en from '../../../i18n/editor.en.json'
import es from '../../../i18n/editor.es.json'
import fr from '../../../i18n/editor.fr.json'
import it_ from '../../../i18n/editor.it.json'
import type { Integration } from '../../../api/types'
import { readAt } from '../../../lib/cardDocument'
import { editor, openNew, prepare } from '../../../test/cardEditor'
import { INTEGRATIONS, SOURCES, stubGuided } from '../../../test/guidedWorld'
import { serviceGroups } from './services'

const click = async (name: string | RegExp) => userEvent.click(await screen.findByRole('button', { name }))
const card = () => editor().card!
const names = (list: HTMLElement[]) => list.map((one) => one.textContent)

beforeEach(() => {
  prepare()
  stubGuided()
})

afterEach(async () => {
  vi.unstubAllGlobals()
  await i18next.changeLanguage('en')
})

describe('umbau dienst D1: the question is about the service, not about the connection', () => {
  it('asks which service the card is for and says it works with every connection of the kind', async () => {
    await openNew()
    expect(await screen.findByRole('heading', { name: 'Which service is the card for?', level: 2 })).toBeInTheDocument()
    expect(screen.getByText('The card works with every integration of this kind. Your integration is only for trying it out.')).toBeInTheDocument()
  })

  it('reads in German as decided and without dashes', () => {
    const service = de.editor.guided.service
    expect(service.title).toBe('Für welchen Dienst ist die Karte?')
    expect(service.lead).toBe('Die Karte funktioniert mit jeder Anbindung dieser Art. Deine Anbindung dient nur zum Ausprobieren.')
    for (const text of Object.values(service)) expect(text).not.toMatch(/[—–]| - /)
  })
})

describe('umbau dienst D2: one tile for each kind, two groups, a search', () => {
  it('shows each kind once, with its name, and the number of connections only where there are several', async () => {
    await openNew()
    const mine = within(await screen.findByTestId('card-services-mine'))
    // Plex (old) is switched off and qBittorrent cannot be read by a card: neither makes a tile. Two Synology connections are one tile.
    expect(names(mine.getAllByRole('button'))).toEqual(['Home Assistant', 'JSON API', 'Plex', 'Proxmox VE', 'Synology DSM2 integrations'])
    expect(screen.getAllByRole('button', { name: /Synology/ })).toHaveLength(1)
    expect(screen.queryByRole('button', { name: /Synology Backup|Synology Storage/ })).toBeNull()
  })

  it('lists every other readable kind below, by category and then by name', async () => {
    await openNew()
    const all = within(await screen.findByTestId('card-services-all'))
    expect(names(all.getAllByRole('button'))).toEqual(['SABnzbd', 'Sonarr'])
    expect(all.getByRole('heading', { name: 'Downloads', level: 4 })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /qBittorrent/ })).toBeNull()
  })

  it('has no tile for a kind without a connection in the first group, and keeps it in the second', () => {
    const groups = serviceGroups(SOURCES, INTEGRATIONS as unknown as Integration[])
    expect(groups.connected.map((one) => one.kind)).toEqual(['homeassistant', 'jsonapi', 'plex', 'proxmox', 'synology'])
    expect(groups.others.map((one) => one.kind)).toEqual(['sabnzbd', 'sonarr'])
    expect(groups.connected.find((one) => one.kind === 'synology')?.connections.map((one) => one.id)).toEqual([17, 18])
  })

  it('filters both groups by name and by category', async () => {
    await openNew()
    const search = await screen.findByRole('searchbox', { name: 'Search services' })
    await userEvent.type(search, 'sonar')
    expect(screen.queryByTestId('card-services-mine')).toBeNull()
    expect(names(within(screen.getByTestId('card-services-all')).getAllByRole('button'))).toEqual(['Sonarr'])
    await userEvent.clear(search)
    await userEvent.type(search, 'nas')
    expect(names(within(screen.getByTestId('card-services-mine')).getAllByRole('button'))).toEqual(['Synology DSM2 integrations'])
    expect(screen.queryByTestId('card-services-all')).toBeNull()
    await userEvent.clear(search)
    await userEvent.type(search, 'zzz')
    expect(screen.getByText('No service matches.')).toBeInTheDocument()
  })
})

describe('umbau dienst D3: what the card is tried with', () => {
  it('takes the one connection of the kind quietly and says so', async () => {
    await openNew()
    await click(/^Proxmox VE/)
    expect(readAt(card(), ['requires'])).toEqual(['proxmox'])
    expect(editor().integrationId).toBe(12)
    expect(await screen.findByTestId('card-try-with')).toHaveTextContent('Trying it out with: pve')
    await click(/^1 Service/)
    expect(await screen.findByTestId('card-try-with')).toHaveTextContent('Trying it out with: pve')
  })

  it('offers a choice between several, the first as the start, and the choice stays out of the card', async () => {
    await openNew()
    await click(/^Synology DSM/)
    expect(readAt(card(), ['requires'])).toEqual(['synology'])
    expect(editor().integrationId).toBe(17)
    const choice = within(await screen.findByTestId('card-try-with'))
    await userEvent.selectOptions(choice.getByRole('combobox', { name: 'Trying it out with' }), 'Synology Storage')
    expect(editor().integrationId).toBe(18)
    // D4: a connection is never written into the definition.
    expect(editor().text).not.toMatch(/Synology (Backup|Storage)|integration|\b1[78]\b/)
    expect(readAt(card(), ['requires'])).toEqual(['synology'])
  })

  it('replaces the kind when another service is chosen, never adds to it', async () => {
    await openNew()
    await click(/^Proxmox VE/)
    await click(/^1 Service/)
    await click(/^Plex/)
    expect(readAt(card(), ['requires'])).toEqual(['plex'])
    expect(editor().integrationId).toBe(13)
  })

  it('builds a card for a kind with no connection: the way to make one, no asking, a reason', async () => {
    await openNew()
    await click(/^Sonarr/)
    expect(readAt(card(), ['requires'])).toEqual(['sonarr'])
    expect(editor().integrationId).toBeNull()
    expect(await screen.findByTestId('card-no-connection')).toBeInTheDocument()
    const ask = screen.getByRole('button', { name: 'Ask' })
    expect(ask).toBeDisabled()
    expect(ask).toHaveAttribute('title', 'Asking needs an integration of this kind. Add one to try the card for real.')
    await click(/^1 Service/)
    const notice = await screen.findByTestId('card-no-connection')
    expect(notice).toHaveTextContent('You have no integration of this kind. You can still build the card, with example data.')
    expect(within(notice).getByRole('link', { name: 'Add an integration' })).toHaveAttribute('href', '/system/integrations?add=sonarr')
  })
})

describe('umbau dienst D5: the words come in all five languages', () => {
  it('has every new word in each language', () => {
    const keys = ['title', 'lead', 'search', 'mine', 'all', 'connections_one', 'connections_other', 'tryWith', 'noneOfKind', 'noMatch']
    for (const texts of [en, de, es, fr, it_]) {
      const service = texts.editor.guided.service as Record<string, string>
      for (const key of keys) expect(service[key], key).toBeTruthy()
      expect(service.none).toBeUndefined()
      expect((texts.editor.guided.data as Record<string, string>).askLocked).toBeTruthy()
    }
    expect(de.editor.guided.service.tryWith).toBe('Ausprobieren mit')
    expect(de.editor.guided.service.mine).toBe('Bei dir angebunden')
    expect(de.editor.guided.service.all).toBe('Alle Dienste')
  })
})
