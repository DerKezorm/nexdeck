/**
 * The catalog window: the search has the focus, Enter takes the first hit,
 * the categories narrow, beta can go, and the generic connection is always
 * there as the way out.
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { AdapterSpec, Integration } from '../../../api/types'
import CatalogDialog from './CatalogDialog'

function adapter(kind: string, label: string, category: string, extra: Partial<AdapterSpec> = {}): AdapterSpec {
  return { kind, label, category, description: '', icon: kind, beta: false, docs_url: '', needs_integration: true, fields: [], widgets: [], ...extra }
}

const ADAPTERS = [
  adapter('tautulli', 'Tautulli', 'media', { description: 'Who is watching on Plex right now. And the history.' }),
  adapter('plex', 'Plex', 'media'),
  adapter('jellystat', 'Jellystat', 'media', { beta: true }),
  adapter('pihole', 'Pi-hole', 'network'),
  adapter('jsonapi', 'JSON API', 'generic'),
]
const OWN = [{ kind: 'plex' }, { kind: 'plex' }, { kind: 'pihole' }] as Integration[]

function show(extra: Partial<Parameters<typeof CatalogDialog>[0]> = {}) {
  const props = { adapters: ADAPTERS, integrations: OWN, onClose: vi.fn(), onPick: vi.fn(), ...extra }
  render(<CatalogDialog {...props} />)
  return props
}

const field = () => screen.getByRole('textbox', { name: 'Search the services' })

describe('the catalog window', () => {
  it('opens with the focus in the search', () => {
    show()
    expect(field()).toHaveFocus()
  })

  it('opens the first hit on Enter, the service named so before one that mentions it', async () => {
    const props = show()
    await userEvent.type(field(), 'plex{Enter}')
    expect(props.onPick).toHaveBeenCalledWith('plex')
    expect(screen.getByText(/2 hits\./)).toBeInTheDocument()
  })

  it('does nothing on Enter while nothing is typed', async () => {
    const props = show()
    await userEvent.type(field(), '{Enter}')
    expect(props.onPick).not.toHaveBeenCalled()
  })

  it('starts with the words it was opened with', () => {
    show({ initialQuery: 'hole' })
    expect(field()).toHaveValue('hole')
    expect(screen.getByRole('button', { name: /Pi-hole/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Tautulli/ })).toBeNull()
  })

  it('says one sentence on a tile, and how often a service is connected', () => {
    show()
    expect(screen.getByText('Who is watching on Plex right now.')).toBeInTheDocument()
    const plex = screen.getByRole('button', { name: /^Plex/ })
    expect(within(plex).getByText('connected (2)')).toBeInTheDocument()
    expect(within(screen.getByRole('button', { name: /^Pi-hole/ })).getByText('connected')).toBeInTheDocument()
  })

  it('narrows to a category, and to what is connected already', async () => {
    show()
    const nav = screen.getByRole('navigation', { name: 'Categories' })
    await userEvent.click(within(nav).getByRole('button', { name: /Network/ }))
    expect(screen.getByRole('button', { name: /^Pi-hole/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Plex/ })).toBeNull()
    await userEvent.click(within(nav).getByRole('button', { name: /Already connected/ }))
    expect(screen.getByRole('button', { name: /^Plex/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Tautulli/ })).toBeNull()
  })

  it('offers the hits of every category when the chosen one has none', async () => {
    show()
    await userEvent.click(within(screen.getByRole('navigation', { name: 'Categories' })).getByRole('button', { name: /Network/ }))
    await userEvent.type(field(), 'tautulli')
    expect(screen.getByText('Nothing matches “tautulli” in Network.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '1 hit in all categories' }))
    expect(screen.getByRole('button', { name: /^Tautulli/ })).toBeInTheDocument()
  })

  it('hides beta with its switch', async () => {
    show()
    expect(screen.getByRole('button', { name: /^Jellystat/ })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('switch', { name: 'Hide beta' }))
    expect(screen.queryByRole('button', { name: /^Jellystat/ })).toBeNull()
  })

  it('keeps the generic connection at the bottom as the way out', async () => {
    const props = show()
    await userEvent.click(screen.getAllByRole('button', { name: 'Generic (HTTP/JSON)' })[0])
    expect(props.onPick).toHaveBeenCalledWith('jsonapi')
  })

  it('closes on Escape and on its button', async () => {
    const props = show()
    await userEvent.keyboard('{Escape}')
    expect(props.onClose).toHaveBeenCalledTimes(1)
    await userEvent.click(screen.getByRole('button', { name: 'Close' }))
    expect(props.onClose).toHaveBeenCalledTimes(2)
  })

  it('shows what stands above the catalog only while all categories are shown', async () => {
    show({ above: (query) => <p>{`found for "${query}"`}</p> })
    expect(screen.getByText('found for ""')).toBeInTheDocument()
    await userEvent.type(field(), 'pi')
    expect(screen.getByText('found for "pi"')).toBeInTheDocument()
    await userEvent.click(within(screen.getByRole('navigation', { name: 'Categories' })).getByRole('button', { name: /Media/ }))
    expect(screen.queryByText(/found for/)).toBeNull()
  })
})
