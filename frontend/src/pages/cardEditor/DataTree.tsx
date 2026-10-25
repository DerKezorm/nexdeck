import { ChevronDown, ChevronRight } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { Confirm } from '../../components/ui'
import { pathText, readAt, type CardPath } from '../../lib/cardDocument'
import type { CardForm } from '../../lib/customCards'
import { enclosingList, type ProbeNode } from './probe'
import { FIELD_TYPE, fits, lostIfShownAs, place, showListAs } from './placing'
import { cardPath, placesOf, slotsOf, usedOf, type Slot } from './slots'
import { useCardEditor } from './store'

/** How deep the tree opens by itself: the answer, its fields, the first row of a list and the objects in it. */
const OPEN_DEPTH = 4

interface Row {
  node: ProbeNode
  depth: number
  parent: ProbeNode | null
}

function opened(tree: ProbeNode): Set<string> {
  const open = new Set<string>()
  const walk = (node: ProbeNode, depth: number, first: boolean) => {
    if (!node.children?.length || depth >= OPEN_DEPTH || !first) return
    open.add(node.path)
    node.children.forEach((child, index) => walk(child, depth + 1, node.type !== 'array' || index === 0))
  }
  walk(tree, 0, true)
  return open
}

function visibleRows(tree: ProbeNode, open: Set<string>): Row[] {
  const rows: Row[] = []
  const walk = (node: ProbeNode, depth: number, parent: ProbeNode | null) => {
    rows.push({ node, depth, parent })
    if (open.has(node.path)) node.children?.forEach((child) => walk(child, depth + 1, node))
  }
  walk(tree, 0, null)
  return rows
}

/** A slot's name on screen: "Title", "Number 2". */
export function slotName(t: (key: string, options?: Record<string, unknown>) => string, slot: Slot): string {
  return t(slot.label.key, { number: slot.label.number })
}

/**
 * The answer of a probe as a tree (KARTEN-9 AC-3 to AC-5, EC-1, EC-9): every field with its name, type and value,
 * long lists cut with "… N more", the fields the card uses marked with their place. A click on a field, or Enter,
 * opens "Use as …" with the places of the card's form; a field can be dragged onto a place of the card as well. A
 * list offers to show it as a list or as pictures, and its fields go into each row.
 *
 * The arrow keys move through the tree: up and down from row to row, right opens and goes in, left closes and goes
 * back out, Home and End to the first and the last.
 */
