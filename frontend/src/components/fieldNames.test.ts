/**
 * Fields a screen reader can name.
 *
 * ⚠️ A placeholder is an example, not a name, and some readers skip it: these
 * fields announced themselves as "edit text" and nothing more, and the one
 * that renames a page had no placeholder either. They have no rendering test
 * of their own, so this looks at the markup. Found on 06.09.2026, still there
 * on 12.09.2026.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

// From the frontend folder, where the test run starts.
const FIELDS: [string, string][] = [
  ['src/components/BoardSettingsSheet.tsx', "placeholder={t('board.newName')}"],
  ['src/components/BoardSettingsSheet.tsx', 'defaultValue={page.name}'],
  ['src/components/WidgetLibrary.tsx', "placeholder={t('library.search')}"],
  ['src/pages/BoardPage.tsx', 'value={newPageName}'],
]

function tagAround(text: string, marker: string): string {
  const at = text.indexOf(marker)
  expect(at, `${marker} is not in the file any more`).toBeGreaterThan(-1)
  return text.slice(text.lastIndexOf('<', at), text.indexOf('/>', at))
}

describe('field names', () => {
  it.each(FIELDS)('%s: the field with %s has a name of its own', (file, marker) => {
    const tag = tagAround(readFileSync(join(process.cwd(), file), 'utf8'), marker)
    expect(tag.startsWith('<input') || tag.startsWith('<textarea'), tag).toBe(true)
    expect(tag).toMatch(/aria-label(ledby)?=/)
  })
})
