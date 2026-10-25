import { FileCode } from 'lucide-react'
import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'

import { adjustedInYaml, pathText } from '../../lib/cardDocument'
import { useCardEditor } from './store'

/**
 * "Adjusted in YAML" (KARTEN-9 AC-12): the parts of the card the editor has no field for. They are named with their
 * lines, open in the YAML view on a click, and stay exactly as they are when the card is saved.
 */
export function AdjustedBlock() {
  const { t } = useTranslation()
  const card = useCardEditor((state) => state.card)
  const goToLine = useCardEditor((state) => state.goToLine)
  const parts = useMemo(() => (card ? adjustedInYaml(card) : []), [card])
  if (!parts.length) return null
  return (
    <section className="rounded-2xl border border-line bg-surface px-4 py-3 min-w-0" aria-labelledby="card-adjusted-title" data-testid="card-adjusted">
      <h2 id="card-adjusted-title" className="flex items-center gap-2 text-sm font-semibold break-words hyphens-auto">
        <FileCode size={15} aria-hidden="true" /> {t('editor.adjusted.title')}
      </h2>
      <p className="text-[13px] text-muted mt-1 break-words hyphens-auto">{t('editor.adjusted.body')}</p>
      <ul className="mt-2 grid gap-1.5">
        {parts.map((part) => (
          <li key={pathText(part.path)} className="flex flex-wrap items-center gap-2 text-[13px] min-w-0">
            <code className="chip !py-0 font-mono break-all">{pathText(part.path)}</code>
            {part.line !== null && <span className="text-faint">{t('editor.adjusted.line', { line: part.line })}</span>}
            <button type="button" className="text-accent hover:underline" onClick={() => goToLine(part.line ?? 1)}>
              {t('editor.adjusted.open')}
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
