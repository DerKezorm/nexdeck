/* The icons for the home screen and notifications, rendered once from the light version of the mark.
 *
 * Same shape as components/Logo.tsx and public/icon.svg; the source of every version is nexapps/icons-vergleich/neu.py.
 * Rendered with Playwright, which the end-to-end tests bring anyway:  node tools/app-icons.mjs
 *
 * The maskable icon is cropped by Android, so the mark sits smaller on a full white square. The Apple touch icon is
 * full bleed: iOS rounds it itself. The badge is one colour: Android tints everything that is not transparent.
 */
import { chromium } from '@playwright/test'

const GRADIENT = `<defs><linearGradient id="g" gradientUnits="userSpaceOnUse" x1="10" y1="10" x2="54" y2="54">
  <stop offset="0" stop-color="#67e8f9"/><stop offset=".5" stop-color="#06b6d4"/><stop offset="1" stop-color="#0e7490"/>
</linearGradient></defs>`
const MARK = `<rect x="24" y="12.5" width="28" height="19" rx="4.5" fill="#fff" stroke="url(#g)" stroke-width="3.6" stroke-opacity=".45"/>
  <rect x="18" y="20.5" width="28" height="19" rx="4.5" fill="#fff" stroke="url(#g)" stroke-width="3.8" stroke-opacity=".75"/>
  <rect x="12" y="29" width="28" height="20" rx="4.5" fill="#fff" stroke="url(#g)" stroke-width="4.2"/>
  <path d="M17.5 42.5l4.6-4.6 4 2.8 4.6-6 4 2.8" fill="none" stroke="#0891b2" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round"/>`

const tile = (s) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="${s}" height="${s}">${GRADIENT}
  <rect x="2" y="2" width="60" height="60" rx="16" fill="#fff"/>
  <rect x="2.75" y="2.75" width="58.5" height="58.5" rx="15.3" fill="none" stroke="#06b6d4" stroke-opacity=".35" stroke-width="1.5"/>
  ${MARK}</svg>`
// The mark spans about 10 to 54 across and 10.5 to 51 down; its middle goes to the middle of the square.
const full = (s, m) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="${s}" height="${s}">${GRADIENT}
  <rect width="64" height="64" fill="#fff"/>
  <g transform="translate(32 32) scale(${m}) translate(-32 -30.8)">${MARK}</g></svg>`
const bleed = (s) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="2 2 60 60" width="${s}" height="${s}">${GRADIENT}
  <rect x="2" y="2" width="60" height="60" fill="#fff"/>${MARK}</svg>`
// White on clear: each card's outline without what the card in front covers, the front card solid with the chart cut out.
const badge = (s) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="6 6 52 52" width="${s}" height="${s}">
  <defs>
    <mask id="back"><rect x="0" y="0" width="64" height="64" fill="#fff"/><rect x="18" y="20.5" width="28" height="19" rx="4.5" fill="#000"/></mask>
    <mask id="middle"><rect x="0" y="0" width="64" height="64" fill="#fff"/><rect x="12" y="29" width="28" height="20" rx="4.5" fill="#000"/></mask>
    <mask id="front"><rect x="0" y="0" width="64" height="64" fill="#fff"/>
      <path d="M17.5 42.5l4.6-4.6 4 2.8 4.6-6 4 2.8" fill="none" stroke="#000" stroke-width="3.6" stroke-linecap="round" stroke-linejoin="round"/></mask>
  </defs>
  <rect x="24" y="12.5" width="28" height="19" rx="4.5" fill="none" stroke="#fff" stroke-width="4" mask="url(#back)"/>
  <rect x="18" y="20.5" width="28" height="19" rx="4.5" fill="none" stroke="#fff" stroke-width="4" mask="url(#middle)"/>
  <rect x="10" y="27" width="32" height="24" rx="6.5" fill="#fff" mask="url(#front)"/></svg>`

const PICTURES = [
  ['public/icon-192.png', tile(192), 192],
  ['public/icon-512.png', tile(512), 512],
  ['public/icon-maskable-512.png', full(512, 0.8), 512],
  ['public/apple-touch-icon.png', bleed(180), 180],
  ['public/badge-96.png', badge(96), 96],
]

const browser = await chromium.launch()
for (const [path, svg, size] of PICTURES) {
  const page = await browser.newPage({ viewport: { width: size, height: size } })
  await page.setContent(`<body style="margin:0;background:transparent">${svg}</body>`)
  await page.locator('svg').screenshot({ path, omitBackground: true })
  await page.close()
  console.log('written:', path)
}
await browser.close()
