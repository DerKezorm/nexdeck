import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'

import { AppShell } from '../components/AppShell'
import { NoticeList } from '../components/NoticeDrawer'
import { useNotices } from '../stores/notices'

export function NoticesPage() {
  const { t } = useTranslation()
  const { notices, load, markAll, markRead, remove } = useNotices()
  useEffect(() => {
    void load()
  }, [load])
  return (
    <AppShell title={t('notices.title')}>
      <div className="max-w-2xl mx-auto px-4 py-6">
        <div className="flex items-center justify-between mb-4">
          <h1 className="text-lg font-semibold">{t('notices.title')}</h1>
          <button className="btn" onClick={() => void markAll()}>
            {t('notices.markAllRead')}
          </button>
        </div>
        <NoticeList notices={notices} onRead={(id) => void markRead([id])} onRemove={(id) => void remove(id)} />
      </div>
    </AppShell>
  )
}
