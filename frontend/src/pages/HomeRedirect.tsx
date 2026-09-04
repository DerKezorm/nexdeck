import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link, Navigate } from 'react-router-dom'

import { get } from '../api/client'
import type { BoardSummary } from '../api/types'
import { BackgroundLayer } from '../components/BackgroundLayer'
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
  return (
    <div className="min-h-full flex items-center justify-center p-6">
      <BackgroundLayer />
      <EmptyState
        title={t('board.none.title')}
        body={t('board.none.body')}
        action={
          user?.role !== 'guest' ? (
            <Link className="btn btn-accent" to="/settings/boards">
              {t('board.none.create')}
            </Link>
          ) : undefined
        }
      />
    </div>
  )
}
