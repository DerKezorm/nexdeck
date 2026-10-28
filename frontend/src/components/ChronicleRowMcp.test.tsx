/** A press over MCP in a chronicle row: it fetches its own words and is drawn again in the reader's language. */
import i18next from 'i18next'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it } from 'vitest'

import type { ChronicleLine } from '../lib/chronicle'
import { ChronicleRow } from './ChronicleLines'

const line: ChronicleLine = {
  id: 5,
  when: Date.now() / 1000 - 60,
  kind: 'mcp_call',
  level: 'info',
  name: 'Containers',
  before: 'Laptop (MCP)',
  after: 'Restart',
  detail: 'Restart on Containers by Laptop (MCP), approved by Sam',
  user: 'Sam',
  board: 'Lab',
}

afterEach(async () => {
  await i18next.changeLanguage('en')
})

describe('a press over MCP in a chronicle row', () => {
  it('is told in German once the German MCP words have arrived', async () => {
    await i18next.changeLanguage('de')
    render(
      <MemoryRouter>
        <ChronicleRow line={line} />
      </MemoryRouter>,
    )
    await waitFor(() => expect(screen.getByText(/auf Containers durch Laptop \(MCP\), erlaubt von Sam/)).toBeInTheDocument())
  })
})
