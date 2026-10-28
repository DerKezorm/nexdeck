/** A press over MCP in the chronicle: the server's sentence is the line, with the card to open. */
import i18next from 'i18next'
import { describe, expect, it } from 'vitest'

import { lineDetail, lineStatus, lineText, type ChronicleLine } from './chronicle'

const t = (key: string, options?: Record<string, unknown>) => i18next.t(key, options) as string

const press: ChronicleLine = {
  when: 1_792_900_000,
  kind: 'mcp_call',
  level: 'info',
  name: 'Containers',
  before: 'Laptop (MCP)',
  after: 'Restart',
  detail: 'Restart on Containers by Laptop (MCP), approved by Sam',
  board: 'Lab',
}

describe('the chronicle line of a press over MCP', () => {
  it('reads as the whole sentence the server wrote', () => {
    expect(lineText(press, t, 'en')).toBe('Restart on Containers by Laptop (MCP), approved by Sam')
  })

  it('falls back to the card name when the sentence is missing', () => {
    expect(lineText({ ...press, detail: '' }, t, 'en')).toBe('Containers')
  })

  it('is news, not a fault: grey dot, no second line', () => {
    expect(lineStatus(press)).toBe('unknown')
    expect(lineDetail(press, t)).toBe('')
  })
})
