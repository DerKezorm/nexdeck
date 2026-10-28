import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { post } from '../../api/client'
import { WidgetCard } from '../../components/WidgetCard'
import { pickText, type CardText } from '../../lib/cardText'
import type { CardForm } from '../../lib/customCards'
import type { WidgetData, WidgetView } from '../../lib/types'
import { pixelsOf, sizesOf } from '../cardEditor/Preview'

/**
 * A card of an import file as it will look, drawn by the renderer of the board with the card's own example data
 * (KARTEN-12 AC-2). Its buttons are drawn and do nothing.
 *
 * Loaded on its own: the renderers come with it, not with the page of the settings.
 */
export default function ImportPreview({ yaml, form, name, icon }: { yaml: string; form: CardForm; name: CardText | null | undefined; icon: string }) {
  const { t, i18n } = useTranslation()
  const preview = useQuery({
    queryKey: ['import-preview', yaml],
    queryFn: () => post<WidgetData>('/cards/preview', { yaml, demo: true }),
    retry: false,
    refetchOnWindowFocus: false,
  })
  const size = sizesOf({ form })[1] ?? [2, 2]
  const pixels = pixelsOf(size, false)

  if (preview.isError) {
    return (
      <p className="text-[12px] text-muted break-words" data-testid="import-preview-failed">
        {t('cards.exchange.noPreview')}
      </p>
    )
  }
  if (!preview.data) {
    return (
      <p className="text-[12px] text-muted" role="status">
        {t('cards.exchange.previewLoading')}
      </p>
    )
  }
  const widget: WidgetView = {
    id: 0,
    kind: `custom.${form}`,
    title: pickText(name, i18n.language),
    icon: icon || 'lucide:layout-dashboard',
    link: '',
    renderer: form,
    options: {},
    integration_id: null,
    refresh_seconds: null,
    default_size: size,
  }
  return (
    <div className="nd-stage rounded-xl p-3 overflow-x-auto min-w-0" style={{ background: 'var(--nd-bg)', color: 'var(--nd-text)' }} data-testid="import-preview">
      <div style={{ width: pixels.width, height: pixels.height }}>
        <WidgetCard widget={widget} data={{ ...preview.data, meta: { ...preview.data.meta, custom: true } }} canAct onAction={() => undefined} />
      </div>
    </div>
  )
}
