/**
 * What a card can be told in edit mode besides being dragged: a size by
 * name, another page to go to, and a page to be copied onto, its own
 * included.
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
  /** The page the card is on, offered first when copying: a copy beside the original. */
  here?: { id: number; name: string }
  /** Copies the card, or the selection, onto a page. Without it the menu only moves. */
  onCopy?: (pageId: number) => void
  onClose: () => void
}

const WIDTH = 248

export function CardMenu({ anchor, carrying, sizes, current, targets, onSize, onMove, here, onCopy, onClose }: Props) {
  const { t } = useTranslation()
  const box = useRef<HTMLDivElement>(null)
  const [top, setTop] = useState(anchor.bottom + 4)
  // Move or copy: the same pages either way, so one list and a switch above it.
  const [copying, setCopying] = useState(false)

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
  const go = (pageId: number) => {
    if (copying) onCopy?.(pageId)
    else onMove(pageId)
    onClose()
  }
  const item = 'w-full text-left px-2 py-1.5 rounded-lg hover:bg-surface-hover focus-visible:bg-surface-hover truncate'

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
      <div className="flex items-center gap-2 px-2 pt-1.5 pb-1 border-t border-line">
        <p className="flex-1 min-w-0 text-[11px] font-medium text-muted truncate">
          {copying
            ? carrying > 1 ? t('arrange.copyMany', { count: carrying }) : t('arrange.copy')
            : carrying > 1 ? t('arrange.moveMany', { count: carrying }) : t('arrange.move')}
        </p>
        {onCopy && (
          <span className="inline-flex shrink-0 rounded-md bg-surface p-0.5 gap-0.5 text-[11px]" role="group" aria-label={t('arrange.moveOrCopy')}>
            {([false, true] as const).map((copy) => (
              <button
                key={String(copy)}
                type="button"
                className={`px-2 py-0.5 rounded ${copying === copy ? 'bg-accent-soft text-ink' : 'text-muted'}`}
                aria-pressed={copying === copy}
                onClick={() => setCopying(copy)}
              >
                {copy ? t('arrange.copyMode') : t('arrange.moveMode')}
              </button>
            ))}
          </span>
        )}
      </div>
      {!copying && reachable.length === 0 && <p className="px-2 py-1 text-[12px] text-faint">{t('arrange.nowhere')}</p>}
      <div className="max-h-64 overflow-y-auto">
        {copying && here && (
          <button role="menuitem" className={`${item} font-medium`} onClick={() => go(here.id)}>
            {t('arrange.duplicateHere')}
          </button>
        )}
        {reachable.map((target) => (
          <div key={target.boardName + String(target.current)}>
            {!target.current && <p className="px-2 pt-1.5 text-[10px] uppercase tracking-wide text-faint">{target.boardName}</p>}
            {target.pages.map((page) => (
              <button key={page.id} role="menuitem" className={item} onClick={() => go(page.id)}>
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
