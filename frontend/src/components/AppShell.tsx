import { useQuery } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'

import { get } from '../api/client'
import type { BoardSummary } from '../api/types'
import { useAuth } from '../stores/auth'
import { useNotices } from '../stores/notices'
import { BackgroundLayer } from './BackgroundLayer'
import { CommandPalette } from './CommandPalette'
import { HeaderTools } from './HeaderTools'
import { LogoMark } from './Logo'
import { MobileTabBar } from './MobileTabBar'
import { NoticeDrawer } from './NoticeDrawer'

/** The frame for pages other than a board: bar with a back link, background, drawers. */
export function AppShell({ title, children }: { title: string; children: ReactNode }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const user = useAuth((state) => state.user)
  const { unread, setOpen } = useNotices()
  const [palette, setPalette] = useState(false)
  const boards = useQuery({ queryKey: ['boards'], queryFn: () => get<BoardSummary[]>('/boards') })
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setPalette((v) => !v)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
  return (
    <div className="min-h-full pb-20 md:pb-8">
      <BackgroundLayer />
      <header className="glass-strong sticky top-0 z-40 h-12 flex items-center gap-2 px-3 border-x-0 border-t-0 rounded-none">
        <Link to="/" className="btn btn-icon border-0 bg-transparent" aria-label={t('common.back')}>
          <ArrowLeft size={16} />
        </Link>
        <LogoMark size={24} />
        <span className="font-semibold text-[15px] truncate">{title}</span>
        <span className="flex-1" />
        <HeaderTools user={user} unread={unread} onNotices={() => setOpen(true)} />
      </header>
      <main>{children}</main>
      <MobileTabBar
        boards={(boards.data ?? []).filter((b) => b.in_menu).map((b) => ({ id: b.id, name: b.name, slug: b.slug }))}
        active={-1}
        onBoard={(id) => {
          const board = boards.data?.find((b) => b.id === id)
          if (board) navigate(`/b/${board.slug}`)
        }}
        onSearch={() => setPalette(true)}
        onNotices={() => setOpen(true)}
        onMenu={() => navigate('/settings')}
        unread={unread}
      />
      <NoticeDrawer />
      <CommandPalette open={palette} onClose={() => setPalette(false)} boards={boards.data ?? []} widgets={[]} />
    </div>
  )
}
