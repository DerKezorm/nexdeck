/**
 * Every what's-new entry has its four fields in both languages it is written in.
 *
 * An entry without them is dropped silently by the dialog, which then shows
 * the previous version's text. Nothing looks broken, it is only wrong.
 */
import { readdirSync, readFileSync } from 'node:fs'
import path from 'node:path'

import de from '../i18n/whatsnew.de.json'
import en from '../i18n/whatsnew.en.json'
import { LANGUAGES } from '../i18n'
import { entriesFor, isEntry, latestVersion } from '../lib/whatsnew'

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

  it('is written in English and German only', () => {
    // Every other language shows the English entries. A file for one of them
    // would never be read, and would only rot.
    const files = readdirSync(path.resolve(__dirname, '../i18n')).filter((name) => /^whatsnew\.\w+\.json$/.test(name))
    expect(files.sort()).toEqual(['whatsnew.de.json', 'whatsnew.en.json'])
  })

  it('shows every other language the English entries, not an empty window', () => {
    const version = latestVersion()!
    const others = Object.keys(LANGUAGES).filter((code) => code !== 'en' && code !== 'de')
    expect(others, 'no language besides English and German to try').not.toEqual([])
    for (const code of others) {
      expect(entriesFor(code)[version], code).toEqual(en.entries[version as keyof typeof en.entries])
    }
    expect(entriesFor('de')[version]).toEqual(de.entries[version as keyof typeof de.entries])
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
