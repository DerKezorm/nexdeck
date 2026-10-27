/**
 * A wall display says what came of a press (KARTEN-8 AC-9): "Done" when it went through and the reason, in the
 * language of the display, when it did not. It once swallowed both.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18next from 'i18next'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'

import deScreen from '../i18n/de.json'
import de from '../i18n/texts.de.json'
import { registerTexts, type TextBundle } from '../i18n/texts'
import { KioskPage } from './KioskPage'

const answers = vi.hoisted(() => ({ next: 'done' as 'done' | 'no_answer' }))
vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {
    status: number
    code: string
    detail: Record<string, unknown> = {}
    constructor(status: number, code: string, message: string) {
      super(message)
      this.status = status
      this.code = code
    }
  },
  get: vi.fn(async (path: string) => {
    if (path === '/kiosk') {
      return {
        id: 1, slug: 'hall', name: 'Hall', icon: '', owner_id: 1, background: { kind: 'bundled', value: 'aurora' }, settings: {},
        provisioned: false, permission: 'act',
        live: { 7: { status: 'ok', meta: { custom: true }, items: [{ id: 'a', title: 'Alpha', actions: [{ id: 'button:pause', label: 'Pause torrent', params: { hash: 'a' } }] }] } },
        pages: [{ id: 1, name: 'One', slug: 'one', icon: '', position: 0, layouts: { lg: [{ i: '7', x: 0, y: 0, w: 6, h: 4 }], md: [{ i: '7', x: 0, y: 0, w: 6, h: 4 }], sm: [{ i: '7', x: 0, y: 0, w: 6, h: 4 }] }, widgets: [
          { id: 7, kind: 'custom.list', title: 'Downloads', icon: '', link: '', renderer: 'list', options: {}, integration_id: 1, refresh_seconds: null },
        ] }],
        kiosk: { cycle_seconds: 0, dim_from: '', dim_to: '', allow_actions: true, name: 'Hall' },
      }
    }
    return {}
  }),
  post: vi.fn(async () => {
    if (answers.next === 'done') return { ok: true, message: 'Done' }
    const { ApiError } = await import('../api/client')
    throw new ApiError(502, 'no_answer', 'No answer. It may have run; check the service.')
  }),
  mediaUrl: () => '',
  openKioskSession: vi.fn(async () => undefined),
}))
vi.mock('../hooks/useStream', () => ({ useStream: () => undefined }))

beforeAll(() => {
  registerTexts('de', de as TextBundle)
  i18next.addResourceBundle('de', 'translation', deScreen, true, true)
})
afterEach(async () => {
  await i18next.changeLanguage('en')
})

function wall() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={['/k']}>
        <Routes>
          <Route path="/k/:token?" element={<KioskPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('a press on a wall display', () => {
  it('karten8 ac9 says Done when it went through', async () => {
    answers.next = 'done'
    wall()
    await userEvent.click(await screen.findByRole('button', { name: 'Pause torrent' }))
    expect(await screen.findByText('Done')).toBeInTheDocument()
  })

  it('karten8 ac9 says why it failed, in the language of the display', async () => {
    answers.next = 'no_answer'
    await i18next.changeLanguage('de')
    wall()
    await userEvent.click(await screen.findByRole('button', { name: 'Pause torrent' }))
    await waitFor(() => expect(screen.getByText((deScreen as { errors: { widget: { no_answer: string } } }).errors.widget.no_answer)).toBeInTheDocument())
    expect(screen.queryByText('No answer. It may have run; check the service.')).toBeNull()
  })
})
