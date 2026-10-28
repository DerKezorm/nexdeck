import { useBoardStreams, useStream } from '../hooks/useStream'
import { useAuth } from '../stores/auth'

/**
 * The bell's own stream, for every page that follows no board: settings,
 * system, chronicle, an approval request.
 *
 * ⚠️ Notices used to arrive only on the stream of a board, so anywhere else
 * the bell stood still until a reload, and an approval request that runs out
 * after ten minutes could pass unseen. A board's stream carries the notices
 * too, so this one is shut while a board's is open: one connection per tab.
 */
export function NoticeStream() {
  const user = useAuth((state) => state.user)
  const boards = useBoardStreams((state) => state.open)
  useStream({ enabled: Boolean(user) && boards === 0 })
  return null
}
