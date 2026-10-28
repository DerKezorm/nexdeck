/**
 * The MCP words (`mcp.<language>.json`, loaded by `lib/mcpTexts.ts`): every language carries every key and placeholder
 * of the English file, none is empty, none has a dash. Its own file so the shared completeness test stays as it is.
 */
import mcpDe from './mcp.de.json'
import mcpEn from './mcp.en.json'
import mcpEs from './mcp.es.json'
import mcpFr from './mcp.fr.json'
import mcpIt from './mcp.it.json'

function paths(value: unknown, prefix = ''): string[] {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return prefix ? [prefix] : []
  return Object.entries(value as Record<string, unknown>).flatMap(([key, child]) => paths(child, prefix ? `${prefix}.${key}` : key))
}

function lookup(data: unknown, path: string): unknown {
  return path.split('.').reduce<unknown>((node, key) => (node as Record<string, unknown> | undefined)?.[key], data)
}

describe('the MCP words in every language', () => {
  const english = new Set(paths(mcpEn))
  const placeholders = (text: string) => (text.match(/\{\{\w+\}\}/g) ?? []).sort().join(',')

  it('are not empty by accident', () => {
    expect(english.size).toBeGreaterThan(80)
  })

  for (const [language, data] of Object.entries({ de: mcpDe, es: mcpEs, fr: mcpFr, it: mcpIt })) {
    it(`${language}: knows the same keys and placeholders as English, none empty`, () => {
      const known = new Set(paths(data))
      expect([...english].filter((p) => !known.has(p)).sort(), `missing from mcp.${language}.json`).toEqual([])
      expect([...known].filter((p) => !english.has(p)).sort(), `only in mcp.${language}.json`).toEqual([])
      expect([...english].filter((p) => placeholders(String(lookup(mcpEn, p))) !== placeholders(String(lookup(data, p))))).toEqual([])
      expect(paths(data).filter((p) => !String(lookup(data, p)).trim() || String(lookup(data, p)).includes('—'))).toEqual([])
    })
  }
})
