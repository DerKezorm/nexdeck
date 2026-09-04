import { Bell, LayoutDashboard, Menu, Search } from 'lucide-react'

interface Board {
  id: number
  name: string
  slug?: string
}

interface Props {
  boards: Board[]
  active: number
  onBoard: (id: number) => void
  onSearch: () => void
  onNotices: () => void
  onMenu: () => void
  unread: number
}

/** The phone's bottom bar: boards as tabs, search, notices, menu. */
export function MobileTabBar({ boards, active, onBoard, onSearch, onNotices, onMenu, unread }: Props) {
  return (
    <nav className="md:hidden fixed bottom-0 inset-x-0 z-40 glass-strong border-x-0 border-b-0 rounded-none pb-[env(safe-area-inset-bottom)]" aria-label="Boards">
      <div className="flex items-stretch h-14">
        {boards.slice(0, 3).map((board) => (
          <button
            key={board.id}
            className={`flex-1 flex flex-col items-center justify-center gap-0.5 text-[10px] ${board.id === active ? 'text-accent' : 'text-muted'}`}
            onClick={() => onBoard(board.id)}
            aria-current={board.id === active ? 'page' : undefined}
          >
            <LayoutDashboard size={18} />
            <span className="truncate max-w-16">{board.name}</span>
          </button>
        ))}
        <button className="flex-1 flex flex-col items-center justify-center gap-0.5 text-[10px] text-muted" onClick={onSearch} aria-label="Search">
          <Search size={18} />
          <span>Search</span>
        </button>
        <button className="flex-1 flex flex-col items-center justify-center gap-0.5 text-[10px] text-muted relative" onClick={onNotices} aria-label="Notices">
          <Bell size={18} />
          <span>Notices</span>
          {unread > 0 && <span className="absolute top-2 right-[calc(50%-14px)] w-2 h-2 rounded-full bg-accent" />}
        </button>
        <button className="flex-1 flex flex-col items-center justify-center gap-0.5 text-[10px] text-muted" onClick={onMenu} aria-label="Menu">
          <Menu size={18} />
          <span>More</span>
        </button>
      </div>
    </nav>
  )
}
