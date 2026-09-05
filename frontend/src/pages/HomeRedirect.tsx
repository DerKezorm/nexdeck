import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link, Navigate } from 'react-router-dom'

import { get } from '../api/client'
import type { BoardSummary } from '../api/types'
import { AppShell } from '../components/AppShell'
import { EmptyState, Spinner } from '../components/ui'
import { useAuth } from '../stores/auth'

/** ``/`` sends the user to their start board, or to the first board they may see. */
export function HomeRedirect() {
  const { t } = useTranslation()
  const user = useAuth((s) => s.user)
  const boards = useQuery({ queryKey: ['boards'], queryFn: () => get<BoardSummary[]>('/boards') })
  if (boards.isLoading) {
    return (
      <div className="min-h-full flex items-center justify-center">
        <Spinner />
      </div>
    )
  }
  const list = boards.data ?? []
  const start = list.find((b) => b.id === user?.start_board_id) ?? list[0]
  if (start) return <Navigate to={`/b/${start.slug}`} replace />
  const guest = user?.role === 'guest'
  /**
   * ⚠️ **Inside the frame, not on a bare page.** This screen stood alone, with
   * no bar and therefore no account menu: a guest with no board shared with him
   * saw a sentence and had no way out, not even to sign out. Whoever gets here
   * is the one person who needs the menu most, because nothing else is here.
   */
  return (
    <AppShell title={t('board.none.title')}>
      <div className="flex min-h-[60vh] items-center justify-center p-6">
        <EmptyState
          title={t('board.none.title')}
          body={guest ? t('board.none.guest') : t('board.none.body')}
          action={
            guest ? undefined : (
              <Link className="btn btn-accent" to="/settings/boards">
                {t('board.none.create')}
              </Link>
            )
          }
        />
      </div>
    </AppShell>
  )
}
