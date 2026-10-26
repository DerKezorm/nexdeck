import { useCallback, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { Confirm } from '../../../components/ui'
import { useCardEditor } from '../store'
import { hiddenIn, type Hidden } from './guided'

/**
 * The question before a choice of the guided way replaces parts it cannot show (a formula, the card's own colour
 * rules, links, an expression): what would go is listed, "Replace" does it, "Cancel" leaves the card as it is.
 * Without such parts the choice goes ahead at once. Nothing the guided way cannot say is ever dropped unasked.
 *
 * `ask(go)` runs `go` now or after "Replace"; `dialog` goes anywhere in the step's markup.
 */
export function useReplaceGuard(): { ask: (go: () => void) => void; dialog: ReactNode } {
  const { t } = useTranslation()
  const [waiting, setWaiting] = useState<{ go: () => void; hidden: Hidden[] } | null>(null)

  const ask = useCallback((go: () => void) => {
    const state = useCardEditor.getState()
    const card = state.card ?? state.lastValid?.card ?? null
    const hidden = card ? hiddenIn(card) : []
    if (!hidden.length) return go()
    setWaiting({ go, hidden })
  }, [])

  const dialog = waiting && (
    <Confirm
      open
      title={t('editor.guided.replace.title')}
      confirmLabel={t('editor.guided.replace.yes')}
      onCancel={() => setWaiting(null)}
      onConfirm={() => {
        const { go } = waiting
        setWaiting(null)
        go()
      }}
    >
      <div className="grid gap-2 min-w-0" data-testid="card-guided-replace">
        <p className="text-sm text-muted break-words hyphens-auto">{t('editor.guided.replace.lead')}</p>
        <ul className="list-disc pl-5 text-sm grid gap-0.5">
          {waiting.hidden.map((kind) => (
            <li key={kind}>{t(`editor.guided.replace.${kind}`)}</li>
          ))}
        </ul>
      </div>
    </Confirm>
  )
  return { ask, dialog }
}
