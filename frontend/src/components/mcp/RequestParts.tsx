import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, get } from '../../api/client'
import { factText } from '../../lib/assistant'
import { decide, openRequest, resultText, type McpRequest } from '../../lib/mcp'
import { tLabel } from '../../i18n/texts'

/** One request of the account, read from the server. A missing or foreign one answers the same way: not found. */
export function useRequest(id: number | null) {
  return useQuery({
    queryKey: ['mcp-request', id],
    queryFn: () => get<McpRequest>(`/mcp/requests/${id}`),
    enabled: id !== null,
    retry: false,
  })
}

const STATUSES = ['waiting', 'approved', 'declined', 'expired', 'failed']

/** The state of a request in words. A state this browser does not know is shown as the server wrote it. */
export function statusText(t: (key: string) => string, request: McpRequest, now = Date.now()): string {
  const state = request.status === 'waiting' && !openRequest(request, now) ? 'expired' : request.status
  return STATUSES.includes(state) ? t(`mcp.request.status.${state}`) : state
}

/** The mark on a dangerous button: it is asked about every time, whatever the key is allowed. */
export function DangerMark() {
  const { t } = useTranslation()
  return (
    <span className="chip text-[11px] text-bad inline-flex items-center gap-1" data-testid="mcp-danger">
      <AlertTriangle size={11} />
      {t('mcp.request.danger')}
    </span>
  )
}

/**
 * Allow and Decline for a request that is still waiting; for any other it
 * shows the state and nothing to press. The server decides again: a request
 * answered meanwhile, or run out, comes back as a conflict and is re-read.
 */
export function RequestAnswer({ request }: { request: McpRequest }) {
  const { t } = useTranslation()
  const client = useQueryClient()
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState('')
  if (!openRequest(request)) {
    return (
      <p className="text-sm text-muted" data-testid="mcp-state">
        {statusText(t, request)}
      </p>
    )
  }
  const answer = async (verb: 'approve' | 'decline') => {
    setBusy(true)
    setFailure('')
    try {
      await decide(request.id, verb)
    } catch (error) {
      setFailure(error instanceof ApiError ? (error.status === 409 ? t('mcp.request.conflict') : error.message) : t('errors.network'))
    } finally {
      await client.invalidateQueries({ queryKey: ['mcp-request', request.id] })
      setBusy(false)
    }
  }
  return (
    <div>
      <div className="flex flex-wrap gap-2">
        <button className={`btn ${request.danger ? 'btn-danger' : 'btn-accent'}`} disabled={busy} onClick={() => void answer('approve')}>
          {t('mcp.request.allow')}
        </button>
        <button className="btn" disabled={busy} onClick={() => void answer('decline')}>
          {t('mcp.request.decline')}
        </button>
      </div>
      {failure && (
        <p className="text-xs text-bad mt-2" role="alert">
          {failure}
        </p>
      )}
    </div>
  )
}

/** Everything about a request but its buttons: who asks, what it would press, what that would hit, until when. */
export function RequestFacts({ request }: { request: McpRequest }) {
  const { t } = useTranslation()
  const params = Object.entries(request.params ?? {})
  const result = resultText(request.result)
  const rows: [string, string][] = [
    [t('mcp.request.program'), request.key_name],
    [t('mcp.request.tool'), request.tool],
    [t('mcp.request.card'), request.card],
    [t('mcp.request.board'), request.board],
    [t('mcp.request.button'), tLabel(request.label)],
  ]
  return (
    <div>
      <dl className="grid grid-cols-[110px_1fr] gap-x-3 gap-y-1.5 text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-muted">{label}</dt>
            <dd className="min-w-0 break-words">{value}</dd>
          </div>
        ))}
        {params.length > 0 && (
          <>
            <dt className="text-muted">{t('mcp.request.params')}</dt>
            <dd className="min-w-0">
              <ul className="num text-xs space-y-0.5" data-testid="mcp-params">
                {params.map(([key, value]) => (
                  <li key={key}>
                    {key}: {typeof value === 'string' ? value : JSON.stringify(value)}
                  </li>
                ))}
              </ul>
            </dd>
          </>
        )}
        <dt className="text-muted">{t('mcp.request.until')}</dt>
        <dd>{new Date(request.expires_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</dd>
      </dl>
      {request.impact.length > 0 && (
        <div className="mt-3">
          <p className="text-xs font-medium text-muted">{t('mcp.request.impact')}</p>
          <ul className="mt-1 text-[12.5px] text-muted" data-testid="mcp-impact">
            {request.impact.map((fact, index) => (
              <li key={index}>{factText(t, fact)}</li>
            ))}
          </ul>
        </div>
      )}
      {result && request.status !== 'waiting' && (
        <div className="mt-3">
          <p className="text-xs font-medium text-muted">{t('mcp.request.result')}</p>
          <pre className="num text-xs whitespace-pre-wrap rounded-lg border border-line p-2 mt-1" data-testid="mcp-result">
            {result}
          </pre>
        </div>
      )}
    </div>
  )
}
