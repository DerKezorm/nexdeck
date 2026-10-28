import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { post } from '../api/client'
import { pickText, type CardText } from '../lib/cardText'
import { useAuth } from '../stores/auth'

/** One custom card or own integration a board file carries, and how it stands against this installation. */
export interface BoardDefinition {
  type: 'card' | 'integration' | 'unknown'
  /** `card:<slug>` or `integration:<short>`. */
  id: string
  name?: CardText | null
  /** `unknown` for somebody who is not an administrator: the server tells him no more than his own file says. */
  status: 'missing' | 'same' | 'different' | 'unknown'
}

/** How long a text rests before the server is asked what its definitions are. */
export const CHECK_MS = 500

/**
 * What the board file in `text` carries of custom cards and own integrations (`POST /boards/import/check`), and the
 * choice about them (KARTEN-12 AC-6, AC-7).
 *
 * Only an administrator may have the missing ones created; anyone else's import sends `skip`, and the cards of the
 * board then say that their definition is missing. A text the check does not understand shows nothing here: the
 * import itself names what is wrong with it.
 */
export function useBoardDefinitions(text: string) {
  const admin = useAuth((state) => state.user?.role === 'admin')
  const [found, setFound] = useState<{ text: string; list: BoardDefinition[]; canCreate: boolean } | null>(null)
  const [create, setCreate] = useState(true)

  useEffect(() => {
    if (!text.trim()) return
    let current = true
    const timer = window.setTimeout(() => {
      post<{ can_create?: boolean; definitions?: BoardDefinition[] }>('/boards/import/check', { yaml_text: text })
        .then((answer) => current && setFound({ text, list: answer.definitions ?? [], canCreate: answer.can_create === true }))
        .catch(() => current && setFound({ text, list: [], canCreate: false }))
    }, CHECK_MS)
    return () => {
      current = false
      window.clearTimeout(timer)
    }
  }, [text])

  const definitions = found && found.text === text ? found.list : []
  const missing = definitions.some((one) => one.status === 'missing')
  // The server says whether this person may have them made; the role is only the answer before it has spoken.
  const mayCreate = found && found.text === text ? found.canCreate && admin : false
  // The extra field of the import: left out when the file carries nothing of the kind.
  const field: { definitions?: 'create' | 'skip' } = definitions.length === 0 ? {} : { definitions: mayCreate && create && missing ? 'create' : 'skip' }
  return { definitions, missing, mayCreate, create, setCreate, field }
}

/** The section "Custom cards in this board" of the import: the list, and for an administrator the tick. */
export function BoardDefinitions({ state }: { state: ReturnType<typeof useBoardDefinitions> }) {
  const { t, i18n } = useTranslation()
  const { definitions, missing, mayCreate, create, setCreate } = state
  if (definitions.length === 0) return null
  return (
    <section className="mt-3 mb-3 rounded-xl border border-line p-3" aria-labelledby="board-definitions-title" data-testid="board-definitions">
      <h3 id="board-definitions-title" className="text-sm font-medium mb-2">
        {t('cards.exchange.board.title')}
      </h3>
      <ul className="grid gap-1">
        {definitions.map((one) => (
          <li key={one.id} className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm min-w-0">
            {one.type !== 'unknown' && <span className="chip !py-0">{t(one.type === 'card' ? 'cards.exchange.card' : 'cards.exchange.integration')}</span>}
            <span className="break-words min-w-0">{pickText(one.name, i18n.language) || one.id.slice(one.id.indexOf(':') + 1)}</span>
            <span className="text-[12px] text-muted">{t(`cards.exchange.board.${one.status}`)}</span>
          </li>
        ))}
      </ul>
      {(missing || !mayCreate) &&
        (mayCreate ? (
          <label className="mt-3 flex items-center gap-2 text-sm">
            <input type="checkbox" className="accent-accent" checked={create} onChange={(event) => setCreate(event.target.checked)} />
            {t('cards.exchange.board.create')}
          </label>
        ) : (
          <p className="mt-3 text-[12px] text-muted" role="note">
            {t('cards.exchange.board.askAdmin')}
          </p>
        ))}
    </section>
  )
}
