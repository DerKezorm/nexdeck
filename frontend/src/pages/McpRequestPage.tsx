import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'

import { ApiError } from '../api/client'
import { AppShell } from '../components/AppShell'
import { DangerMark, RequestAnswer, RequestFacts, statusText, useRequest } from '../components/mcp/RequestParts'
import { Spinner } from '../components/ui'
import { openRequest } from '../lib/mcp'
import { useMcpTexts } from '../lib/mcpTexts'

/**
 * One approval request, in full (``/mcp/requests/<id>``): who asks, which card
 * and which button, the parameters as they were stored, what the press would
 * hit, until when the answer counts. The place the bell and the channels lead
 * to. A request that was answered or ran out shows its state and the result,
 * and no buttons.
 */
export function McpRequestPage() {
  const ready = useMcpTexts()
  return ready ? <Page /> : null
}

function Page() {
  const { t } = useTranslation()
  const params = useParams()
  const id = /^\d+$/.test(params.id ?? '') ? Number(params.id) : null
  const request = useRequest(id)
  const data = request.data
  const failed = id === null || request.isError
  return (
    <AppShell title={t('mcp.request.title')}>
      <div className="max-w-xl mx-auto px-4 py-6">
        {request.isLoading && id !== null && (
          <div className="flex justify-center py-10">
            <Spinner />
          </div>
        )}
        {failed && (
          <div className="glass rounded-2xl p-5" data-testid="mcp-request-gone">
            <p className="text-sm">{request.error instanceof ApiError && request.error.status !== 404 ? request.error.message : t('mcp.request.gone')}</p>
            <Link to="/notices" className="btn mt-3">
              {t('mcp.request.back')}
            </Link>
          </div>
        )}
        {data && (
          <div className={`glass rounded-2xl p-5 ${data.danger && openRequest(data) ? 'border border-bad/60' : ''}`} data-testid="mcp-request">
            <div className="flex flex-wrap items-center gap-2 mb-3">
              <h1 className="text-lg font-semibold flex-1">{t('mcp.request.heading', { program: data.key_name })}</h1>
              {data.danger && <DangerMark />}
              <span className="chip text-[11px] text-muted" data-testid="mcp-status">
                {statusText(t, data)}
              </span>
            </div>
            <p className="text-sm text-muted mb-4">{openRequest(data) ? t('mcp.request.help') : t('mcp.request.helpDone')}</p>
            <RequestFacts request={data} />
            <div className="mt-5">
              <RequestAnswer request={data} />
            </div>
          </div>
        )}
      </div>
    </AppShell>
  )
}
