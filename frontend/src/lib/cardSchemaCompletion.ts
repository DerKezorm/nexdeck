/**
 * Suggestions while typing a custom card as YAML (KARTEN-10 AC-2), read from the JSON schema of a card
 * (`GET /cards/schema`, the same one the server checks against).
 *
 * The place in the card is worked out from the indentation of the lines above the cursor, not from a parsed document:
 * while somebody types, the text is invalid more often than not.
 */

/** As much of a JSON schema as this reads. */
export interface SchemaNode {
  $ref?: string
  $defs?: Record<string, SchemaNode>
  type?: string | string[]
  properties?: Record<string, SchemaNode>
  items?: SchemaNode
  anyOf?: SchemaNode[]
  oneOf?: SchemaNode[]
  allOf?: SchemaNode[]
  enum?: unknown[]
  const?: unknown
  description?: string
  additionalProperties?: SchemaNode | boolean
}

export interface Suggestion {
  label: string
  kind: 'key' | 'value'
  /** The first sentence of the schema's description. */
  detail?: string
}

export interface Suggestions {
  /** Where the word being typed begins; a suggestion replaces the text from here to the cursor. */
  from: number
  options: Suggestion[]
}

type Step = string | '*'

function resolve(root: SchemaNode, node: SchemaNode | undefined, seen = 0): SchemaNode[] {
  if (!node || seen > 20) return []
  if (node.$ref) {
    const name = node.$ref.replace(/^#\/\$defs\//, '')
    return resolve(root, root.$defs?.[name], seen + 1)
  }
  const parts = [...(node.anyOf ?? []), ...(node.oneOf ?? []), ...(node.allOf ?? [])]
  if (parts.length) return [node, ...parts.flatMap((part) => resolve(root, part, seen + 1))]
  return [node]
}

/** The first sentence, for the line beside a suggestion. */
function firstSentence(text: string | undefined): string | undefined {
  if (!text) return undefined
  const end = text.search(/\.(\s|$)/)
  return end > 0 ? text.slice(0, end + 1) : text
}

/** The schemas a path leads to. At the top, the form already written picks the kind of card. */
function schemasAt(root: SchemaNode, path: Step[], text: string): SchemaNode[] {
  let current = resolve(root, root)
  const form = /^form:\s*["']?([a-z]+)/m.exec(text)?.[1]
  if (form) {
    const fitting = current.filter((one) => {
      const own = one.properties?.form
      return own !== undefined && (own.const === form || (Array.isArray(own.enum) && own.enum.includes(form)))
    })
    if (fitting.length) current = fitting
  }
  for (const step of path) {
    current = current.flatMap((one) => resolve(root, step === '*' ? one.items : one.properties?.[step]))
    if (!current.length) return []
  }
  return current
}

const KEY_LINE = /^( *)(?:(- +))?(["']?[\w-]+["']?)\s*:(.*)$/

function indentOf(line: string): number {
  return /^( *)/.exec(line)![1].length
}

function isEmptyValue(rest: string): boolean {
  const value = rest.trim()
  return value === '' || value.startsWith('#')
}

/**
 * The keys from the top down to the map the line at `index` belongs to, at indentation `indent`. A list item is `*`.
 */
function pathAbove(lines: string[], index: number, indent: number): Step[] {
  const path: Step[] = []
  let want = indent
  // A list without indentation (`requests:\n- id:`) has its dash at the column of its key.
  let seqAt: number | null = null
  for (let at = index - 1; at >= 0; at -= 1) {
    const line = lines[at]
    if (!line.trim() || line.trim().startsWith('#')) continue
    const lead = indentOf(line)
    const dash = /^( *)(- +)/.exec(line)
    if (seqAt !== null) {
      // Looking for the key that holds the list whose item was found.
      if (dash && lead === seqAt) continue
      const key = KEY_LINE.exec(line)
      if (!key || lead > seqAt) continue
      if (dash) return path.reverse()
      path.push(key[3].replace(/^["']|["']$/g, ''))
      want = lead
      seqAt = null
      continue
    }
    if (dash) {
      const content = lead + dash[2].length
      if (content === want) {
        path.push('*')
        seqAt = lead
        // The item may itself start with a key: `- id: x` is a sibling, the item's map is the one wanted.
        continue
      }
      if (lead < want) {
        // A dash further out: the item holds a map below its own key (`- item:\n    title:`).
        const key = KEY_LINE.exec(line)
        if (key && isEmptyValue(key[4]) && content < want) {
          path.push(key[3].replace(/^["']|["']$/g, ''), '*')
          seqAt = lead
        }
        continue
      }
      continue
    }
    if (lead < want) {
      const key = KEY_LINE.exec(line)
      if (!key || !isEmptyValue(key[4])) return path.reverse()
      path.push(key[3].replace(/^["']|["']$/g, ''))
      want = lead
      if (want === 0) break
    }
  }
  return path.reverse()
}

/** The keys already written in the map at `indent` around line `index`, so that they are not offered again. */
function siblings(lines: string[], index: number, indent: number): Set<string> {
  const found = new Set<string>()
  const take = (line: string) => {
    const key = KEY_LINE.exec(line)
    if (!key) return
    const at = key[1].length + (key[2]?.length ?? 0)
    if (at === indent) found.add(key[3].replace(/^["']|["']$/g, ''))
  }
  for (const direction of [-1, 1]) {
    for (let at = index + direction; at >= 0 && at < lines.length; at += direction) {
      const line = lines[at]
      if (!line.trim() || line.trim().startsWith('#')) continue
      const lead = indentOf(line)
      const dash = /^( *)(- +)/.exec(line)
      const content = dash ? lead + dash[2].length : lead
      if (content < indent || (dash && content === indent && direction === 1)) break
      take(line)
      if (dash && content === indent) break
    }
  }
  return found
}

/** What may follow at `offset` in `text`: keys at the start of a line, values after `key: `; `null` for nothing. */
export function suggestionsAt(schema: SchemaNode, text: string, offset: number): Suggestions | null {
  const lineStart = text.lastIndexOf('\n', offset - 1) + 1
  const before = text.slice(lineStart, offset)
  const lines = text.split('\n')
  const index = text.slice(0, lineStart).split('\n').length - 1

  const value = /^( *)(?:(- +))?(["']?[\w-]+["']?)\s*:\s+["']?([\w.-]*)$/.exec(before)
  if (value) {
    const indent = value[1].length + (value[2]?.length ?? 0)
    const path = pathAbove(lines, index, indent)
    if (value[2]) path.push('*')
    const key = value[3].replace(/^["']|["']$/g, '')
    const schemas = schemasAt(schema, [...path, key], text)
    const options = new Map<string, Suggestion>()
    for (const one of schemas) {
      for (const choice of [...(one.enum ?? []), ...(one.const !== undefined ? [one.const] : [])]) {
        if (typeof choice === 'string' || typeof choice === 'number') options.set(String(choice), { label: String(choice), kind: 'value' })
      }
      if (one.type === 'boolean') for (const word of ['true', 'false']) options.set(word, { label: word, kind: 'value' })
    }
    const typed = value[4]
    const list = [...options.values()].filter((option) => option.label.startsWith(typed))
    return list.length ? { from: offset - typed.length, options: list } : null
  }

  const key = /^( *)(- +)?([\w-]*)$/.exec(before)
  if (!key) return null
  const indent = key[1].length + (key[2]?.length ?? 0)
  const path = pathAbove(lines, index, indent)
  if (key[2]) path.push('*')
  const taken = siblings(lines, index, indent)
  const options = new Map<string, Suggestion>()
  for (const one of schemasAt(schema, path, text)) {
    for (const [name, inner] of Object.entries(one.properties ?? {})) {
      if (taken.has(name) || options.has(name)) continue
      const described = resolve(schema, inner).find((part) => part.description)?.description
      options.set(name, { label: name, kind: 'key', detail: firstSentence(inner.description ?? described) })
    }
  }
  const typed = key[3]
  const list = [...options.values()].filter((option) => option.label.startsWith(typed))
  return list.length ? { from: offset - typed.length, options: list } : null
}
