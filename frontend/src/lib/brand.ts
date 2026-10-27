/**
 * The name and the logo of the installation, where nexdeck's own would stand.
 *
 * Read once at the start, signed in or not: the sign-in page and the browser
 * tab need them before anybody signs in. Empty means nexdeck, as always.
 */
import { useEffect } from 'react'
import { create } from 'zustand'

import { get, serverUrl } from '../api/client'
import type { Appearance } from './appearance'

export interface Brand {
  name: string
  /** Addresses, each with the logo's stamp in it; null where nexdeck's own mark stays. */
  logo: string | null
  favicon: string | null
  app_icons: Record<'192' | '512', string> | null
  board_in_title: boolean
  /** The part of the look a page is drawn in before anybody signs in. */
  look?: Appearance | null
}

export const NO_BRAND: Brand = { name: '', logo: null, favicon: null, app_icons: null, board_in_title: true }

export const useBrand = create<Brand>(() => NO_BRAND)

/** The name the installation goes by: its own, else nexdeck. */
export function shownName(brand: Brand): string {
  return brand.name || 'nexdeck'
}

/** What the browser tab says, with the board in front when the operator wants it there. */
export function tabTitle(brand: Brand, board?: string): string {
  const name = shownName(brand)
  return board && brand.board_in_title ? `${board} · ${name}` : name
}

/** A ``<link>`` in the head, pointed somewhere else, or back to where the build put it. */
function relink(rel: string, href: string | null): void {
  const link = document.head.querySelector<HTMLLinkElement>(`link[rel="${rel}"]`)
  if (!link) return
  if (!link.dataset.built) link.dataset.built = link.getAttribute('href') ?? ''
  link.setAttribute('href', href ? serverUrl(href) : link.dataset.built)
  // nexdeck's own mark is an SVG; a logo can be a PNG or a WebP as well.
  if (rel === 'icon') {
    if (href) link.removeAttribute('type')
    else link.setAttribute('type', 'image/svg+xml')
  }
}

/** The tab icon, the home-screen icon and the title, from the brand. */
export function applyBrand(brand: Brand): void {
  useBrand.setState(brand, true)
  relink('icon', brand.favicon)
  relink('apple-touch-icon', brand.app_icons?.['512'] ?? null)
  // The name a browser offers nexdeck under as a search engine (``/opensearch.xml`` says the same).
  document.head.querySelector('link[rel="search"]')?.setAttribute('title', shownName(brand))
  document.title = tabTitle(brand)
}

export async function loadBrand(): Promise<void> {
  try {
    applyBrand({ ...NO_BRAND, ...(await get<Brand>('/brand')) })
  } catch {
    // Without an answer it is nexdeck, as it always was.
  }
}

/** For a page that shows a board: its name in front of the installation's in the tab. */
export function useTabTitle(board?: string): void {
  const brand = useBrand()
  useEffect(() => {
    document.title = tabTitle(brand, board)
    return () => {
      document.title = tabTitle(brand)
    }
  }, [brand, board])
}
