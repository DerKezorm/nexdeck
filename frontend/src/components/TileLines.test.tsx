/**
 * A card that is a tile of key figures offers "Yellow from" and "Red from"
 * whatever its view: the tile draws the number in every view, coloured by
 * those lines. Elsewhere they stay with the dial, the LEDs and the digits.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { inFigures } from '../lib/figures'
import { useEditedPage } from '../lib/groups'
import type { WidgetView } from '../lib/types'
import { WidgetSettingsSheet } from './WidgetSettingsSheet'

const OPTIONS = [
  { name: 'view', label: 'View', type: 'select', default: 'value', options: [{ value: 'value', label: 'The rows' }, { value: 'segments', label: 'Seven segments' }] },
  { name: 'level_warn', label: 'Yellow from', type: 'number', default: null, only_when: ['view', 'gauge|meter|segments'] },
  { name: 'level_bad', label: 'Red from', type: 'number', default: null, only_when: ['view', 'gauge|meter|segments'] },
  { name: 'meter_direction', label: 'LEDs run', type: 'select', default: 'across', options: [{ value: 'across', label: 'Across' }], only_when: ['view', 'meter'] },
]
const CPU = { id: 3, kind: 'core.host', title: 'NAS', icon: '', link: '', renderer: 'stats', options: { view: 'value' }, integration_id: null, refresh_seconds: 15, health: null }
const FIGURES = { id: 9, kind: 'core.figures', title: 'Wall', renderer: 'figures', options: { cards: [3] } }

function answer() {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    const body = url.includes('/adapters')
      ? [{ kind: 'core', label: 'Basics', needs_integration: false, fields: [], widgets: [{ kind: 'core.host', label: 'This machine', renderer: 'stats', options: OPTIONS }] }]
      : url.includes('/integrations') ? [] : {}
    return new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } })
  })
}

function sheet() {
  vi.stubGlobal('fetch', answer())
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <WidgetSettingsSheet widget={CPU as never} pages={[{ id: 1, name: 'one' }]} onClose={vi.fn()} onSaved={vi.fn()} onDeleted={vi.fn()} />
    </QueryClientProvider>,
  )
}

afterEach(() => {
  useEditedPage.setState({ widgets: [] })
  vi.unstubAllGlobals()
})

describe('the lines of a tile', () => {
  it('knows a card that stands in key figures', () => {
    expect(inFigures(3, [CPU, FIGURES] as unknown as WidgetView[])).toBe(true)
    expect(inFigures(3, [CPU, { ...FIGURES, kind: 'core.group' }] as unknown as WidgetView[])).toBe(false)
    expect(inFigures(4, [CPU, FIGURES] as unknown as WidgetView[])).toBe(false)
  })

  it('are offered in the plain view while the card is a tile', async () => {
    useEditedPage.setState({ widgets: [CPU, FIGURES] as unknown as WidgetView[] })
    sheet()
    expect(await screen.findByLabelText(/Yellow from/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Red from/)).toBeInTheDocument()
    // The other settings of a drawing stay with their drawing.
    expect(screen.queryByLabelText(/LEDs run/)).toBeNull()
  })

  it('stay with the drawings of one number on a card of the board', async () => {
    useEditedPage.setState({ widgets: [CPU] as unknown as WidgetView[] })
    sheet()
    expect(await screen.findByText('View')).toBeInTheDocument()
    expect(screen.queryByLabelText(/Yellow from/)).toBeNull()
    expect(screen.queryByLabelText(/Red from/)).toBeNull()
  })
})
