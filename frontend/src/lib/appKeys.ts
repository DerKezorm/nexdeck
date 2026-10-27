/**
 * Number keys for app tiles: on the board, 1 to 9 opens the tile that has
 * the key, as a click on it would, and ? shows the keys as small marks on
 * the tiles and hides them again.
 *
 * A key belongs to one tile per board (``services/app_keys.py``), so it
 * opens the same tile whichever page is in view.
 *
 * ⚠️ Not shown by holding Alt, which is the usual way: browsers on Windows
 * take Alt for their own menu bar, and the marks flickered or never came.
 */
import type { TFunction } from 'i18next'
import { useEffect, useRef } from 'react'
import { create } from 'zustand'

import { ApiError } from '../api/client'
import { safeUrl } from './safeUrl'
import type { WidgetData, WidgetView } from './types'

export const KEYS = ['1', '2', '3', '4', '5', '6', '7', '8', '9']

/** The key of a tile, or an empty string. */
export function keyOf(widget: WidgetView): string {
  const key = String(widget.options?.key ?? '')
  return widget.kind === 'core.app' && KEYS.includes(key) ? key : ''
}

/**
 * Where a tile leads and whether it opens a tab of its own: the one rule for
 * the click on the tile and for its key.
 *
 * ⚠️ ``data.link`` comes from the service, not from the operator, so the
 * address goes through ``safeUrl`` like every other on a card.
 */
export function appTarget(widget: WidgetView, data: WidgetData | undefined): { href: string | undefined; newTab: boolean } {
  const href = safeUrl(widget.link || data?.link || widget.service_link) || undefined
  return { href, newTab: Boolean(href) && data?.meta?.open_new_tab !== false }
}

/** Whether the marks are shown. Kept per board page, gone when it is left. */
export const useKeyMarks = create<{ shown: boolean; set: (shown: boolean) => void }>((store) => ({
  shown: false,
  set: (shown) => store({ shown }),
}))

/**
 * Whether a key press is free for the board: not typed into a field, not
 * with Ctrl, Alt or Meta (those are the browser's and the system's), and
 * nothing open over the board that the key belongs to instead.
 */
export function freeForTheBoard(event: KeyboardEvent): boolean {
  if (event.ctrlKey || event.altKey || event.metaKey || event.defaultPrevented || event.repeat) return false
  const target = event.target as HTMLElement | null
  if (target?.closest?.('input, textarea, select, [contenteditable="true"], [contenteditable=""]')) return false
  // A dialog, a sheet, the search: everything that stands over the board says so.
  return !document.querySelector('[role="dialog"], [role="menu"], [aria-modal="true"]')
}

/** Leaving the page for a tile's address; an object so a test can stand in for the browser. */
export const leave = { to: (href: string) => window.location.assign(href) }

/** Opens a tile as its click would: in a tab of its own, or in this one. */
export function openTile(widget: WidgetView, data: WidgetData | undefined): boolean {
  const { href, newTab } = appTarget(widget, data)
  if (!href) return false
  if (newTab) window.open(href, '_blank', 'noopener,noreferrer')
  else leave.to(href)
  return true
}

/**
 * The keys on a board page: a digit opens its tile, ? shows and hides the
 * marks. Off while ``enabled`` is false: while the board is arranged and
 * while the search is open.
 */
export function useAppKeys(enabled: boolean, tiles: WidgetView[], data: Record<number, WidgetData | undefined>): void {
  const latest = useRef({ tiles, data })
  useEffect(() => {
    latest.current = { tiles, data }
  })
  useEffect(() => {
    if (!enabled) return
    const press = (event: KeyboardEvent) => {
      if (!freeForTheBoard(event)) return
      if (event.key === '?') {
        event.preventDefault()
        useKeyMarks.getState().set(!useKeyMarks.getState().shown)
        return
      }
      if (!KEYS.includes(event.key)) return
      const tile = latest.current.tiles.find((one) => keyOf(one) === event.key)
      if (tile && openTile(tile, latest.current.data[tile.id])) event.preventDefault()
    }
    window.addEventListener('keydown', press)
    return () => window.removeEventListener('keydown', press)
  }, [enabled])
  // Marks left on would greet the next board, and a wall display never.
  useEffect(() => () => useKeyMarks.getState().set(false), [])
}

/**
 * The refusal of a key another tile has, in the reader's language with the
 * name of that tile; any other failure as the server worded it.
 */
export function failureText(failure: unknown, t: TFunction): string {
  if (!(failure instanceof ApiError)) return t('errors.network')
  if (failure.code === 'key_taken') return t('widget.keyTaken', { key: String(failure.detail.key ?? ''), name: String(failure.detail.name ?? '') })
  return failure.message
}
