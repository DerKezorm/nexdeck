/**
 * The CHANGELOG of a Card shop entry for the update dialog (KARTEN-15 AC-2): only the sections that are newer than the
 * installed version, set as headings, paragraphs and lists. Everything stays plain text; nothing here makes HTML.
 */

export type ChangelogBlock = { kind: 'text'; text: string } | { kind: 'list'; items: string[] }

export interface ChangelogSection {
  heading: string
  /** The version the heading starts with (`1.0.1`, `v1.0.1`, `[1.0.1]`), or null when it names none. */
  version: string | null
  blocks: ChangelogBlock[]
}

function numbers(version: string): number[] {
  const parts = version.split('.').map((part) => Number.parseInt(part, 10))
  return parts.some((part) => Number.isNaN(part)) ? [0] : parts
}

/** Whether a version is later than another: compared number by number, the shorter one padded with zeros (`1.0.10` is later than `1.0.9`). */
export function isNewerVersion(candidate: string, installed: string): boolean {
  const a = numbers(candidate)
  const b = numbers(installed)
  for (let at = 0; at < Math.max(a.length, b.length); at += 1) {
    const left = a[at] ?? 0
    const right = b[at] ?? 0
    if (left !== right) return left > right
  }
  return false
}

/** The version at the start of a heading; a date such as `2026-10-28` is not one. */
function versionOf(heading: string): string | null {
  return /^[[(]?v?(\d+(?:\.\d+)+)[\])]?(?![\d.-])/i.exec(heading.trim())?.[1] ?? null
}

/**
 * The sections of a CHANGELOG: every `## ` line opens one. What stands before the first is a section without a heading
 * (a `# ` title line is left out), so a file with no `## ` lines at all still shows its text.
 */
export function changelogSections(text: string): ChangelogSection[] {
  let current: ChangelogSection = { heading: '', version: null, blocks: [] }
  const sections: ChangelogSection[] = [current]
  let paragraph: string[] = []
  let list: string[] | null = null
  const endParagraph = () => {
    if (paragraph.length > 0) current.blocks.push({ kind: 'text', text: paragraph.join(' ') })
    paragraph = []
  }
  const endList = () => {
    if (list && list.length > 0) current.blocks.push({ kind: 'list', items: list })
    list = null
  }
  for (const raw of text.replace(/\r\n?/g, '\n').split('\n')) {
    const line = raw.trim()
    const opens = /^##\s+(.*)$/.exec(line)
    if (opens) {
      endParagraph()
      endList()
      current = { heading: opens[1].trim(), version: versionOf(opens[1]), blocks: [] }
      sections.push(current)
      continue
    }
    if (/^#\s/.test(line)) continue
    const item = /^[-*]\s+(.*)$/.exec(line)
    if (item) {
      endParagraph()
      list = [...(list ?? []), item[1].trim()]
    } else if (line === '') {
      endParagraph()
      endList()
    } else {
      endList()
      paragraph.push(line.replace(/^#{3,6}\s+/, ''))
    }
  }
  endParagraph()
  endList()
  return sections.filter((one) => one.heading !== '' || one.blocks.length > 0)
}

/**
 * The sections newer than the installed version. A heading with no version in it cannot be judged: such sections stay
 * only when no section names a version at all (then there is nothing to cut by).
 */
export function newerSections(text: string, installed: string): ChangelogSection[] {
  const all = changelogSections(text)
  const versioned = all.some((one) => one.version !== null)
  return all.filter((one) => (one.version === null ? !versioned : isNewerVersion(one.version, installed)))
}
