import { describe, expect, it } from 'vitest'

import type { BoardSummary } from '../api/types'
import { homeBoardPath } from './homeBoard'

const board = (id: number, slug: string) => ({ id, slug, name: slug }) as BoardSummary

describe('homeBoardPath', () => {
  const boards = [board(1, 'home'), board(2, 'media'), board(3, 'office')]

  it('leads to the start board', () => {
    expect(homeBoardPath(boards, 2)).toBe('/b/media')
  })

  it('leads to the first board without a start board, or when it is gone', () => {
    expect(homeBoardPath(boards, null)).toBe('/b/home')
    expect(homeBoardPath(boards, 99)).toBe('/b/home')
  })

  it('never leads back to the board being deleted', () => {
    expect(homeBoardPath(boards, 2, 2)).toBe('/b/home')
    expect(homeBoardPath(boards, null, 1)).toBe('/b/media')
  })

  it('is the empty page only when no board is left', () => {
    expect(homeBoardPath([board(1, 'home')], 1, 1)).toBe('/')
    expect(homeBoardPath([], null)).toBe('/')
  })
})
