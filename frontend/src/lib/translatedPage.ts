/**
 * When the browser translates the page (Chrome, Edge, extensions), it swaps
 * text nodes for elements of its own. React still holds the old nodes and
 * throws on the next insert or removal ("insertBefore", "removeChild"), and
 * the whole page is gone. Both give way here: a node that was taken away
 * already is not removed again, and what is meant to go before a node that
 * was taken away goes before what stands in its place, or at the end.
 *
 * It shows only when the page is in another language than the browser.
 */
export function bearTranslatedPages(): void {
  if (typeof Node !== 'function') return
  const proto = Node.prototype
  if ((proto as { nexdeckBears?: boolean }).nexdeckBears) return
  ;(proto as { nexdeckBears?: boolean }).nexdeckBears = true

  const removeChild = proto.removeChild
  proto.removeChild = function <T extends Node>(this: Node, child: T): T {
    if (child.parentNode !== this) return child
    return removeChild.call(this, child) as T
  }

  const insertBefore = proto.insertBefore
  proto.insertBefore = function <T extends Node>(this: Node, node: T, before: Node | null): T {
    if (before !== null && before.parentNode !== this) {
      return insertBefore.call(this, node, childHolding(this, before)) as T
    }
    return insertBefore.call(this, node, before) as T
  }
}

/** The child of `parent` that holds `node` today; null when it is not in there any more. */
function childHolding(parent: Node, node: Node): Node | null {
  let current: Node | null = node
  while (current !== null && current.parentNode !== parent) current = current.parentNode
  return current
}
