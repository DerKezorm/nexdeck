import { Bell, Files, LayoutDashboard, Menu, Search } from 'lucide-react'
import { useTranslation } from 'react-i18next'

interface Board {
  id: number
  name: string
  slug?: string
}

interface Page {
  id: number
  name: string
  slug: string
}

interface Props {
  boards: Board[]
  active: number
  onBoard: (id: number) => void
  onSearch: () => void
  onNotices: () => void
  onMenu: () => void
  unread: number
  /** ⚠️ The pages of the board being looked at. The side panel is hidden below
   * 700 px and this bar only ever carried boards, so on a phone the second and
   * third page of a board were reachable through the search and nowhere else.
   * Somebody who does not know the search cannot get to them at all. */
  pages?: Page[]
  activePage?: string
  onPage?: (slug: string) => void
}

/** The phone's bottom bar: boards as tabs, pages, search, notices, menu. */
export function MobileTabBar({ boards, active, onBoard, onSearch, onNotices, onMenu, unread, pages, activePage, onPage }: Props) {
  const { t } = useTranslation()
  // With more than one page, the pages of this board matter more than the
  // third and fourth board: one tap away instead of hidden.
  const manyPages = (pages?.length ?? 0) > 1
  const shownBoards = boards.slice(0, manyPages ? 2 : 3)
  return (
    <nav className="md:hidden fixed bottom-0 inset-x-0 z-40 glass-strong border-x-0 border-b-0 rounded-none pb-[env(safe-area-inset-bottom)]" aria-label={t('nav.boards')}>
      <div className="flex items-stretch h-14">
        {shownBoards.map((board) => (
          <button
            key={board.id}
            className={`flex-1 flex flex-col items-center justify-center gap-0.5 text-[10px] ${board.id === active ? 'text-accent' : 'text-muted'}`}
            onClick={() => onBoard(board.id)}
            aria-current={board.id === active ? 'page' : undefined}
          >
            <LayoutDashboard size={18} aria-hidden="true" />
            <span className="truncate max-w-16">{board.name}</span>
          </button>
        ))}
        {manyPages && onPage && (
          <div className="flex-1 flex flex-col items-center justify-center gap-0.5 text-[10px] text-muted">
            <Files size={18} aria-hidden="true" />
            <select
              className="bg-transparent text-[10px] max-w-16 truncate text-center outline-none"
              value={activePage ?? ''}
              onChange={(event) => onPage(event.target.value)}
              aria-label={t('nav.pages')}
            >
              {pages?.map((page) => (
                <option key={page.id} value={page.slug}>
                  {page.name}
                </option>
              ))}
            </select>
          </div>
        )}
        <button className="flex-1 flex flex-col items-center justify-center gap-0.5 text-[10px] text-muted" onClick={onSearch} aria-label={t('nav.search')}>
          <Search size={18} aria-hidden="true" />
          <span>{t('nav.search')}</span>
        </button>
        <button className="flex-1 flex flex-col items-center justify-center gap-0.5 text-[10px] text-muted relative" onClick={onNotices} aria-label={t('nav.notices')}>
          <Bell size={18} aria-hidden="true" />
          <span>{t('nav.notices')}</span>
          {unread > 0 && <span className="absolute top-2 right-[calc(50%-14px)] w-2 h-2 rounded-full bg-accent" />}
        </button>
        <button className="flex-1 flex flex-col items-center justify-center gap-0.5 text-[10px] text-muted" onClick={onMenu} aria-label={t('nav.more')}>
          <Menu size={18} aria-hidden="true" />
          <span>{t('nav.more')}</span>
        </button>
      </div>
    </nav>
  )
}
