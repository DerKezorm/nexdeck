/** W2 (Etappe 8), on the way: the list of changes in the detail of an entry is set like the one in the update dialog, every section of it. */
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18next from 'i18next'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { entry, renderWith, reset, STATE_ON, stub, world } from '../../../test/shopWorld'
import { ShopTab } from './ShopTab'

const PATH = '/workshop/entries/123/queue-size'

beforeEach(() => {
  localStorage.clear()
  reset([entry()], STATE_ON)
  stub()
})
afterEach(async () => {
  vi.unstubAllGlobals()
  await i18next.changeLanguage('en')
})

describe('the list of changes in the detail', () => {
  it('karten16w2_changelog: every section is set as a small heading, text and a list, and nothing is raw', async () => {
    world.given[`GET ${PATH}`] = {
      status: 200,
      body: {
        ...entry(),
        readme: null,
        files_warning: null,
        offered_integrations: [],
        changelog: '# Changelog\n\n## 1.2.0 (2026-10-28)\n\n- Faster list\n- New icon\n\nReads one request less.\n\n## 1.0.0 (2026-10-01)\n\nFirst version <b>bold</b>.\n',
      },
    }
    renderWith(<ShopTab />)
    await userEvent.click(await screen.findByText('Queue size'))
    const log = await screen.findByTestId('shop-changelog')
    expect(within(log).getAllByRole('heading').map((one) => one.textContent)).toEqual(['1.2.0 (2026-10-28)', '1.0.0 (2026-10-01)'])
    expect(within(log).getAllByRole('listitem').map((one) => one.textContent)).toEqual(['Faster list', 'New icon'])
    expect(within(log).getByText('Reads one request less.')).toBeInTheDocument()
    expect(log).not.toHaveTextContent('## ')
    expect(log).not.toHaveTextContent('- Faster')
    expect(log).not.toHaveTextContent('# Changelog')
    expect(log.querySelector('b')).toBeNull()
    expect(log).toHaveTextContent('First version <b>bold</b>.')
  })
})
