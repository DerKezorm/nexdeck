/**
 * The short name an app tile takes from its name, as ``services/aliases.py``
 * works it out: lower-case letters, digits and hyphens, forty at most, ä, ö,
 * ü and ß written out. The server decides; this only shows it while typing.
 */
const SPELLED: Record<string, string> = { 'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss' }

export const ALIAS = /^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$/

export function deriveAlias(name: string): string {
  const spelled = [...(name ?? '').toLowerCase()].map((letter) => SPELLED[letter] ?? letter).join('')
  // Split into letter and accent, then keep printable ASCII only: "é" keeps its "e".
  const plain = spelled.normalize('NFKD').replace(/[^ -~]/g, '')
  return plain.replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40).replace(/-+$/, '')
}
