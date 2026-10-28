import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { post } from '../../api/client'
import { WidgetCard } from '../../components/WidgetCard'
import { parseCard, readAt } from '../../lib/cardDocument'
import { pickText, type CardText } from '../../lib/cardText'
import type { CardForm } from '../../lib/customCards'
import type { WidgetData, WidgetView } from '../../lib/types'
import { pixelsOf, sizesOf } from './Preview'

const FORMS: CardForm[] = ['value', 'stats', 'list', 'posters', 'builder']

/**
 * A card that is only proposed, drawn small with its example data (KARTEN-17 AC-5, KARTEN-18 AC-5): in the editor
 * beside the summary, in the chat under the answer. The same frame and renderers as the board; buttons are drawn and
 * do nothing. It reads nothing from the editor, so it works wherever it stands.
 */
export function DraftPreview({ yaml }: { yaml: string }) {
  const { t, i18n } = useTranslation()
  const [data, setData] = useState<WidgetData | null>(null)
  const [failed, setFailed] = useState(false)
  const parsed = useMemo(() => parseCard(yaml), [yaml])
  const plain = useMemo(() => (parsed.ok ? (parsed.card.doc.toJS() as Record<string, unknown>) : {}), [parsed])
  const form = (FORMS.includes(plain.form as CardForm) ? plain.form : 'value') as CardForm

  useEffect(() => {
    let gone = false
    setData(null)
    setFailed(false)
    post<WidgetData>('/cards/preview', { yaml, demo: true })
      .then((answer) => {
        if (!gone) setData({ ...answer, meta: { ...answer.meta, custom: true } })
      })
      .catch(() => {
        if (!gone) setFailed(true)
      })
    return () => {
      gone = true
    }
  }, [yaml])

  if (!parsed.ok || failed) {
    return (
      <p className="text-[12px] text-muted break-words hyphens-auto" data-testid="draft-preview-failed">
        {t('editor.ai.previewFailed')}
      </p>
    )
  }
  const size = sizesOf(plain)[1] ?? sizesOf(plain)[0]
  const pixels = pixelsOf(size, true)
  const widget: WidgetView = {
    id: 0,
    kind: `custom.${form}`,
    title: pickText(readAt(parsed.card, ['name']) as CardText, i18n.language),
    icon: 'lucide:layout-dashboard',
    link: '',
    renderer: form,
    options: {},
    integration_id: null,
    refresh_seconds: null,
    default_size: size,
  }
  return (
    <div className="nd-stage rounded-xl p-2 overflow-x-auto min-w-0" style={{ background: 'var(--nd-bg)', color: 'var(--nd-text)' }} data-testid="draft-preview">
      <div style={{ width: pixels.width, height: pixels.height }} className="max-w-none">
        {data ? (
          <WidgetCard widget={widget} data={data} canAct />
        ) : (
          <div className="h-full grid place-items-center text-[12px] text-muted">{t('editor.preview.waiting')}</div>
        )}
      </div>
    </div>
  )
}
