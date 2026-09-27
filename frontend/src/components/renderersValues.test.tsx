/**
 * Words the server sends as a value are translated like labels, numbers are
 * formatted. The chips and the rows of a card showed "just now" and the note
 * that a token reads one namespace in English in every language, although
 * the tables had them.
 */
import { render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { DEMO_VIEWS } from '../demo/board'
import { setLanguage } from '../i18n'
import { formatValue } from '../lib/format'
import type { WidgetData, WidgetView } from '../lib/types'
import { renderWidget } from './renderers'

const data = {
  status: 'ok',
  primary: { label: 'Living room', value: 21.5, unit: '°C' },
  secondary: [
    { label: 'Updated', value: 'just now' },
    { label: 'Allocated', value: 'unknown: the token reads one namespace' },
    { label: 'Traffic', value: 3.2, unit: 'MB/s' },
  ],
} as unknown as WidgetData

describe('values on a card', () => {
  beforeEach(async () => {
    await setLanguage('de')
  })
  afterEach(async () => {
    await setLanguage('en')
  })

  it('are translated in the chips under a single value', () => {
    const view = { ...DEMO_VIEWS[0], id: 21, renderer: 'value' } as WidgetView
    render(<>{renderWidget({ widget: view, data })}</>)
    expect(screen.getByText('gerade eben')).toBeTruthy()
    expect(screen.queryByText('just now')).toBeNull()
    // A number with its unit is left to the formatting, not to the tables.
    expect(document.body.textContent).toContain(formatValue(3.2, 'MB/s'))
  })

  it('are translated in the rows of a stats card', () => {
    const view = { ...DEMO_VIEWS[0], id: 22, renderer: 'stats' } as WidgetView
    render(<>{renderWidget({ widget: view, data })}</>)
    expect(screen.getByText('unbekannt: das Token liest nur einen Namensraum')).toBeTruthy()
    // A number with its unit is left to the formatting, not to the tables.
    expect(document.body.textContent).toContain(formatValue(3.2, 'MB/s'))
  })
})
