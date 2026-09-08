/**
 * The media list: what is on the server, what still shows it, and what
 * deleting one costs.
 *
 * ⚠️ Nothing here existed. Files could go onto the server and never come off,
 * and the upload quota's own message said "delete a file you no longer need"
 * about something nobody could reach.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { MediaSettings, humanSize } from './MediaSettings'

const calls = vi.hoisted(() => ({
  deleted: [] as string[],
  files: [] as unknown[],
}))

vi.mock('../../api/client', () => ({
  ApiError: class ApiError extends Error {},
  get: vi.fn(async () => calls.files),
  upload: vi.fn(async () => ({})),
  del: vi.fn(async (path: string) => {
    calls.deleted.push(path)
    return {}
  }),
}))

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MediaSettings />
    </QueryClientProvider>,
  )
}

describe('humanSize', () => {
  it('counts up in the unit that fits', () => {
    expect(humanSize(512)).toBe('512 B')
    expect(humanSize(2048)).toBe('2 kB')
    expect(humanSize(5 * 1024 * 1024)).toBe('5.0 MB')
  })
})

describe('MediaSettings', () => {
  beforeEach(() => {
    calls.deleted.length = 0
    calls.files = [
      { id: 1, kind: 'picture', filename: 'rack.png', size: 253_000, url: '/api/v1/assets/1/rack.png', created_at: '2026-09-08T10:00:00Z', used_by: [{ what: 'widget', name: 'The rack' }] },
      { id: 2, kind: 'picture', filename: 'spare.png', size: 12_000, url: '/api/v1/assets/2/spare.png', created_at: '2026-09-08T10:00:00Z', used_by: [] },
    ]
  })

  it('says of every file whether anything still shows it', async () => {
    show()
    expect(await screen.findByText('rack.png')).toBeInTheDocument()
    expect(screen.getByText('Used by The rack')).toBeInTheDocument()
    expect(screen.getByText('Not used')).toBeInTheDocument()
  })

  it('names what would go blank before it deletes one', async () => {
    // ⚠️ The point of the whole screen. A file deleted out from under a wall
    // display leaves a hole nobody is standing next to.
    show()
    await userEvent.click(await screen.findByRole('button', { name: 'Delete rack.png' }))
    expect(screen.getByText(/still shown by: The rack/)).toBeInTheDocument()
    expect(calls.deleted).toEqual([])

    await userEvent.click(screen.getByRole('button', { name: /^Delete$/ }))
    await waitFor(() => expect(calls.deleted).toEqual(['/assets/1?anyway=true']))
  })

  it('asks no second question about a file nobody shows', async () => {
    show()
    await userEvent.click(await screen.findByRole('button', { name: 'Delete spare.png' }))
    expect(screen.getByText(/Nothing shows this file/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /^Delete$/ }))
    // ⚠️ Without "anyway": the server refuses that word for a file in use, so
    // sending it always would make the refusal unreachable from here.
    await waitFor(() => expect(calls.deleted).toEqual(['/assets/2']))
  })

  it('adds up what is lying there', async () => {
    show()
    expect(await screen.findByText(/2 file/)).toHaveTextContent('259 kB')
  })

  it('says so when nothing has been uploaded', async () => {
    calls.files = []
    show()
    expect(await screen.findByText('Nothing uploaded yet.')).toBeInTheDocument()
  })
})
