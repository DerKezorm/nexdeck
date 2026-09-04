import { Bell, ChevronDown, Moon, Pencil, Search, Sun } from 'lucide-react'

import { LogoMark } from './Logo'

interface Page {
  id: number
  name: string
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
  theme: 'dark' | 'light'
  onTheme: () => void
  userInitial: string
  onProfile: () => void
}

/** The slim top bar: board and pages left, search in the middle, tools right. */
export function TopBar(props: Props) {
  const { boardName, pages, activePage, onPage, editing, onEdit, canEdit, unread, onNotices, onSearch, onBoards, theme, onTheme, userInitial, onProfile } = props
  return (
    <header className="glass-strong sticky top-0 z-40 h-12 flex items-center gap-2 px-3 border-x-0 border-t-0 rounded-none">
      <a href="/" className="flex items-center gap-2 mr-1" aria-label="nexdeck home">
        <LogoMark size={26} />
        <span className="font-semibold tracking-tight hidden lg:inline">
          nex<span className="text-accent">deck</span>
        </span>
      </a>
      <span className="w-px h-5 bg-line-strong hidden lg:block" />
      <button className="btn border-0 bg-transparent px-2 gap-1 font-semibold" onClick={onBoards} aria-haspopup="menu">
        {boardName}
        <ChevronDown size={14} className="text-muted" />
      </button>
      <nav className="hidden md:flex items-center gap-0.5 ml-1" aria-label="Pages">
        {pages.map((page) => (
          <button
            key={page.id}
            className={`h-8 px-3 rounded-lg text-[13px] transition-colors ${page.id === activePage ? 'bg-accent-soft text-accent font-medium' : 'text-muted hover:text-ink hover:bg-surface-hover'}`}
            onClick={() => onPage(page.id)}
            aria-current={page.id === activePage ? 'page' : undefined}
          >
            {page.name}
          </button>
        ))}
      </nav>
      <div className="flex-1 flex justify-center px-2">
        <button
          className="hidden sm:flex items-center gap-2 h-8 w-full max-w-[420px] px-3 rounded-lg border border-line bg-bg/40 text-muted text-[13px] hover:border-line-strong transition-colors"
          onClick={onSearch}
          aria-label="Search"
        >
          <Search size={14} />
          <span className="flex-1 text-left">Search services, actions, boards…</span>
          <kbd className="num text-[10px] px-1.5 py-0.5 rounded border border-line text-faint">Ctrl K</kbd>
        </button>
      </div>
      <div className="flex items-center gap-1">
        {canEdit && (
          <button className="btn btn-icon" onClick={onEdit} aria-pressed={editing} aria-label="Edit board" title="Edit board">
            <Pencil size={15} />
          </button>
        )}
        <button className="btn btn-icon relative" onClick={onNotices} aria-label={`Notices${unread ? `, ${unread} unread` : ''}`}>
          <Bell size={15} />
          {unread > 0 && (
            <span className="absolute -top-1 -right-1 min-w-4 h-4 px-1 rounded-full bg-accent text-[10px] font-semibold text-[#041016] flex items-center justify-center num">
              {unread}
            </span>
          )}
        </button>
        <button className="btn btn-icon" onClick={onTheme} aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}>
          {theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
        </button>
        <button
          className="w-8 h-8 rounded-full bg-gradient-to-br from-accent to-indigo-500 text-[#041016] font-semibold text-[13px] flex items-center justify-center ml-1"
          onClick={onProfile}
          aria-label="Profile"
        >
          {userInitial}
        </button>
      </div>
    </header>
  )
}
