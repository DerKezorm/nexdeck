/**
 * "Found in your network" at the top of the catalog: what runs and is not
 * connected, with the address filled in, Connect and Ignore; and nothing at
 * all where nothing was found.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { AdapterSpec } from '../../../api/types'
import CatalogDialog from './CatalogDialog'
import type { FoundService } from './FoundInNetwork'

const state = vi.hoisted(() => ({
  found: [] as FoundService[],
  ignored: [] as string[],
  calls: [] as string[],
}))

vi.mock('../../../api/client', () => ({
  ApiError: class ApiError extends Error {},
  get: vi.fn(async () => {
    state.calls.push('get')
    return { found: state.found.filter((one) => !state.ignored.includes(one.key)), ignored: state.ignored.length, looked_at: '2026-10-27T10:00:00Z' }
  }),
  post: vi.fn(async (_path: string, body: { key: string }) => {
    state.calls.push(`ignore ${body.key}`)
    state.ignored.push(body.key)
  }),
  del: vi.fn(async () => {
    state.calls.push('show again')
    state.ignored = []
  }),
}))

function service(kind: string, label: string, address: string): FoundService {
  return { key: `${kind}@container:1:${kind}`, kind, label, icon: kind, beta: false, thing: 'container', name: kind, engine: 'Docker docker-live', address }
}

const ADAPTERS = [{ kind: 'mealie', label: 'Mealie', category: 'other', description: '', icon: 'mealie', beta: false, docs_url: '', needs_integration: true, fields: [], widgets: [] }] as AdapterSpec[]

function show(connecting = true) {
  const onConnect = connecting ? vi.fn() : undefined
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <CatalogDialog adapters={ADAPTERS} integrations={[]} onClose={vi.fn()} onPick={vi.fn()} onConnect={onConnect} />
    </QueryClientProvider>,
  )
  return onConnect
}

beforeEach(() => {
  state.found = [service('mealie', 'Mealie', 'http://192.0.2.10:9925'), service('paperless', 'Paperless-ngx', 'http://192.0.2.10:8000')]
  state.ignored = []
  state.calls = []
})

describe('found in your network', () => {
  it('stands above the catalog with where each one runs and its address', async () => {
    show()
    const section = await screen.findByRole('region', { name: 'Found in your network' })
    expect(within(section).getByText('Container mealie on Docker docker-live')).toBeInTheDocument()
    expect(within(section).getByRole('textbox', { name: 'Address of Mealie' })).toHaveValue('http://192.0.2.10:9925')
  })

  it('connects with the address as it stands in the field, corrected or not', async () => {
    const onConnect = show()
    const field = await screen.findByRole('textbox', { name: 'Address of Mealie' })
    await userEvent.clear(field)
    await userEvent.type(field, 'http://192.0.2.11:9925')
    await userEvent.click(screen.getByRole('button', { name: 'Connect Mealie' }))
    expect(onConnect).toHaveBeenCalledWith('mealie', 'http://192.0.2.11:9925')
  })

  it('ignores one for good and offers them back', async () => {
    show()
    await userEvent.click(await screen.findByRole('button', { name: 'Ignore Mealie' }))
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Connect Mealie' })).toBeNull())
    expect(state.calls).toContain('ignore mealie@container:1:mealie')
    expect(screen.getByText('1 ignored.', { exact: false })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Show again' }))
    expect(await screen.findByRole('button', { name: 'Connect Mealie' })).toBeInTheDocument()
  })

  it('follows the search, and is gone when the search passes them by', async () => {
    show()
    await screen.findByRole('button', { name: 'Connect Mealie' })
    await userEvent.type(screen.getByRole('textbox', { name: 'Search the services' }), 'paperless')
    expect(screen.queryByRole('button', { name: 'Connect Mealie' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Connect Paperless-ngx' })).toBeInTheDocument()
    await userEvent.type(screen.getByRole('textbox', { name: 'Search the services' }), ' nothing')
    expect(screen.queryByRole('region', { name: 'Found in your network' })).toBeNull()
  })

  it('is not there when nothing was found', async () => {
    state.found = []
    show()
    await waitFor(() => expect(state.calls).toContain('get'))
    await screen.findByRole('button', { name: /^Mealie/ })
    expect(screen.queryByRole('region', { name: 'Found in your network' })).toBeNull()
  })

  it('is not asked for without a way to connect', async () => {
    show(false)
    await screen.findByRole('button', { name: /^Mealie/ })
    expect(state.calls).toEqual([])
  })
})
