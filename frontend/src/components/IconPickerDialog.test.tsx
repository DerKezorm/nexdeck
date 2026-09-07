/**
 * The overview lists symbols and every logo name, filters as you type, and a
 * click hands the chosen name back and closes. The name index is fetched
 * once; the filtering never waits for the network.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'

import { IconPickerDialog } from './IconPickerDialog'

const calls = vi.hoisted(() => ({
  uploaded: [] as { path: string; name: string; fields: Record<string, string> }[],
  deleted: [] as string[],
  own: [{ id: 7, filename: 'nas.png', url: '/api/v1/assets/7/nas.png' }],
}))

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  get: vi.fn(async (path: string) => {
    if (path === '/icons/names') {
      return [
        { name: 'nexview', source: 'bundled' },
        { name: 'radarr', source: 'dashboard-icons' },
        { name: 'radarr-4k', source: 'dashboard-icons' },
        { name: 'sonarr', source: 'selfhst' },
      ]
    }
    if (path === '/assets?kind=icon') return calls.own
    throw new Error(`unexpected request ${path}`)
  }),
  del: vi.fn(async (path: string) => {
    calls.deleted.push(path)
    calls.own = []
    return {}
  }),
  upload: vi.fn(async (path: string, file: File, fields: Record<string, string>) => {
    calls.uploaded.push({ path, name: file.name, fields })
    return { id: 8, filename: file.name, url: `/api/v1/assets/8/${file.name}` }
  }),
}))

function wrap(children: ReactNode) {
  return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>
}

describe('IconPickerDialog', () => {
  it('lists every logo and symbol, filters by name and hands the pick back', async () => {
    const picked: string[] = []
    let closed = 0
    render(wrap(<IconPickerDialog open value="" onPick={(name) => picked.push(name)} onClose={() => (closed += 1)} />))
    const overview = await screen.findByTestId('icon-overview')
    await waitFor(() => expect(overview.querySelectorAll('button')).toHaveLength(4))
    expect(screen.getByRole('button', { name: 'nexview' })).toBeInTheDocument()
    // Symbols come from the curated lucide set.
    expect(screen.getByRole('button', { name: 'rss' })).toBeInTheDocument()

    await userEvent.type(screen.getByPlaceholderText('Filter by name…'), 'rad')
    expect(overview.querySelectorAll('button')).toHaveLength(2)
    expect(screen.queryByRole('button', { name: 'sonarr' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'rss' })).toBeNull()

    await userEvent.click(screen.getByRole('button', { name: 'radarr-4k' }))
    expect(picked).toEqual(['radarr-4k'])
    expect(closed).toBe(1)
  })

  it('offers what this installation uploaded, before the collections', async () => {
    const picked: string[] = []
    render(wrap(<IconPickerDialog open value="" onPick={(name) => picked.push(name)} onClose={() => undefined} />))
    const own = await screen.findByRole('button', { name: 'nas.png' })
    await userEvent.click(own)
    // ⚠️ The address, not the file name. An uploaded icon is reached by its
    // own address; the name is only what it is called on disk.
    expect(picked).toEqual(['/api/v1/assets/7/nas.png'])
  })

  it('uploads a file and takes it straight away', async () => {
    const picked: string[] = []
    render(wrap(<IconPickerDialog open value="" onPick={(name) => picked.push(name)} onClose={() => undefined} />))
    await screen.findByRole('button', { name: 'radarr' })
    await userEvent.upload(screen.getByLabelText('Upload'), new File(['x'], 'own-logo.png', { type: 'image/png' }))

    await waitFor(() => expect(calls.uploaded).toHaveLength(1))
    expect(calls.uploaded[0]).toMatchObject({ path: '/assets', name: 'own-logo.png', fields: { kind: 'icon' } })
    await waitFor(() => expect(picked).toEqual(['/api/v1/assets/8/own-logo.png']))
  })

  it('asks before it deletes one', async () => {
    render(wrap(<IconPickerDialog open value="" onPick={() => undefined} onClose={() => undefined} />))
    await userEvent.click(await screen.findByRole('button', { name: 'Delete nas.png' }))
    // ⚠️ Nothing is gone yet. Other cards may be drawing this file, and a
    // click on a five-pixel bin next to a tile is easy to make by accident.
    expect(calls.deleted).toEqual([])

    await userEvent.click(screen.getByRole('button', { name: /^Delete$/ }))
    await waitFor(() => expect(calls.deleted).toEqual(['/assets/7']))
  })

  it('says so when nothing matches', async () => {
    render(wrap(<IconPickerDialog open value="" onPick={() => undefined} onClose={() => undefined} />))
    await screen.findByRole('button', { name: 'radarr' })
    await userEvent.type(screen.getByPlaceholderText('Filter by name…'), 'zzqq')
    expect(screen.getByRole('status')).toHaveTextContent('No logo matches "zzqq".')
  })
})
