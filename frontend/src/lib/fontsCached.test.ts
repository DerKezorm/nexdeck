/**
 * A font one may choose loads when it is chosen. The service worker must not
 * fetch its files with every first visit: each chosen font named in
 * `lib/fonts.ts` is left out of the precache in `vite.config.ts`.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { FONTS } from './fonts'

it('leaves every font that loads on demand out of the precache', () => {
  const config = readFileSync(join(process.cwd(), 'vite.config.ts'), 'utf8')
  const source = readFileSync(join(process.cwd(), 'src/lib/fonts.ts'), 'utf8')
  const lazy = FONTS.filter((font) => font.load)
  expect(lazy.length).toBeGreaterThan(0)
  for (const font of lazy) {
    // The package the font comes from, as the import in lib/fonts.ts names it.
    const line = source.split('\n').find((one) => one.includes(`key: '${font.key}'`))!
    const name = /@fontsource-variable\/([a-z0-9-]+)/.exec(line)![1]
    expect(config, font.key).toContain(`'**/${name}-*.woff2'`)
  }
})
