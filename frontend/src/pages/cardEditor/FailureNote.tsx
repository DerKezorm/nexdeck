import { AlertTriangle } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { tLabel } from '../../i18n/texts'
import type { Failure } from './connections'

/**
 * A failure in the words a card uses for it (KARTEN-9 EC-2): English shows the server's own sentence with its
 * specifics, every other language the sentence for its code, and the hint below.
 */
export function failureText(t: (key: string, options?: Record<string, unknown>) => string, language: string, failure: Failure): string {
  if (failure.code === 'network') return t('errors.network')
  if (language.split('-')[0] === 'en') return failure.message
  return t(`errors.widget.${failure.code}`, { defaultValue: tLabel(failure.message) })
}

export function FailureNote({ failure }: { failure: Failure }) {
  const { t, i18n } = useTranslation()
  return (
    <div className="rounded-xl border border-bad/40 px-3 py-2 flex gap-2 items-start min-w-0" role="alert" data-testid="card-failure" data-code={failure.code}>
      <AlertTriangle size={18} className="text-bad flex-none mt-0.5" aria-hidden="true" />
      <div className="min-w-0">
        <p className="text-sm font-medium text-bad break-words hyphens-auto">{failureText(t, i18n.language, failure)}</p>
        {failure.hint && <p className="text-[12px] text-muted break-words hyphens-auto">{failure.hint}</p>}
      </div>
    </div>
  )
}
