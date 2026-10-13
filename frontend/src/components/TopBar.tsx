import { Check, ChevronDown, ChevronLeft, ChevronRight, LayoutDashboard, Pencil, Search, Settings } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { useDisguise } from '../lib/showcase'
import { Bar } from './AppBar'
import { HeaderTools, type HeaderUser } from './HeaderTools'
import { LogoMark } from './Logo'

interface Page {
  id: number
  name: string
}

interface BoardEntry {
  id: number
  name: string
  slug: string
}

interface Props {
  boardName: string
  pages: Page[]
  activePage: number
  onPage: (id: number) => void
  editing: boolean
  onEdit: () => void
  canEdit: boolean
  unread: number
  onNotices: () => void
  onSearch: () => void
  onBoards: () => void
  user: HeaderUser | null
  boards?: BoardEntry[]
  onSwitchBoard?: (slug: string) => void
  /** Where the logo leads: the home board itself, not ``/`` (see ``useHomeBoardPath``). */
  home?: string
}

type More = { left: boolean; right: boolean }

/** Fades the side of the page row that has more beyond it. */
function pagesFade(more: More): CSSProperties | undefined {
  if (!more.left && !more.right) return undefined
  const mask = `linear-gradient(to right, ${more.left ? 'transparent, black 40px' : 'black'}, ${more.right ? 'black calc(100% - 40px), transparent' : 'black'})`
  return { maskImage: mask, WebkitMaskImage: mask }
}

