/**
 * Saving an app card must not quietly rewrite its reachability check.
 *
 * ⚠️ The sheet read the kind and the interval back and hard-coded the rest,
 * while the server assigns every field of the body without condition. So
 * renaming a card put the TLS box back to off, the timeout back to five
 * seconds and the expected status back to any. Whoever had ticked that box for
 * a service with a self-signed certificate lost it on the next rename, and two
 * minutes later every administrator got an outage notice about a service that
 * had been fine all along.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { vi } from 'vitest'

import { WidgetSettingsSheet } from './WidgetSettingsSheet'

const HEALTH = {
  id: 7,
  kind: 'http',
  target: 'https://films.example.com',
  interval_seconds: 120,
  timeout_seconds: 20,
  expect_status: 401,
  insecure: true,
  enabled: true,
  last_ok: true,
  last_latency_ms: 40,
  down_since: null,
  last_error: '',
}

const WIDGET = {
  id: 3,
  kind: 'core.app',
  title: 'Films',
  icon: 'radarr',
  link: 'https://films.example.com',
  renderer: 'app',
  options: {},
  integration_id: null,
  refresh_seconds: 60,
  health: HEALTH,
}

/** The options of the app tile as the server describes them, trimmed to the two switches. */
const APP_OPTIONS = [
  { name: 'check', label: 'Check reachability', type: 'bool', default: true },
  { name: 'open_new_tab', label: 'Open in a new tab', type: 'bool', default: true },
]

function answerWith(sent: Record<string, unknown>[], options: unknown[] = []) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    if (init?.body && url.includes('/health')) sent.push(JSON.parse(String(init.body)))
    if (url.includes('/adapters')) {
      return new Response(JSON.stringify([{ kind: 'core', label: 'Core', needs_integration: false, fields: [], widgets: [{ kind: 'core.app', label: 'App', options }] }]), {
        status: 200, headers: { 'content-type': 'application/json' },
      })
    }
    if (url.includes('/integrations')) {
      return new Response('[]', { status: 200, headers: { 'content-type': 'application/json' } })
    }
    return new Response(JSON.stringify({}), { status: 200, headers: { 'content-type': 'application/json' } })
  })
}

async function saveTheCard() {
  const sent: Record<string, unknown>[] = []
  vi.stubGlobal('fetch', answerWith(sent))
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <WidgetSettingsSheet widget={WIDGET as never} pages={[{ id: 1, name: 'one' }]} onClose={vi.fn()} onSaved={vi.fn()} onDeleted={vi.fn()} />
    </QueryClientProvider>,
  )
  const save = await screen.findByRole('button', { name: /save|speichern/i })
  await userEvent.click(save)
  await waitFor(() => expect(sent.length).toBeGreaterThan(0))
  return sent[0]
}

it('sends back the check that is there, not the factory one', async () => {
  const body = await saveTheCard()
  expect(body.insecure).toBe(true)
  expect(body.timeout_seconds).toBe(20)
  expect(body.expect_status).toBe(401)
  expect(body.interval_seconds).toBe(120)
})

it('switches a check on that was off, since the switch that shows says on', async () => {
  // ⚠️ A demo tile's check starts switched off, and nothing in the sheet shows
  // that flag. Sending it back as it was kept an edited tile grey for good.
  const sent: Record<string, unknown>[] = []
  vi.stubGlobal('fetch', answerWith(sent))
  const off = { ...WIDGET, health: { ...HEALTH, enabled: false } }
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <WidgetSettingsSheet widget={off as never} pages={[{ id: 1, name: 'one' }]} onClose={vi.fn()} onSaved={vi.fn()} onDeleted={vi.fn()} />
    </QueryClientProvider>,
  )
  await userEvent.click(await screen.findByRole('button', { name: /save|speichern/i }))
  await waitFor(() => expect(sent.length).toBeGreaterThan(0))
  expect(sent[0].enabled).toBe(true)
  expect(sent[0].insecure).toBe(true)
})

it('gives a card without a check a fresh one, not the card opened before', async () => {
  // ⚠️ The sheet stays mounted between cards; its check settings used to stay too.
  const sent: Record<string, unknown>[] = []
  vi.stubGlobal('fetch', answerWith(sent))
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const sheet = (widget: unknown) => (
    <QueryClientProvider client={client}>
      <WidgetSettingsSheet widget={widget as never} pages={[{ id: 1, name: 'one' }]} onClose={vi.fn()} onSaved={vi.fn()} onDeleted={vi.fn()} />
    </QueryClientProvider>
  )
  const { rerender } = render(sheet({ ...WIDGET, health: { ...HEALTH, kind: 'tcp' } }))
  await screen.findByRole('button', { name: /save|speichern/i })
  rerender(sheet({ ...WIDGET, id: 4, title: 'Plex', health: null }))
  await userEvent.click(await screen.findByRole('button', { name: /save|speichern/i }))
  await waitFor(() => expect(sent.length).toBeGreaterThan(0))
  expect(sent[0]).toMatchObject({ kind: 'http', interval_seconds: 30, timeout_seconds: 5, expect_status: 0, insecure: false, enabled: true })
})

it('shows the switch of the check once, in the box of the check', async () => {
  vi.stubGlobal('fetch', answerWith([], APP_OPTIONS))
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <WidgetSettingsSheet widget={WIDGET as never} pages={[{ id: 1, name: 'one' }]} onClose={vi.fn()} onSaved={vi.fn()} onDeleted={vi.fn()} />
    </QueryClientProvider>,
  )
  // The other switch of the list is there, so the options have arrived.
  expect(await screen.findByRole('switch', { name: /open in a new tab|in einem neuen tab/i })).toBeInTheDocument()
  expect(screen.getAllByRole('switch', { name: /check reachability|erreichbarkeit prüfen/i })).toHaveLength(1)
})
