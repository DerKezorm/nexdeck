import { Check, Trash2 } from 'lucide-react'
import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import type { Notice } from '../api/types'
import { useNotices } from '../stores/notices'
import { Sheet, Toast } from './ui'

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
              <div className="text-sm font-medium">{notice.title}</div>
              {notice.body && <div className="text-xs text-muted mt-0.5 whitespace-pre-wrap">{notice.body}</div>}
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
      footer={
        <>
          <Link className="btn" to="/notices" onClick={() => setOpen(false)}>
            {t('notices.all')}
          </Link>
          <button className="btn btn-accent" onClick={() => void markAll()}>
            {t('notices.markAllRead')}
          </button>
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
      <div className="font-medium">{toast.title}</div>
      {toast.body && <div className="text-xs text-muted mt-0.5">{toast.body}</div>}
    </Toast>
  )
}
