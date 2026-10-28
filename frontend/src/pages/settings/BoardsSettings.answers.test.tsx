/**
 * The board import against what the server really answers (`src/test/karten12Answers.json`, written and checked by the
 * backend test `test_karten12_answers.py`), KARTEN-12 AC-6, AC-7.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useAuth } from '../../stores/auth'
import answers from '../../test/karten12Answers.json'
import { BoardsSettings } from './BoardsSettings'

function stub(check: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input).replace(/^.*\/api\/v1/, '')
      const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json' } })
      if (init?.method === 'POST' && url === '/boards/import/check') return json(check)
      return json([])
    }),
  )
}

async function show(role: 'admin' | 'user') {
  useAuth.setState({ user: { id: role === 'admin' ? 1 : 2, username: role, role } as never })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <BoardsSettings />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  const field = await screen.findByRole('textbox', { name: 'Import a board' })
  await userEvent.click(field)
  await userEvent.paste(answers.board_file)
  return screen.findByTestId('board-definitions')
}

/** The rows of the section, each as its text, without the lists of problems inside them. */
const rows = (section: HTMLElement) =>
  Array.from(section.querySelectorAll(':scope > ul > li')).map((one) =>
    Array.from(one.children)
      .filter((child) => child.tagName !== 'UL')
      .map((child) => child.textContent)
      .join(''),
  )

afterEach(() => vi.unstubAllGlobals())

describe('the board import with the answers of the server', () => {
  it('karten12 ac6: a definition with a problem says that it cannot be created, and why, in a sentence', async () => {
    stub(answers.board_check_admin)
    const section = await show('admin')
    expect(rows(section)).toEqual([
      'CardQueuealready here',
      'CardQueuediffers, yours is kept',
      'CardQueuemissing',
      'CardQueuecannot be created',
      'IntegrationBookStackmissing',
    ])
    const problems = within(section).getByRole('list', { name: 'Problems' })
    expect(problems).toHaveTextContent(/^Line 15: /)
    expect(section.textContent).not.toContain('cards.exchange')
  })

  it('karten12 ac7: somebody who is not an administrator learns that it cannot be created, and nothing about what is here', async () => {
    stub(answers.board_check_member)
    const section = await show('user')
    expect(rows(section)).toEqual(['CardQueuein this file', 'CardQueuein this file', 'CardQueuein this file', 'CardQueuecannot be created', 'IntegrationBookStackin this file'])
    expect(section.textContent).not.toContain('cards.exchange')
  })
})
