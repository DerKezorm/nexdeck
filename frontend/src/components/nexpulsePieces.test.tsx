/**
 * The one shared piece nexpulse needed: a button pointed at an action that
 * acts on the whole connection. Its target list brings its own empty entry,
 * and the dropdown must not put "Not picked" on top of it.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { FieldSpec } from '../api/types'
import { FieldInput } from './FieldInput'

const WHOLE = 'Nothing to pick, it acts on the whole connection'

vi.mock('../api/client', () => ({
  ApiError: class extends Error {},
  get: vi.fn(async (path: string) => {
    if (path === '/integrations/7/choices/target') return [{ value: '', label: WHOLE }]
    if (path === '/integrations/8/choices/target') return [{ value: 'lib-1', label: 'Films' }]
    throw new Error(`unexpected request ${path}`)
  }),
}))

function target(integrationId: number) {
  const spec = {
    name: 'target', label: 'What it acts on', type: 'choices', required: false, secret: false,
    default: null, help: '', placeholder: '', options: [], from_field: 'service',
  } as unknown as FieldSpec
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <FieldInput spec={spec} value="" onChange={() => {}} integrationId={integrationId} />
    </QueryClientProvider>,
  )
}

describe('a button target list', () => {
  it('shows the empty entry an action brings, and no second one', async () => {
    target(7)
    const offered = await screen.findAllByRole('option')
    expect(offered.map((one) => one.textContent)).toEqual([WHOLE])
  })

  it('keeps "Not picked" above a list of real targets', async () => {
    target(8)
    const offered = await screen.findAllByRole('option')
    expect(offered.map((one) => one.textContent)).toEqual(['Not picked', 'Films'])
  })
})
