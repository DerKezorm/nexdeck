import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { applyBrand, NO_BRAND, tabTitle } from './brand'

describe('the tab title', () => {
  it('says nexdeck without a name of its own', () => {
    expect(tabTitle(NO_BRAND)).toBe('nexdeck')
    expect(tabTitle(NO_BRAND, 'Home')).toBe('Home · nexdeck')
  })

  it('carries the installation name, with the board in front when wanted', () => {
    expect(tabTitle({ ...NO_BRAND, name: 'Homelab Nord' }, 'Home')).toBe('Home · Homelab Nord')
    expect(tabTitle({ ...NO_BRAND, name: 'Homelab Nord', board_in_title: false }, 'Home')).toBe('Homelab Nord')
  })
})

describe('the icons in the head', () => {
  beforeEach(() => {
    document.head.innerHTML =
      '<link rel="icon" type="image/svg+xml" href="/icon.svg"><link rel="apple-touch-icon" href="/apple-touch-icon.png">' +
      '<link rel="search" type="application/opensearchdescription+xml" href="/opensearch.xml" title="nexdeck">'
  })
  afterEach(() => applyBrand(NO_BRAND))

  const href = (rel: string) => document.head.querySelector(`link[rel="${rel}"]`)?.getAttribute('href')

  it('point at the logo and the drawn app icon', () => {
    applyBrand({ ...NO_BRAND, name: 'Homelab', logo: '/api/v1/brand/logo?v=1', favicon: '/api/v1/brand/logo?v=1', app_icons: { 192: '/api/v1/brand/icon-192.png?v=1', 512: '/api/v1/brand/icon-512.png?v=1' } })
    expect(href('icon')).toBe('/api/v1/brand/logo?v=1')
    expect(document.head.querySelector('link[rel="icon"]')?.hasAttribute('type')).toBe(false)
    expect(href('apple-touch-icon')).toBe('/api/v1/brand/icon-512.png?v=1')
    expect(document.head.querySelector('link[rel="search"]')?.getAttribute('title')).toBe('Homelab')
    expect(href('search')).toBe('/opensearch.xml')
    expect(document.title).toBe('Homelab')
  })

  it('go back to what the build put there when the logo is removed', () => {
    applyBrand({ ...NO_BRAND, logo: '/l', favicon: '/l', app_icons: { 192: '/s', 512: '/b' } })
    applyBrand(NO_BRAND)
    expect(href('icon')).toBe('/icon.svg')
    expect(document.head.querySelector('link[rel="icon"]')?.getAttribute('type')).toBe('image/svg+xml')
    expect(href('apple-touch-icon')).toBe('/apple-touch-icon.png')
    expect(document.head.querySelector('link[rel="search"]')?.getAttribute('title')).toBe('nexdeck')
    expect(document.title).toBe('nexdeck')
  })
})
