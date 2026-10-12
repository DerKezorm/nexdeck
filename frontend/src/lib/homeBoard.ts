import { useQuery } from '@tanstack/react-query'

import { get } from '../api/client'
import type { BoardSummary } from '../api/types'
import { useAuth } from '../stores/auth'

/**
 * Where "home" is: the start board, or the first board the user may see.
 *
 * ``without`` leaves out a board that is about to be deleted, so the way home
 * never leads back to it. With no board left, home is ``/`` and its empty page.
 */
export function homeBoardPath(boards: BoardSummary[], startBoardId: number | null | undefined, without?: number): string {
  const list = boards.filter((entry) => entry.id !== without)
  const start = list.find((entry) => entry.id === startBoardId) ?? list[0]
  return start ? `/b/${start.slug}` : '/'
}

/**
 * The path of the home board, for a link that goes there directly.
 *
 * ⚠️ **Not ``/``** from a board. ``/`` is a page of its own that only passes
 * the user on, and for that moment there is no bar on the page. The app
 * installed on iPadOS 26 blurs the top of the page whenever it finds no solid
 * bar there, and the blur stays (#27, #40: deleting a board went home that way).
 * A board to a board keeps the same bar.
 */
export function useHomeBoardPath(without?: number): string {
  const startBoardId = useAuth((s) => s.user?.start_board_id)
  const boards = useQuery({ queryKey: ['boards'], queryFn: () => get<BoardSummary[]>('/boards') })
  return homeBoardPath(boards.data ?? [], startBoardId, without)
}
