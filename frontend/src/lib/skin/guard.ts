/**
 * Where no skin reaches: pages that ask for a password, a key or a secret, that
 * hand out rights, and the look's own settings, so a broken skin can never lock
 * anyone out of the page that would switch it off.
 *
 * The mark is `data-skin-guard` on <html>. Every rule a skin brings starts with
 * `:root[data-skin=…]:not([data-skin-guard])` (backend/app/skins/css.py), so on
 * these pages none applies, and a dialog that opens from here (a portal into
 * <body>) is covered as well. The colours of the first layer stay: they live in
 * the theme, are checked for contrast and cannot hide anything.
 *
 * A confirmation carries the mark itself (`Dialog` with `alert` in ui.tsx), so
 * a skin can never redraw "Delete" on any page. 1984 is nexdeck's own sheet and
 * not fenced: it drew the sign-in page before there were skins, on purpose.
 */
import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'

export const GUARD = 'data-skin-guard'

/** The pages, by their address; a section of the settings by its whole path. */
export const GUARDED: RegExp[] = [
  /^\/login\/?$/,
  /^\/setup\/?$/,
  /^\/reset\//,
  /^\/connect\/?$/,
  /^\/mcp\/requests\//,
  /^\/settings\/?$/,
  /^\/settings\/(tokens|mcp)\/?$/,
  /^\/system\/(users|sign-in|mcp|integrations|mail|assistant|backups|appearance|skins)(\/|$)/,
]

export function guarded(path: string): boolean {
  return GUARDED.some((pattern) => pattern.test(path))
}

/** Inside the router: the mark follows the page shown. */
export function useSkinGuard(): void {
  const { pathname } = useLocation()
  useEffect(() => {
    const root = document.documentElement
    if (guarded(pathname)) root.setAttribute(GUARD, '')
    else root.removeAttribute(GUARD)
  }, [pathname])
}

export function SkinGuard(): null {
  useSkinGuard()
  return null
}
