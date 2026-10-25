/**
 * Lines of the chronicle, for the page and the card alike. A line about a
 * card that still exists, on a board the reader may open, leads to it.
 */
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'

import { clockOf, lineDetail, lineStatus, lineText, type ChronicleLine } from '../lib/chronicle'
import { focusCard } from '../lib/focusCard'
import { useDisguise } from '../lib/showcase'
import { useAuth } from '../stores/auth'
import { WhyLink } from './WhyLink'

/** Lines after which a service can be asked why. */
const TROUBLE = ['card', 'outage', 'recovery', 'forecast']

export function ChronicleRow({ line, compact = false }: { line: ChronicleLine; compact?: boolean }) {
  const { t, i18n } = useTranslation()
  const disguise = useDisguise()
  const navigate = useNavigate()
  const signedIn = useAuth((state) => state.user != null)
  const text = disguise.free(lineText(line, t, i18n.language))
  const detail = disguise.free(lineDetail(line, t))
  const where = [line.board, line.user].filter(Boolean).join(' · ')
  const target = line.target
  const go = () => {
    if (!target) return
    if (focusCard(target.widget)) return
    // A wall display behind a kiosk link has no other board to go to.
    if (signedIn) navigate(`/b/${target.board}/${target.page}`, { state: { focus: target.widget } })
  }
  const body = (
    <>
      <span className="num text-[11px] text-faint min-w-11 whitespace-nowrap flex-none pt-[2px]">{clockOf(line.when, i18n.language)}</span>
      <span className="dot flex-none mt-[6px]" data-status={lineStatus(line)} aria-hidden="true" />
      <span className="min-w-0 flex-1">
        <span className="block text-[13px] leading-snug">{text}</span>
        {!compact && (detail || where) ? (
          <span className="block text-[11px] text-muted truncate mt-px">{[detail, where].filter(Boolean).join(' · ')}</span>
        ) : null}
      </span>
    </>
  )
  // Roadmap M6: a line about a service that went wrong or came back leads to its diagnosis, at that moment.
  const why = !compact && TROUBLE.includes(line.kind) && line.level !== 'info' ? <WhyLink subject={line.subject} name={line.name} at={line.when} className="self-center px-1" /> : null
  const row = target ? (
    <button type="button" className="nd-chron-row" onClick={go} data-kind={line.kind}>{body}</button>
  ) : (
    <div className="nd-chron-row" data-kind={line.kind}>{body}</div>
  )
  return why ? <div className="flex items-start">{row}{why}</div> : row
}
