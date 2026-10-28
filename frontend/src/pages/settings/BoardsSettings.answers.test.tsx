/**
 * The board import against what the server really answers (`src/test/karten12Answers.json`, written and checked by the
 * backend test `test_karten12_answers.py`), KARTEN-12 AC-6, AC-7.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useAuth } from '../../stores/auth'
import answers from '../../test/karten12Answers.json'
import { BoardsSettings } from './BoardsSettings'

function stub(check: unknown, imported: unknown = {}) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input).replace(/^.*\/api\/v1/, '')
      const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json' } })
      if (init?.method === 'POST' && url === '/boards/import/check') return json(check)
      if (init?.method === 'POST' && url === '/boards/import') return json(imported, 201)
      return json([])
    }),
  )
}

async function show(role: 'admin' | 'user', text: string = answers.board_file) {
  useAuth.setState({ user: { id: role === 'admin' ? 1 : 2, username: role, role } as never })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/settings/boards']}>
        <Routes>
          <Route path="/settings/boards" element={<BoardsSettings />} />
          <Route path="/b/:slug" element={<p>The new board</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  const field = await screen.findByRole('textbox', { name: 'Import a board' })
  await userEvent.click(field)
  await userEvent.paste(text)
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

  it('karten12 ac6: after the import an administrator reads what was created, what was here already and what stays his own', async () => {
    stub(answers.board_check_admin, answers.board_import_admin)
    await show('admin', answers.board_file_good)
    await userEvent.click(screen.getAllByRole('button', { name: 'Import' }).at(-1)!)
    const report = await screen.findByTestId('board-import-report')
    expect(within(report).getAllByRole('listitem').map((one) => one.textContent)).toEqual([
      'Created: brand-new, bookstack-own',
      'Already here: exists-same',
      'Already here with other content, yours is kept: exists-diff',
    ])
    await userEvent.click(within(report).getByRole('button', { name: 'Open the board' }))
    expect(await screen.findByText('The new board')).toBeInTheDocument()
  })

  it('karten12 ac7: somebody who is not an administrator reads that nothing was created and who can create it', async () => {
    stub(answers.board_check_member, answers.board_import_member)
    await show('user', answers.board_file_good)
    await userEvent.click(screen.getAllByRole('button', { name: 'Import' }).at(-1)!)
    const report = await screen.findByTestId('board-import-report')
    expect(within(report).getAllByRole('listitem').map((one) => one.textContent)).toEqual(['Not created: exists-same, exists-diff, brand-new, bookstack-own'])
    expect(report).toHaveTextContent('An administrator can create the missing ones.')
  })
})
