import de from '../i18n/whatsnew.de.json'
import en from '../i18n/whatsnew.en.json'

export interface WhatsNewEntry {
  lead: string
  sections: { title: string; body: string; path?: string }[]
  smallTitle: string
  small: string[]
}

const FILES: Record<string, { entries: Record<string, WhatsNewEntry> }> = { en, de }

export function entriesFor(language: string): Record<string, WhatsNewEntry> {
  return (FILES[language] ?? FILES.en).entries
}

/** The newest version that has an entry, by semantic order. */
export function latestVersion(): string | null {
  const versions = Object.keys(FILES.en.entries)
  if (!versions.length) return null
  return versions.sort((a, b) => compare(b, a))[0]
}

function compare(a: string, b: string): number {
  const pa = a.split('.').map(Number)
  const pb = b.split('.').map(Number)
  for (let i = 0; i < 3; i++) {
    if ((pa[i] ?? 0) !== (pb[i] ?? 0)) return (pa[i] ?? 0) - (pb[i] ?? 0)
  }
  return 0
}

export function isEntry(value: unknown): value is WhatsNewEntry {
  if (!value || typeof value !== 'object') return false
  const entry = value as Record<string, unknown>
  return typeof entry.lead === 'string' && Array.isArray(entry.sections) && typeof entry.smallTitle === 'string' && Array.isArray(entry.small)
}
