/**
 * Every what's-new entry has its four fields in both languages.
 *
 * An entry without them is dropped silently by the dialog, which then shows
 * the previous version's text. Nothing looks broken, it is only wrong.
 */
import { readFileSync } from 'node:fs'
import path from 'node:path'

import de from '../i18n/whatsnew.de.json'
import en from '../i18n/whatsnew.en.json'
import { isEntry, latestVersion } from '../lib/whatsnew'

const REQUIRED = ['lead', 'sections', 'smallTitle', 'small'] as const

describe("what's new entries", () => {
  for (const [language, file] of [['en', en], ['de', de]] as const) {
    it(`${language}: every entry has all four fields`, () => {
      const incomplete: string[] = []
      for (const [version, entry] of Object.entries(file.entries)) {
        const missing = REQUIRED.filter((field) => !(field in entry))
        if (missing.length) incomplete.push(`${version}: ${missing.join(', ')}`)
        expect(isEntry(entry), `${version} passes isEntry`).toBe(true)
      }
      expect(incomplete).toEqual([])
    })
  }

  it('both languages describe the same versions', () => {
    expect(Object.keys(de.entries).sort()).toEqual(Object.keys(en.entries).sort())
  })

  it('the version being shipped has an entry', () => {
    // ⚠️ Against the version in package.json, not against a number written
    // out here. Written out, this line has to be edited on every release,
    // and the release it is forgotten on is the one that ships with the
    // previous version's text in the dialog.
    const shipping = JSON.parse(readFileSync(path.resolve(__dirname, '../../package.json'), 'utf8')).version
    expect(shipping, 'package.json has no version, so this test proves nothing').toBeTruthy()
    expect(latestVersion()).toBe(shipping)
  })

  it('sections carry title and body', () => {
    for (const entry of Object.values(en.entries)) {
      expect(entry.sections.length).toBeGreaterThan(0)
      for (const section of entry.sections) {
        expect(section.title.length).toBeGreaterThan(0)
        expect(section.body.length).toBeGreaterThan(0)
      }
    }
  })
})
