/**
 * A list row's title is a name and stays as it came, unless the row says it
 * is nexdeck's own wording (`worded`): a finding, the kinds on a volume. The
 * value on the right is translated like a label, and a value with a unit is
 * formatted.
 */
import { render } from '@testing-library/react'
import i18next from 'i18next'

import '../i18n/index'
import de from '../i18n/texts.de.json'
import { registerTexts, type TextBundle } from '../i18n/texts'
import type { WidgetData, WidgetView } from '../lib/types'
import { renderWidget } from './renderers'

const VIEW: WidgetView = {
  id: 1,
  kind: 'nexcrate.findings',
  title: 'Findings',
  icon: '',
  link: '',
  renderer: 'list',
  options: {},
  integration_id: 1,
  refresh_seconds: 30,
}

function rows(items: Record<string, unknown>[]): string[] {
  const data: WidgetData = { status: 'ok', items }
  const { container } = render(<>{renderWidget({ widget: VIEW, data })}</>)
  return [...container.querySelectorAll('li')].map((row) => row.textContent ?? '')
}

describe('list wording', () => {
  beforeAll(() => {
    registerTexts('de', de as TextBundle)
  })
  beforeEach(async () => {
    await i18next.changeLanguage('de')
  })
  afterEach(async () => {
    await i18next.changeLanguage('en')
  })

  it('translates a worded title and leaves a name alone', () => {
    const [finding, name] = rows([
      { title: 'The automatic search for music is off', worded: true },
      { title: 'Stuck', subtitle: 'a film of that name' },
    ])
    expect(finding).toContain('Die automatische Suche für Musik ist aus')
    expect(name).toContain('Stuck')
    expect(name).not.toContain('Hängt')
  })

  it('translates the kinds on a volume and the free space', () => {
    const [volume] = rows([{ title: 'Films · Series', worded: true, subtitle: '73.7 TB free of 125.7 TB', value: 41.4, unit: '%' }])
    expect(volume).toContain('Filme · Serien')
    expect(volume).toContain('73.7 TB frei von 125.7 TB')
    expect(volume).toContain('%')
  })

  it('translates a value in words', () => {
    const [owner, found] = rows([
      { title: 'A', value: 'Needs you' },
      { title: 'B', value: '12 found' },
    ])
    expect(owner).toContain('Braucht dich')
    expect(found).toContain('12 gefunden')
  })
})
