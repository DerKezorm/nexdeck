/**
 * The import dialog with what the server really answers (`src/test/karten12Answers.json`): replacing an own integration
 * whose fields change warns about the stored values it throws away (KARTEN-12 AC-3, KARTEN-3 EC-10).
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import answers from '../../test/karten12Answers.json'
import { ImportDialog } from './ImportDialog'

function stub(check: unknown) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input).replace(/^.*\/api\/v1/, '')
      const json = (value: unknown) => new Response(JSON.stringify(value), { status: 200, headers: { 'content-type': 'application/json' } })
      return json(init?.method === 'POST' && url === '/cards/import/check' ? check : [])
    }),
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('the import dialog with the answers of the server', () => {
  it('karten12 ac3: replacing an integration that loses a field says which, and that its stored values go, secrets included', async () => {
    stub(answers.cards_check_dropped)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <ImportDialog open onClose={() => undefined} onDone={() => undefined} />
      </QueryClientProvider>,
    )
    await userEvent.click(screen.getByRole('textbox', { name: 'Or paste the text' }))
    await userEvent.paste(answers.integration_renamed)
    await userEvent.click(screen.getByRole('button', { name: 'Check' }))
    const warning = await screen.findByTestId('import-drops-integration:bookstack-own')
    expect(warning).toHaveTextContent('Replace throws away the fields token_secret: what the connections of this kind keep in them, secrets included, is deleted.')
    const conflict = screen.getByTestId('import-conflict-integration:bookstack-own')
    await userEvent.click(within(conflict).getByRole('radio', { name: 'Replace' }))
    expect(warning).toHaveClass('text-bad')
  })
})
