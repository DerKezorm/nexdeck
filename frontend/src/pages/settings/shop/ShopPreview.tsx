import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'

import { ApiError, post } from '../../../api/client'
import { WidgetCard } from '../../../components/WidgetCard'
import { entryPath, previewForm, type ShopEntry } from '../../../lib/cardShop'
import { pickText } from '../../../lib/cardText'
import type { WidgetData, WidgetView } from '../../../lib/types'
import { pixelsOf, sizesOf } from '../../cardEditor/Preview'

/**
 * A card of the shop with the data of one of the administrator's own connections, drawn by the renderer of the board
 * (KARTEN-14 AC-6). Nothing is installed. Its buttons are drawn and do nothing.
 *
 * Loaded on its own: the renderers come with it, not with the page of the settings.
 */
export default function ShopPreview({ entry, connection }: { entry: ShopEntry; connection: number }) {
  const { t, i18n } = useTranslation()
  const preview = useQuery({
    queryKey: ['workshop-preview', entry.id, entry.version, connection],
    queryFn: () => post<WidgetData>(`/workshop/entries/${entryPath(entry)}/preview`, { integration_id: connection }),
    retry: false,
    refetchOnWindowFocus: false,
  })

  if (preview.isError) {
    const failure = preview.error
    return (
      <p className="text-sm text-bad break-words" role="alert" data-testid="shop-preview-failed">
        {failure instanceof ApiError ? failure.message : t('errors.network')}
      </p>
    )
  }
  if (!preview.data) {
    return (
      <p className="text-sm text-muted" role="status">
        {t('cards.exchange.previewLoading')}
      </p>
    )
  }
  const form = previewForm(preview.data)
  const size = sizesOf({ form })[1] ?? [2, 2]
  const pixels = pixelsOf(size, false)
  const widget: WidgetView = {
    id: 0,
    kind: `custom.${form}`,
    title: pickText(entry.name, i18n.language),
    icon: entry.requires[0]?.icon || 'lucide:layout-dashboard',
    link: '',
    renderer: form,
    options: {},
    integration_id: connection,
    refresh_seconds: null,
    default_size: size,
  }
  return (
    <div className="nd-stage rounded-xl p-3 overflow-x-auto min-w-0" style={{ background: 'var(--nd-bg)', color: 'var(--nd-text)' }} data-testid="shop-preview">
      <div style={{ width: pixels.width, height: pixels.height }}>
        <WidgetCard widget={widget} data={{ ...preview.data, meta: { ...preview.data.meta, custom: true } }} canAct onAction={() => undefined} />
      </div>
    </div>
  )
}
