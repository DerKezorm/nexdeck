import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { get } from '../api/client'
import type { About } from '../api/types'

/**
 * A line above the cards while the whole installation shows invented data.
 *
 * ⚠️ Said on the board, not only in the settings. Issue #2: a Nomad connection
 * tested fine, and its cards showed the three sample nodes, because the setup
 * wizard had switched demo mode on for everything and nothing on the board
 * said so. The way out is offered to administrators only, and not at all when
 * NEXDECK_DEMO holds the mode: the switch could not undo that.
 */
export function DemoNotice({ admin }: { admin: boolean }) {
  const { t } = useTranslation()
  const about = useQuery({ queryKey: ['about'], queryFn: () => get<About>('/about'), staleTime: 60_000 })
  if (!about.data?.demo) return null
  return (
    <p className="rounded-xl border border-warn/40 bg-warn/10 px-3 py-2 text-sm mb-3 flex flex-wrap items-center gap-x-3 gap-y-1" role="status">
      <span>{t('board.demo')}</span>
      {admin && !about.data.demo_forced && (
        <Link to="/system/integrations" className="text-accent font-medium">
          {t('board.demoOff')}
        </Link>
      )}
    </p>
  )
}
