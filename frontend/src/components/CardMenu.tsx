/**
 * What a card can be told in edit mode besides being dragged: a size by
 * name, and another page to go to.
 *
 * ⚠️ Drawn at the body, not inside the card. A grid item clips what sticks
 * out of it, so a menu inside the card was cut at the card's edge, and a
 * small card had no room for a menu at all.
 */
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'

import type { SizeName } from '../lib/arranging'

export interface MoveTarget {
  boardName: string
  /** Whether this is the board the card is on; its pages come first and without the board's name. */
  current: boolean
  pages: { id: number; name: string }[]
}

interface Props {
  anchor: DOMRect
  /** How many cards a move takes along: the selection, when this card is part of it. */
  carrying: number
  sizes: { name: SizeName; w: number; h: number }[]
  /** The size the card has now, so the menu can say which one it is. */
  current: { w: number; h: number }
  targets: MoveTarget[]
  onSize: (w: number, h: number) => void
  onMove: (pageId: number) => void
  onClose: () => void
}

const WIDTH = 248

export function CardMenu({ anchor, carrying, sizes, current, targets, onSize, onMove, onClose }: Props) {
  const { t } = useTranslation()
  const box = useRef<HTMLDivElement>(null)
  const [top, setTop] = useState(anchor.bottom + 4)

  // Below the button, or above it when the window ends first.
  useLayoutEffect(() => {
    const height = box.current?.offsetHeight ?? 0
    setTop(anchor.bottom + 4 + height > window.innerHeight - 8 ? Math.max(8, anchor.top - 4 - height) : anchor.bottom + 4)
  }, [anchor])

  useEffect(() => {
    const away = (event: PointerEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) onClose()
    }
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onClose()
      }
    }
    document.addEventListener('pointerdown', away, true)
    document.addEventListener('keydown', key, true)
    box.current?.querySelector<HTMLElement>('button')?.focus()
    return () => {
      document.removeEventListener('pointerdown', away, true)
      document.removeEventListener('keydown', key, true)
    }
  }, [onClose])

  const left = Math.max(8, Math.min(window.innerWidth - WIDTH - 8, anchor.right - WIDTH))
  const reachable = targets.filter((target) => target.pages.length > 0)

  return createPortal(
    <div ref={box} role="menu" aria-label={t('arrange.menu')} className="glass-strong fixed z-[60] rounded-xl p-2 shadow-2xl text-sm" style={{ top, left, width: WIDTH }}>
      <p className="px-2 pt-1 pb-1.5 text-[11px] font-medium text-muted">{t('arrange.size')}</p>
      <div className="grid grid-cols-4 gap-1 px-1 pb-2">
        {sizes.map((size) => {
          const now = size.w === current.w && size.h === current.h
          return (
            <button
              key={size.name}
              role="menuitemradio"
              aria-checked={now}
              className={`btn h-auto py-1 flex-col !gap-0 ${now ? 'border-accent' : ''}`}
              title={t('arrange.sizeTitle', { w: size.w, h: size.h })}
              onClick={() => {
                onSize(size.w, size.h)
                onClose()
              }}
            >
              <span className="font-medium">{size.name}</span>
              <span className="num text-[10px] text-faint">
                {size.w}×{size.h}
              </span>
            </button>
          )
        })}
      </div>
      <p className="px-2 pt-1 pb-1 text-[11px] font-medium text-muted border-t border-line">
        {carrying > 1 ? t('arrange.moveMany', { count: carrying }) : t('arrange.move')}
      </p>
      {reachable.length === 0 && <p className="px-2 py-1 text-[12px] text-faint">{t('arrange.nowhere')}</p>}
      <div className="max-h-64 overflow-y-auto">
        {reachable.map((target) => (
          <div key={target.boardName + String(target.current)}>
            {!target.current && <p className="px-2 pt-1.5 text-[10px] uppercase tracking-wide text-faint">{target.boardName}</p>}
            {target.pages.map((page) => (
              <button
                key={page.id}
                role="menuitem"
                className="w-full text-left px-2 py-1.5 rounded-lg hover:bg-surface-hover focus-visible:bg-surface-hover truncate"
                onClick={() => {
                  onMove(page.id)
                  onClose()
                }}
              >
                {page.name}
              </button>
            ))}
          </div>
        ))}
      </div>
    </div>,
    document.body,
  )
}
