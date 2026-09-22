import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { get } from '../api/client'
import type { About } from '../api/types'
import { LeaveDemo } from './LeaveDemo'

/**
 * A line above the cards while the whole installation shows invented data.
 *
 * ⚠️ Said on the board, not only in the settings. Issue #2: a Nomad connection
 * tested fine, and its cards showed the three sample nodes, because the setup
 * wizard had switched demo mode on for everything and nothing on the board
 * said so. The way out is offered to administrators only, and not at all when
 * NEXDECK_DEMO holds the mode: the switch could not undo that.
 *
 * ⚠️ A plain paragraph, without a role. `status` is a live announcement and
 * the board has one already, the edit-mode hint; `note` is taken by the line
 * that tells a phone to arrange cards on a wider screen. With either role the
 * end-to-end tests found two and stopped, and the notice needs neither: it is
 * read where it stands.
 *
 * Also when the switch is off but connections are still in demo mode: a
 * demo switched off before leaving it properly existed kept its board
 * inventing data, and this notice was the only thing that could say so.
 */
export function DemoNotice({ admin }: { admin: boolean }) {
  const { t } = useTranslation()
  const about = useQuery({ queryKey: ['about'], queryFn: () => get<About>('/about'), staleTime: 60_000 })
  if (!about.data?.demo && !about.data?.demo_data) return null
  return (
    <p className="rounded-xl border border-warn/40 bg-warn/10 px-3 py-2 text-sm mb-3 flex flex-wrap items-center gap-x-3 gap-y-1">
      <span>{about.data.demo ? t('board.demo') : t('board.demoData')}</span>
      {admin && !about.data.demo_forced && <LeaveDemo className="text-accent font-medium" label={t('board.demoOff')} />}
    </p>
  )
}
