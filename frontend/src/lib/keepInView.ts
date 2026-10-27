/** The gap kept to the edge of the screen. */
export const VIEW_MARGIN = 8

/**
 * How far a box has to move sideways to lie inside ``0..width`` with the
 * margin to spare. A box wider than the room is put at the left margin (the
 * caller has already cut its width, so this is the last resort).
 */
export function shiftIntoView(left: number, right: number, width: number, margin = VIEW_MARGIN): number {
  if (right - left > width - 2 * margin) return margin - left
  if (left < margin) return margin - left
  if (right > width - margin) return width - margin - right
  return 0
}

/**
 * Move a menu that hangs off its button (``absolute left-0 top-full``) into
 * the visible width, and cut it to the screen if it is wider than that.
 *
 * ⚠️ These menus are anchored to the button and are 16 to 18 rem wide, so an
 * element on the left edge showed the right-aligned rename form at
 * ``left: -167px`` (only "...me Assistant" and half of "Save" were left to
 * see), and an element on the right edge did the same the other way round.
 * Called when the menu has just been added, before the browser paints, so it
 * never shows in the wrong place for a frame. It moves with ``translate``,
 * which nothing else on a menu uses, and measures what is left afterwards
 * because a zoomed element counts the move in its own pixels.
 */
export function keepInView(menu: HTMLElement): void {
  const width = document.documentElement.clientWidth || window.innerWidth
  menu.style.maxWidth = `${Math.max(0, width - 2 * VIEW_MARGIN)}px`
  let moved = 0
  for (let pass = 0; pass < 2; pass += 1) {
    const box = menu.getBoundingClientRect()
    if (!box.width) return
    const more = shiftIntoView(box.left, box.right, width)
    if (!more) return
    moved += more
    menu.style.translate = `${moved}px 0`
  }
}
