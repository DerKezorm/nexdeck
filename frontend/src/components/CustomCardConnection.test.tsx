/**
 * The connection of a custom card in its settings.
 *
 * ⚠️ The sheet offered the connections of the card's own kind, `custom`, of which there are none: it showed "None" and
 * nothing else, and saving would have taken the card off the connection it reads through.
 */
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { vi } from 'vitest'

import { WidgetSettingsSheet } from './WidgetSettingsSheet'

const WIDGET = {
  id: 9,
  kind: 'custom.value',
  title: 'Lights on',
  icon: '',
  link: '',
  renderer: 'value',
  options: { card: 'lights-on' },
  integration_id: 5,
  refresh_seconds: 60,
  health: null,
}

const HOME = { id: 5, kind: 'homeassistant', name: 'Home Assistant', icon: 'homeassistant', config: {} }
const CABIN = { id: 6, kind: 'homeassistant', name: 'Cabin', icon: 'homeassistant', config: {} }
const PLEX = { id: 7, kind: 'plex', name: 'Plex', icon: 'plex', config: {} }

function serve(integrations: unknown[]) {
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } })
    if (url.includes('/adapters')) {
      return json([{ kind: 'custom', label: 'Custom cards', needs_integration: true, fields: [],
        widgets: [{ kind: 'custom.value', label: 'Custom number', options: [] }] }])
    }
    if (url.includes('/cards/library')) {
      return json({ cards: [{ slug: 'lights-on', name: 'Lights on', form: 'value', version: '1.0.0',
        requires: [{ kind: 'homeassistant', label: 'Home Assistant', icon: 'homeassistant' }], fits: [] }] })
    }
    if (url.includes('/integrations')) return json(integrations)
    return json({})
  }))
}

function open() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <WidgetSettingsSheet widget={WIDGET as never} pages={[{ id: 1, name: 'one' }]} onClose={vi.fn()} onSaved={vi.fn()} onDeleted={vi.fn()} />
    </QueryClientProvider>,
  )
}

const choices = (select: HTMLSelectElement) => Array.from(select.options).map((one) => one.textContent)

it('karten6: a custom card offers the connections of the kinds it reads through, without None', async () => {
  serve([HOME, CABIN, PLEX])
  open()
  const select = (await screen.findByRole('combobox', { name: /^(integration|anbindung)$/i })) as HTMLSelectElement
  await vi.waitFor(() => expect(choices(select)).toEqual(['Home Assistant', 'Cabin']))
  expect(select.value).toBe('5')
  expect(select.disabled).toBe(false)
})

it('karten6: with a single connection that fits, it shows it and there is nothing to choose', async () => {
  serve([HOME, PLEX])
  open()
  const select = (await screen.findByRole('combobox', { name: /^(integration|anbindung)$/i })) as HTMLSelectElement
  await vi.waitFor(() => expect(choices(select)).toEqual(['Home Assistant']))
  expect(select.value).toBe('5')
  expect(select.disabled).toBe(true)
})
