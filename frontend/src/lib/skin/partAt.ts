/**
 * Which part of nexdeck an element is, for the inspector of the skin editor: a
 * click on the stage names the part a skin would style there.
 *
 * The parts come from the server (`GET /skins/schema`, backend/app/skins/parts.json).
 * The nearest element that is a part wins; when it is more than one (a primary
 * button is a button too), the part whose selector says more about it, that is
 * the longer one that matched.
 */
export interface PartEntry {
  group: string
  label: string
  selectors: string[]
  pseudo: string[]
  container?: boolean
  states?: Record<string, string[]>
}

export type Parts = Record<string, PartEntry>

export function partOf(element: Element, parts: Parts): string | null {
  let best: { name: string; length: number } | null = null
  for (const [name, part] of Object.entries(parts)) {
    for (const selector of part.selectors) {
      try {
        if (element.matches(selector) && (!best || selector.length > best.length)) best = { name, length: selector.length }
      } catch {
        // A selector this browser cannot read names no part here.
      }
    }
  }
  return best?.name ?? null
}

/** The part at an element or the nearest one around it, with the element that is it. */
export function partAt(target: Element | null, parts: Parts): { part: string; element: Element } | null {
  for (let element: Element | null = target; element; element = element.parentElement) {
    const part = partOf(element, parts)
    if (part) return { part, element }
  }
  return null
}

/** Every element of a part in a document, to show where it is. */
export function elementsOf(root: ParentNode, part: PartEntry): Element[] {
  try {
    return [...root.querySelectorAll(part.selectors.join(', '))]
  } catch {
    return []
  }
}
