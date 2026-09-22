/**
 * The overview lists symbols and every logo name, filters as you type, and a
 * click hands the chosen name back and closes. The name index is fetched
 * once; the filtering never waits for the network.
 *
 * ⚠️ Every role query is asked inside the part of the dialog it is about.
 * Asked of the whole screen, one cost 35 ms warm and 130 ms cold in jsdom,
 * because the visibility check reads the computed style of all 430 elements;
 * inside one section it cost under a millisecond (measured on 22.09.2026). On
 * a machine busy with the backend suite the first test ran past its five
 * seconds, and a findByRole of the next ones gave up after one second, before
 * a single pass over the screen had finished.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'

import { IconPickerDialog } from './IconPickerDialog'

const NAS = { id: 7, filename: 'nas.png', url: '/api/v1/assets/7/nas.png' }
const calls = vi.hoisted(() => ({
  uploaded: [] as { path: string; name: string; fields: Record<string, string> }[],
  deleted: [] as string[],
  own: [] as { id: number; filename: string; url: string }[],
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

/** The section under a heading, found by its text, which needs no style. */
function section(heading: string): HTMLElement {
  return screen.getByText(heading, { selector: 'h3' }).closest('section') as HTMLElement
}

function wrap(children: ReactNode) {
  return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>
}

describe('IconPickerDialog', () => {
  // Each test starts from the same installation: deleting the upload in one
  // must not decide what the next one finds.
  beforeEach(() => {
    calls.uploaded.length = 0
    calls.deleted.length = 0
    calls.own = [NAS]
  })

  it('lists every logo and symbol, filters by name and hands the pick back', async () => {
    const picked: string[] = []
    let closed = 0
    render(wrap(<IconPickerDialog open value="" onPick={(name) => picked.push(name)} onClose={() => (closed += 1)} />))
    const overview = await screen.findByTestId('icon-overview')
    await waitFor(() => expect(overview.querySelectorAll('button')).toHaveLength(4))
    expect(within(overview).getByRole('button', { name: 'nexview' })).toBeInTheDocument()
    // Symbols come from the curated lucide set. By title: sixty tiles make a
    // role query here cost more than the rest of the test, and the tile that
    // draws them is the one whose name the logo above has just proved.
    expect(within(section('Symbols')).getByTitle('rss')).toBeInTheDocument()

    await userEvent.type(screen.getByPlaceholderText('Filter by name…'), 'rad')
    expect(overview.querySelectorAll('button')).toHaveLength(2)
    expect(within(overview).queryByRole('button', { name: 'sonarr' })).toBeNull()
    expect(screen.queryByTitle('rss')).toBeNull()

    await userEvent.click(within(overview).getByRole('button', { name: 'radarr-4k' }))
    expect(picked).toEqual(['radarr-4k'])
    expect(closed).toBe(1)
  })

  it('offers what this installation uploaded, before the collections', async () => {
    const picked: string[] = []
    render(wrap(<IconPickerDialog open value="" onPick={(name) => picked.push(name)} onClose={() => undefined} />))
    const own = await within(section('Your own')).findByRole('button', { name: 'nas.png' })
    await userEvent.click(own)
    // ⚠️ The address, not the file name. An uploaded icon is reached by its
    // own address; the name is only what it is called on disk.
    expect(picked).toEqual(['/api/v1/assets/7/nas.png'])
  })

  it('uploads a file and takes it straight away', async () => {
    const picked: string[] = []
    render(wrap(<IconPickerDialog open value="" onPick={(name) => picked.push(name)} onClose={() => undefined} />))
    await within(await screen.findByTestId('icon-overview')).findByRole('button', { name: 'radarr' })
    await userEvent.upload(screen.getByLabelText('Upload'), new File(['x'], 'own-logo.png', { type: 'image/png' }))

    await waitFor(() => expect(calls.uploaded).toHaveLength(1))
    expect(calls.uploaded[0]).toMatchObject({ path: '/assets', name: 'own-logo.png', fields: { kind: 'icon' } })
    await waitFor(() => expect(picked).toEqual(['/api/v1/assets/8/own-logo.png']))
  })

  it('asks before it deletes one', async () => {
    render(wrap(<IconPickerDialog open value="" onPick={() => undefined} onClose={() => undefined} />))
    await userEvent.click(await within(section('Your own')).findByRole('button', { name: 'Delete nas.png' }))
    // ⚠️ Nothing is gone yet. Other cards may be drawing this file, and a
    // click on a five-pixel bin next to a tile is easy to make by accident.
    expect(calls.deleted).toEqual([])

    const confirm = screen.getByText(/Cards still using this file/).closest('[role="dialog"]') as HTMLElement
    await userEvent.click(within(confirm).getByRole('button', { name: /^Delete$/ }))
    await waitFor(() => expect(calls.deleted).toEqual(['/assets/7']))
  })

  it('says so when nothing matches', async () => {
    render(wrap(<IconPickerDialog open value="" onPick={() => undefined} onClose={() => undefined} />))
    const overview = await screen.findByTestId('icon-overview')
    await within(overview).findByRole('button', { name: 'radarr' })
    const logos = overview.closest('section') as HTMLElement
    // By its name, not by its example: a placeholder is not a name, and some screen readers skip it.
    await userEvent.type(screen.getByLabelText('Filter by name…'), 'zzqq')
    expect(within(logos).getByRole('status')).toHaveTextContent('No logo matches "zzqq".')
  })
})
