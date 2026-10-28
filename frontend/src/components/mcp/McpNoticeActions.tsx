import { useTranslation } from 'react-i18next'

import { openRequest, requestIdOf } from '../../lib/mcp'
import { useMcpTexts } from '../../lib/mcpTexts'
import type { Notice } from '../../api/types'
import { DangerMark, RequestAnswer, useRequest } from './RequestParts'

/**
 * Allow and Decline right under an approval request in the bell.
 *
 * Loaded only when such a notice is on screen, so the bell itself stays as
 * light as it was. The notice carries the id in its link; the request is read
 * to learn whether it can still be answered, so a notice for a request that
 * ran out or was answered elsewhere shows its state and no buttons.
 */
export default function McpNoticeActions({ notice }: { notice: Notice }) {
  const { t } = useTranslation()
  const ready = useMcpTexts()
  const id = requestIdOf(notice.link)
  const request = useRequest(id)
  if (!ready || id === null) return null
  if (request.isError) return <p className="text-[11px] text-faint mt-1.5">{t('mcp.request.gone')}</p>
  if (!request.data) return null
  return (
    <div className="mt-2" data-testid={`mcp-notice-${id}`}>
      {request.data.danger && openRequest(request.data) && (
        <div className="mb-1.5">
          <DangerMark />
        </div>
      )}
      <RequestAnswer request={request.data} />
    </div>
  )
}