/** The slim top bar: board and pages left, search in the middle, tools right. */
export function TopBar(props: Props) {
  const { boardName, pages, activePage, onPage, editing, onEdit, canEdit, unread, onNotices, onSearch, onBoards, user, boards = [], onSwitchBoard, home = '/' } = props
  // A board or a page may carry a name or an address, as "Anna's room" or "nas.lan" does.
  const disguise = useDisguise()
  const { t } = useTranslation()
  const [menu, setMenu] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const pagesRef = useRef<HTMLElement>(null)
  const [more, setMore] = useState<More>({ left: false, right: false })
  const measurePages = useCallback(() => {
    const nav = pagesRef.current
    if (!nav) return
    const next = { left: nav.scrollLeft > 1, right: nav.scrollLeft + nav.clientWidth < nav.scrollWidth - 1 }
    setMore((current) => (current.left === next.left && current.right === next.right ? current : next))
  }, [])
  const turnPages = (way: 1 | -1) => {
    const nav = pagesRef.current
    nav?.scrollBy({ left: way * Math.max(120, nav.clientWidth * 0.7), behavior: 'smooth' })
  }
  // The page shown in sight, and the edges measured again whenever the room or the pages change.
  useEffect(() => {
    const nav = pagesRef.current
    if (!nav) return
    const shown = nav.querySelector<HTMLElement>(`[data-page="${activePage}"]`)
    if (shown) {
      const start = shown.offsetLeft - nav.offsetLeft
      const end = start + shown.offsetWidth
      if (start < nav.scrollLeft) nav.scrollLeft = start - 40
      else if (end > nav.scrollLeft + nav.clientWidth) nav.scrollLeft = end - nav.clientWidth + 40
    }
    measurePages()
    const watch = new ResizeObserver(measurePages)
    watch.observe(nav)
    return () => watch.disconnect()
  }, [activePage, pages.length, measurePages])
  useEffect(() => {
    if (!menu) return
    const onClick = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setMenu(false)
    }
    window.addEventListener('mousedown', onClick)
    return () => window.removeEventListener('mousedown', onClick)
  }, [menu])
  return (
    <Bar>
      <Link to={home} className="flex items-center gap-2 mr-1" aria-label="nexdeck">
        <LogoMark size={26} />
        <span className="font-semibold tracking-tight hidden lg:inline">
          nex<span className="text-accent">deck</span>
        </span>
      </Link>
      <span className="w-px h-5 bg-line-strong hidden lg:block" />
      <div className="relative" ref={menuRef}>
        {/* One line, cut short if need be: a long name wrapped to two and squeezed the bar (#40). */}
        <button className="btn btn-flat px-2 gap-1 font-semibold whitespace-nowrap" onClick={() => setMenu((v) => !v)} aria-haspopup="menu" aria-expanded={menu}>
          <span className="truncate max-w-40">{disguise.free(boardName)}</span>
          <ChevronDown size={14} className="text-muted shrink-0" />
        </button>
        {menu && (
          <div className="absolute left-0 top-10 z-50 glass-strong rounded-xl p-1 min-w-56 shadow-2xl" role="menu">
            {boards.map((board) => (
              <button
                key={board.id}
                role="menuitem"
                className="w-full text-left flex items-center gap-2 px-3 py-2 rounded-lg text-sm hover:bg-surface-hover"
                onClick={() => {
                  setMenu(false)
                  onSwitchBoard?.(board.slug)
                }}
              >
                <LayoutDashboard size={14} className="text-muted" />
                <span className="flex-1 truncate">{disguise.free(board.name)}</span>
                {board.name === boardName && <Check size={14} className="text-accent" />}
              </button>
            ))}
            {boards.length > 0 && <div className="h-px bg-line my-1" />}
            <button
              role="menuitem"
              className="w-full text-left flex items-center gap-2 px-3 py-2 rounded-lg text-sm hover:bg-surface-hover"
              onClick={() => {
                setMenu(false)
                onBoards()
              }}
            >
              <Settings size={14} className="text-muted" />
              {t('board.manage')}
            </button>
          </div>
        )}
      </div>
      {/* ⚠️ The pages scroll once they no longer fit, and nothing said so: a page added last
          seemed missing on an upright iPad (#40). A fading edge and an arrow say there is more
          that way, and the page shown is scrolled into sight. */}
      {/* The arrows lie over the faded edges, not beside the row: beside it they changed its
          width as they came and went, and pushed the page shown back out of sight. */}
      <div className="relative hidden md:flex min-w-0 ml-1">
        <nav
          ref={pagesRef}
          onScroll={measurePages}
          className="flex items-center gap-0.5 min-w-0 overflow-x-auto scrollbar-none [&>*]:shrink-0 whitespace-nowrap"
          style={pagesFade(more)}
          data-more={[more.left && 'left', more.right && 'right'].filter(Boolean).join(' ') || undefined}
          aria-label={t('board.pages')}
        >
          {pages.map((page) => (
            <button
              key={page.id}
              data-page={page.id}
              className={`h-8 px-3 rounded-lg text-[13px] transition-colors ${page.id === activePage ? 'bg-accent-soft text-accent font-medium' : 'text-muted hover:text-ink hover:bg-surface-hover'}`}
              onClick={() => onPage(page.id)}
              aria-current={page.id === activePage ? 'page' : undefined}
            >
              {disguise.free(page.name)}
            </button>
          ))}
        </nav>
        {more.left && (
          <button
            className="absolute inset-y-0 left-0 flex w-6 items-center justify-center text-muted hover:text-ink"
            onClick={() => turnPages(-1)}
            aria-label={t('board.pagesEarlier')}
            title={t('board.pagesEarlier')}
          >
            <ChevronLeft size={15} />
          </button>
        )}
        {more.right && (
          <button
            className="absolute inset-y-0 right-0 flex w-6 items-center justify-center text-muted hover:text-ink"
            onClick={() => turnPages(1)}
            aria-label={t('board.pagesLater')}
            title={t('board.pagesLater')}
          >
            <ChevronRight size={15} />
          </button>
        )}
      </div>
      {/* ⚠️ min-w: a flex item keeps the width of its content unless told otherwise, and the
          placeholder alone pushed the account menu off an upright iPad (issue #27).
          ⚠️ What the field shows goes by its own width, not the screen's: with many pages it
          kept "Ctrl K" at a width of 40 points, and the key ran under the bell (#40). Narrow,
          it is a search button and nothing more. */}
      <div className="@container flex-1 min-w-10 flex justify-center px-2">
        <button
          className="hidden sm:flex items-center justify-center @min-[8rem]:justify-start gap-2 h-8 w-full max-w-[420px] px-2.5 @min-[8rem]:px-3 rounded-lg border border-line bg-bg/40 text-muted text-[13px] hover:border-line-strong transition-colors overflow-hidden"
          onClick={onSearch}
          aria-label={t('palette.title')}
        >
          <Search size={14} className="shrink-0" />
          {/* One line in every language: French wrapped to two and burst the bar. */}
          <span className="hidden @min-[8rem]:block flex-1 min-w-0 truncate text-left">{t('palette.placeholder')}</span>
          <kbd className="hidden @min-[16rem]:inline shrink-0 num text-[10px] px-1.5 py-0.5 rounded border border-line text-faint">Ctrl K</kbd>
        </button>
      </div>
      <div className="flex items-center gap-1.5">
        {canEdit && (
          <button className="btn btn-icon" onClick={onEdit} aria-pressed={editing} aria-label={t('board.edit')} title={t('board.edit')}>
            <Pencil size={15} />
          </button>
        )}
        <HeaderTools user={user} unread={unread} onNotices={onNotices} />
      </div>
    </Bar>
  )
}
