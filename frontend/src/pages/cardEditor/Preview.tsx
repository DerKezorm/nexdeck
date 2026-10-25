import { useTranslation } from 'react-i18next'

import { useCardEditor } from './store'

/**
 * Where the card is shown while it is built (KARTEN-9 AC-9): beside the step on a wide screen, below it on a phone
 * (EC-5). It shows the last valid version, and says so while the text is not valid.
 *
 * The card itself is drawn here from `POST /cards/preview` with the renderers of the board, with the switches for
 * live or demo data, theme, card style, size and phone.
 */
export function Preview() {
  const { t } = useTranslation()
  const stale = useCardEditor((state) => state.card === null)
  return (
    <section className="glass rounded-2xl p-4 sm:p-5 min-w-0" aria-labelledby="card-preview-title" data-testid="card-preview">
      <h2 id="card-preview-title" className="font-semibold text-[15px] break-words hyphens-auto">
        {stale ? t('editor.preview.lastValid') : t('editor.preview.title')}
      </h2>
    </section>
  )
}