export function DataTree({ requestId, tree }: { requestId: string; tree: ProbeNode }) {
  const { t, i18n } = useTranslation()
  const card = useCardEditor((state) => state.card)
  const [open, setOpen] = useState(() => opened(tree))
  const [active, setActive] = useState(tree.path)
  const [menu, setMenu] = useState<string | null>(null)
  const [asking, setAsking] = useState<{ form: Extract<CardForm, 'list' | 'posters'>; list: ProbeNode; lost: CardPath[] } | null>(null)
  const rowsRef = useRef<Record<string, HTMLDivElement | null>>({})
  const menuRef = useRef<HTMLDivElement | null>(null)

  const rows = useMemo(() => visibleRows(tree, open), [tree, open])
  const used = useMemo(() => usedOf(card), [card])
  const slots = useMemo(() => slotsOf(card), [card])
  const form = card ? (readAt(card, ['form']) as CardForm | undefined) : undefined

  useEffect(() => {
    if (menu) menuRef.current?.querySelector<HTMLElement>('[role="menuitem"]:not([disabled])')?.focus()
  }, [menu])

  const focusRow = (path: string) => {
    setActive(path)
    rowsRef.current[path]?.focus()
  }

  const toggle = (node: ProbeNode, to?: boolean) =>
    setOpen((now) => {
      const next = new Set(now)
      if (to ?? !next.has(node.path)) next.add(node.path)
      else next.delete(node.path)
      return next
    })

  const onKey = (event: KeyboardEvent<HTMLDivElement>, row: Row, index: number) => {
    const { node } = row
    const container = Boolean(node.children?.length)
    const go = (to: Row | undefined) => {
      if (!to) return
      event.preventDefault()
      focusRow(to.node.path)
    }
    switch (event.key) {
      case 'ArrowDown':
        return go(rows[index + 1])
      case 'ArrowUp':
        return go(rows[index - 1])
      case 'Home':
        return go(rows[0])
      case 'End':
        return go(rows[rows.length - 1])
      case 'ArrowRight':
        event.preventDefault()
        if (container && !open.has(node.path)) toggle(node, true)
        else if (container) focusRow(node.children![0].path)
        return
      case 'ArrowLeft':
        event.preventDefault()
        if (container && open.has(node.path)) toggle(node, false)
        else if (row.parent) focusRow(row.parent.path)
        return
      case 'Enter':
      case ' ':
        event.preventDefault()
        setMenu(node.path)
        return
    }
  }

  const closeMenu = (path: string) => {
    setMenu(null)
    rowsRef.current[path]?.focus()
  }

  const showAs = (list: ProbeNode, to: Extract<CardForm, 'list' | 'posters'>) => {
    setMenu(null)
    const lost = lostIfShownAs(to)
    if (lost.length) setAsking({ form: to, list, lost })
    else showListAs(requestId, list, to)
  }

  const typeName = (node: ProbeNode) => t(`editor.tree.type.${node.type}`)
  const keyName = (node: ProbeNode) => (node.key === null ? t('editor.tree.answer') : typeof node.key === 'number' ? `[${node.key}]` : node.key)
  const valueText = (node: ProbeNode) => {
    if (node.type === 'object') return t('editor.tree.fields', { count: (node.children?.length ?? 0) + (node.more ?? 0) })
    if (node.type === 'array') return t('editor.tree.items', { count: (node.children?.length ?? 0) + (node.more ?? 0) })
    if (node.type === 'string') return `"${String(node.value ?? '')}${node.truncated ? '…' : ''}"`
    return String(node.value)
  }

  return (
    <>
      <div role="tree" aria-label={t('editor.tree.label')} className="rounded-xl border border-line bg-surface/40 py-1 text-[13px] min-w-0 overflow-x-auto" data-testid="card-tree">
        {rows.map((row, index) => {
          const { node, depth } = row
          const container = Boolean(node.children?.length)
          const isOpen = open.has(node.path)
          const places = placesOf(used, cardPath(card, requestId, node.path))
          const shownAsRows = used.rows !== null && node.type === 'array' && used.rows.select === cardPath(card, requestId, node.path)
          const marks = [...places.map((slot) => slotName(t, slot)), ...(shownAsRows ? [t(form === 'posters' ? 'editor.tree.shownAsPictures' : 'editor.tree.shownAsList')] : [])]
          const list = node.type === 'array' ? node : null
          const offered = slots.filter((slot) => fits(tree, node, slot) && (!slot.row || (form !== 'value' && form !== 'stats')))
          const inList = enclosingList(tree, node) !== null
          const label = [keyName(node), typeName(node), valueText(node), ...marks].join(', ')
          return (
            <div key={node.path} role="none">
              <div
                ref={(element) => {
                  rowsRef.current[node.path] = element
                }}
                role="treeitem"
                aria-level={depth + 1}
                aria-expanded={container ? isOpen : undefined}
                aria-selected={active === node.path}
                aria-label={label}
                tabIndex={active === node.path ? 0 : -1}
                draggable={node.key !== null}
                onDragStart={(event) => {
                  event.dataTransfer.setData(FIELD_TYPE, JSON.stringify({ requestId, path: node.path }))
                  event.dataTransfer.effectAllowed = 'copy'
                }}
                onFocus={() => setActive(node.path)}
                onKeyDown={(event) => onKey(event, row, index)}
                onClick={() => {
                  setActive(node.path)
                  setMenu(menu === node.path ? null : node.path)
                }}
                className={`group flex items-center gap-2 pr-2 py-1 cursor-pointer min-w-0 outline-none focus-visible:ring-2 focus-visible:ring-accent/60 ${marks.length ? 'bg-accent-soft/60' : ''} ${active === node.path ? 'bg-surface-hover' : 'hover:bg-surface-hover'}`}
                style={{ paddingLeft: 8 + depth * 18 }}
                data-path={node.path}
              >
                {container ? (
                  <button
                    type="button"
                    tabIndex={-1}
                    aria-hidden="true"
                    className="text-muted flex-none"
                    onClick={(event) => {
                      event.stopPropagation()
                      toggle(node)
                    }}
                  >
                    {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  </button>
                ) : (
                  <span className="w-[14px] flex-none" aria-hidden="true" />
                )}
                <span className="font-mono text-ink break-all min-w-0">{keyName(node)}</span>
                <span className="text-[11px] text-faint flex-none">{typeName(node)}</span>
                <span className={`min-w-0 flex-1 truncate ${node.type === 'number' ? 'tabular-nums' : ''} text-muted`} title={valueText(node)}>
                  {valueText(node)}
                </span>
                {marks.map((mark) => (
                  <span key={mark} className="chip !py-0 text-[11px] text-accent border-accent/40 flex-none break-words hyphens-auto" lang={i18n.language}>
                    {mark}
                  </span>
                ))}
                <span className={`btn btn-flat !h-6 !px-2 text-[12px] flex-none ${active === node.path || menu === node.path ? '' : 'opacity-0 group-hover:opacity-100'}`} aria-hidden="true">
                  {t('editor.tree.useAs')}
                </span>
              </div>
              {menu === node.path && (
                <div
                  ref={menuRef}
                  role="menu"
                  aria-label={t('editor.tree.useAsField', { field: keyName(node) })}
                  className="mx-2 my-1 rounded-lg border border-line bg-[var(--nd-bg-elev)] p-1 grid gap-0.5 shadow-lg"
                  style={{ marginLeft: 8 + depth * 18 + 20 }}
                  onKeyDown={(event) => {
                    const items = [...(menuRef.current?.querySelectorAll<HTMLElement>('[role="menuitem"]:not([disabled])') ?? [])]
                    const at = items.indexOf(document.activeElement as HTMLElement)
                    if (event.key === 'Escape') {
                      event.preventDefault()
                      closeMenu(node.path)
                    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
                      event.preventDefault()
                      items[(at + (event.key === 'ArrowDown' ? 1 : items.length - 1)) % items.length]?.focus()
                    }
                  }}
                >
                  {list && (
                    <>
                      <button type="button" role="menuitem" className="text-left px-2 py-1.5 rounded-md text-sm hover:bg-surface-hover focus:bg-surface-hover outline-none break-words hyphens-auto" onClick={() => showAs(list, 'list')}>
                        {t('editor.tree.showAsList')}
                      </button>
                      <button type="button" role="menuitem" className="text-left px-2 py-1.5 rounded-md text-sm hover:bg-surface-hover focus:bg-surface-hover outline-none break-words hyphens-auto" onClick={() => showAs(list, 'posters')}>
                        {t('editor.tree.showAsPictures')}
                      </button>
                    </>
                  )}
                  {offered.map((slot) => (
                    <button
                      key={slot.id}
                      type="button"
                      role="menuitem"
                      className="text-left px-2 py-1.5 rounded-md text-sm hover:bg-surface-hover focus:bg-surface-hover outline-none break-words hyphens-auto"
                      onClick={() => {
                        place(requestId, node, slot)
                        closeMenu(node.path)
                      }}
                    >
                      {t(slot.row ? 'editor.tree.useAsRow' : 'editor.tree.useAsPlace', { place: slotName(t, slot) })}
                    </button>
                  ))}
                  {!list && offered.length === 0 && (
                    <p className="px-2 py-1.5 text-[12px] text-muted break-words hyphens-auto" role="none">
                      {inList ? t('editor.tree.nothingHere') : t('editor.tree.pickAList')}
                    </p>
                  )}
                </div>
              )}
              {isOpen && node.more ? (
                <div className="py-1 text-[12px] text-faint" style={{ paddingLeft: 8 + (depth + 1) * 18 + 22 }} role="none" data-testid="card-tree-more">
                  {t(node.type === 'array' ? 'editor.tree.moreItems' : 'editor.tree.moreFields', { count: node.more, number: node.more.toLocaleString(i18n.language) })}
                </div>
              ) : null}
            </div>
          )
        })}
      </div>
      <Confirm
        open={asking !== null}
        title={t('editor.form.loseTitle')}
        body={asking ? t('editor.form.loseBody', { parts: asking.lost.map((part) => pathText(part)).join(', ') }) : ''}
        danger
        confirmLabel={t('editor.form.loseConfirm')}
        onCancel={() => setAsking(null)}
        onConfirm={() => {
          if (asking) showListAs(requestId, asking.list, asking.form)
          setAsking(null)
        }}
      />
    </>
  )
}
