import { Check, Trash2 } from 'lucide-react'
import { lazy, Suspense, useEffect, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import type { Notice } from '../api/types'
import { useNotices } from '../stores/notices'
import { Confirm, Sheet, Toast } from './ui'

// Allow and Decline for an approval request (MCP), fetched only when one is on screen.
const McpNoticeActions = lazy(() => import('./mcp/McpNoticeActions'))
// The words of a notice about MCP in the language on screen, likewise.
const McpNoticeText = lazy(() => import('./mcp/McpNoticeText'))

/** Title and body of a notice. Those about MCP are worded from their fields; the rest come as the server wrote them. */
function NoticeWords({ notice, render }: { notice: Notice; render: (title: string, body: string) => ReactNode }) {
  if (!notice.facts && notice.event !== 'mcp_request') return <>{render(notice.title, notice.body)}</>
  return (
    <Suspense fallback={render(notice.title, notice.body)}>
      <McpNoticeText notice={notice} render={render} />
    </Suspense>
  )
}

const LEVEL_DOT: Record<string, string> = { info: 'ok', warn: 'warn', error: 'bad' }

export function NoticeList({ notices, onRead, onRemove }: { notices: Notice[]; onRead?: (id: number) => void; onRemove?: (id: number) => void }) {
  const { t } = useTranslation()
  if (!notices.length) return <p className="text-sm text-muted">{t('notices.empty')}</p>
  return (
    <ul className="space-y-2">
      {notices.map((notice) => (
        <li key={notice.id} className={`rounded-xl border border-line p-3 ${notice.read_at ? 'opacity-60' : 'bg-surface-hover'}`}>
          <div className="flex items-start gap-2">
            <span className="dot mt-1.5" data-status={LEVEL_DOT[notice.level] ?? 'unknown'} />
            <div className="min-w-0 flex-1">
              <NoticeWords
                notice={notice}
                render={(title, body) => (
                  <>
                    <div className="text-sm font-medium">{title}</div>
                    {body && <div className="text-xs text-muted mt-0.5 whitespace-pre-wrap">{body}</div>}
                  </>
                )}
              />
              {notice.event === 'mcp_request' && (
                <Suspense fallback={null}>
                  <McpNoticeActions notice={notice} />
                </Suspense>
              )}
              <div className="text-[11px] text-faint mt-1">
                {new Date(notice.created_at).toLocaleString()}
                {notice.link && (
                  <>
                    {' · '}
                    <Link to={notice.link} className="text-accent">
                      {t('common.open')}
                    </Link>
                  </>
                )}
              </div>
            </div>
            {!notice.read_at && onRead && (
              <button className="btn btn-icon h-7 w-7 btn-flat" onClick={() => onRead(notice.id)} aria-label={t('notices.markRead')}>
                <Check size={14} />
              </button>
            )}
            {onRemove && (
              <button className="btn btn-icon h-7 w-7 btn-flat btn-danger" onClick={() => onRemove(notice.id)} aria-label={t('common.delete')}>
                <Trash2 size={14} />
              </button>
            )}
          </div>
        </li>
      ))}
    </ul>
  )
}

/** "Delete all", next to "Mark all as read" (issue #36). Unread ones go too, so it asks first. */
export function DeleteAllNotices() {
  const { t } = useTranslation()
  const { notices, removeAll } = useNotices()
  const [asking, setAsking] = useState(false)
  return (
    <>
      <button className="btn btn-danger whitespace-nowrap" onClick={() => setAsking(true)} disabled={!notices.length}>
        {t('notices.deleteAll')}
      </button>
      <Confirm
        open={asking}
        danger
        title={t('notices.deleteAllTitle')}
        body={t('notices.deleteAllBody', { count: notices.length })}
        confirmLabel={t('notices.deleteAll')}
        onCancel={() => setAsking(false)}
        onConfirm={() => {
          setAsking(false)
          void removeAll()
        }}
      />
    </>
  )
}

export function NoticeDrawer() {
  const { t } = useTranslation()
  const { open, setOpen, notices, load, markAll, markRead, remove } = useNotices()
  useEffect(() => {
    if (open) void load()
  }, [open, load])
  return (
    <Sheet
      open={open}
      onClose={() => setOpen(false)}
      title={t('notices.title')}
      // ⚠️ Three labels in one row do not fit a narrow drawer or a phone in
      // German ("Alle als gelesen markieren"): each wrapped inside its button
      // and ran out of it. The two that act on the list stay together and
      // drop to a second row under the link when the row is too short.
      footer={
        <>
          <Link className="btn mr-auto whitespace-nowrap" to="/notices" onClick={() => setOpen(false)}>
            {t('notices.all')}
          </Link>
          <div className="flex flex-wrap justify-end gap-2" data-testid="notice-actions">
            <DeleteAllNotices />
            <button className="btn btn-accent whitespace-nowrap" onClick={() => void markAll()}>
              {t('notices.markAllRead')}
            </button>
          </div>
        </>
      }
    >
      <NoticeList notices={notices} onRead={(id) => void markRead([id])} onRemove={(id) => void remove(id)} />
    </Sheet>
  )
}

export function NoticeToast() {
  const { toast, dismissToast } = useNotices()
  if (!toast) return null
  return (
    <Toast onClose={dismissToast} level={toast.level === 'error' ? 'error' : toast.level === 'warn' ? 'warn' : 'info'}>
      <NoticeWords
        notice={toast}
        render={(title, body) => (
          <>
            <div className="font-medium">{title}</div>
            {body && <div className="text-xs text-muted mt-0.5">{body}</div>}
          </>
        )}
      />
    </Toast>
  )
}
