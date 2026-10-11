/**
 * A row of the problems card names the findings of the card it stands for
 * (issue #35). Each part is translated on its own, a name stays a name, and
 * "+N more" says that the card has more than the row shows.
 */
import { render } from '@testing-library/react'
import i18next from 'i18next'

import { setLanguage } from '../i18n/index'
import type { WidgetData, WidgetView } from '../lib/types'
import { renderWidget } from './renderers'

const VIEW: WidgetView = {
  id: 1,
  kind: 'core.problems',
  title: 'Problems',
  icon: '',
  link: '',
  renderer: 'list',
  options: {},
  integration_id: null,
  refresh_seconds: 30,
}

const ROW = {
  title: 'Jellyfin',
  status: 'bad',
  subtitle: 'Intro Skipper: Plugin malfunctioned · Jellyfin: A restart is pending · +2 more',
  findings: [
    { title: 'Intro Skipper', subtitle: 'Plugin malfunctioned', worded: false },
    { title: 'Jellyfin', subtitle: 'A restart is pending', worded: false },
  ],
  more: 2,
  url: 'http://jellyfin.example.com/',
}

function row(item: Record<string, unknown>): HTMLElement {
  const data: WidgetData = { status: 'bad', items: [item] }
  const { container } = render(<>{renderWidget({ widget: VIEW, data })}</>)
  return container.querySelector('li') as HTMLElement
}

describe('problems card findings', () => {
  afterEach(async () => {
    await i18next.changeLanguage('en')
  })

  it('names the findings and how many more, in English', () => {
    expect(row(ROW).textContent).toContain('Intro Skipper: Plugin malfunctioned · Jellyfin: A restart is pending · +2 more')
  })

  it('translates each finding and the count, and leaves the names alone', async () => {
    await setLanguage('de')
    expect(row(ROW).textContent).toContain('Intro Skipper: Plugin gestört · Jellyfin: Ein Neustart steht aus · +2 weitere')
  })

  it('says nothing of more when the row shows everything', () => {
    const text = row({ ...ROW, findings: ROW.findings.slice(1), more: 0 }).textContent ?? ''
    expect(text).toContain('Jellyfin: A restart is pending')
    expect(text).not.toContain('more')
  })

  it('leads to the card behind it', () => {
    const link = row(ROW).querySelector('a')
    expect(link?.getAttribute('href')).toBe('http://jellyfin.example.com/')
  })
})
