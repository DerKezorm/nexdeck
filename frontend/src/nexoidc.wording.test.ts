/**
 * Pflichttest 35 (Bauplan 05): every text of the oidc module is in the app, in German and English, through the app's
 * own i18n. Copied once by `bauplaene/oidc/tools/sync.py` to `frontend/src/nexoidc.wording.test.ts`; then the
 * app's file. Fill in the places marked APP.
 *
 * The module's own tests already check the wording files against Bauplan 04 word for word; this test checks that the
 * app really loads them (merged into its resources, `{{app}}` filled in) and that nothing in the app overrides them.
 */
import { describe, expect, it } from 'vitest'

import { oidcWording, type OidcWording } from './vendor/nexoidc/oidc'
import de from './vendor/nexoidc/oidc.de.json'
import en from './vendor/nexoidc/oidc.en.json'
// APP: the app's i18n instance after its set-up (with the module's files merged into the resources). nexdeck ships
// English in the bundle and loads German when it is chosen, through setLanguage.
import i18n, { setLanguage } from './i18n'

// APP: the name of the app as it appears in the texts.
const APP_NAME = 'nexdeck'
// APP: true for the apps with one account (nexcrate, nexsift); the app merges the files through oidcWording.
const SINGLE_ACCOUNT = false

type Tree = OidcWording

function leaves(tree: Tree, prefix = ''): [string, string][] {
  return Object.entries(tree).flatMap(([name, value]) => {
    const key = prefix ? `${prefix}.${name}` : name
    return typeof value === 'string' ? [[key, value] as [string, string]] : leaves(value, key)
  })
}

// Every placeholder of the texts but `{{app}}` (`address` since 1.0.10, in the template since 1.0.11).
const values = { name: 'N', count: 2, only: 1, status: 403, address: 'https://app.example.com' }

describe('the oidc texts', () => {
  for (const [language, tree] of [['de', de], ['en', en]] as const) {
    it(`are all in the app in ${language}, word for word, with the app's name`, async () => {
      await setLanguage(language)
      for (const [key, text] of leaves(oidcWording(tree, { singleAccount: SINGLE_ACCOUNT }))) {
        // Plural forms are asked for without their suffix, with a count that picks them (since 1.0.9).
        const plural = /_(one|other)$/.exec(key)
        const given = plural ? { ...values, count: plural[1] === 'one' ? 1 : 2 } : values
        const asked = plural ? key.slice(0, plural.index) : key
        const expected = text.replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
          name === 'app' ? APP_NAME : String(given[name as keyof typeof given]),
        )
        expect(i18n.t(asked, given), key).toBe(expected)
      }
    })
  }
})
