/* The scale at the door: how heavy is the first visit?
 *
 *   node tools/weight-check.mjs        (after `npm run build`)
 *
 * Measures what a visitor downloads on first open: the entry chunk, everything
 * it imports statically, and the stylesheet, gzip-compressed. Lazily loaded
 * pages do not count; that is the whole point of loading them lazily.
 *
 * THE LIMIT DOES NOT GO UP WHEN THIS TRIPS. A scale whose weight you adjust
 * whenever it complains measures nothing. When it trips, something new moves
 * behind a lazy import, or a dependency goes.
 */
import { readFileSync, statSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { gzipSync } from 'node:zlib'

/** Kilobytes, gzip, of the first load. */
const LIMIT_KB = 420

const here = path.dirname(fileURLToPath(import.meta.url))
const DIST = path.join(here, '..', 'dist')
const MANIFEST = path.join(DIST, '.vite', 'manifest.json')

let manifest
try {
  manifest = JSON.parse(readFileSync(MANIFEST, 'utf8'))
} catch {
  console.error(`No build found (${path.relative(process.cwd(), MANIFEST)}). Run \`npm run build\` first.`)
  process.exit(2)
}

const entryKey = Object.keys(manifest).find((key) => manifest[key].isEntry)
if (!entryKey) {
  console.error('The manifest has no entry point.')
  process.exit(2)
}

const fixed = new Set()
function follow(key) {
  if (fixed.has(key) || !manifest[key]) return
  fixed.add(key)
  for (const next of manifest[key].imports ?? []) follow(next)
}
follow(entryKey)

const files = new Set()
for (const key of fixed) {
  const entry = manifest[key]
  if (entry.file) files.add(entry.file)
  for (const css of entry.css ?? []) files.add(css)
}

let total = 0
const rows = []
for (const file of files) {
  const full = path.join(DIST, file)
  const raw = statSync(full).size
  const gzip = gzipSync(readFileSync(full)).length
  total += gzip
  rows.push({ file, raw, gzip })
}
rows.sort((a, b) => b.gzip - a.gzip)
for (const row of rows) {
  console.log(`${(row.gzip / 1000).toFixed(1).padStart(7)} kB gzip  ${(row.raw / 1000).toFixed(1).padStart(8)} kB raw  ${row.file}`)
}
const totalKb = total / 1000
console.log(`\nFirst load: ${totalKb.toFixed(1)} kB gzip (limit ${LIMIT_KB} kB)`)
if (totalKb > LIMIT_KB) {
  console.error(`\nToo heavy by ${(totalKb - LIMIT_KB).toFixed(1)} kB. Move something behind a lazy import; do not raise the limit.`)
  process.exit(1)
}
