import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, get, patch } from '../../api/client'
import type { About } from '../../api/types'
import { Field, Toast } from '../../components/ui'
import { SettingsCard } from './SettingsCard'

/**
 * The public address of this installation.
 *
 * Its own page, small as it is: identity providers, Web Push and the links in
 * every notification are built from it, so a wrong value breaks three things
 * that look unrelated.
 */
export function AddressSettings() {
  const { t } = useTranslation()
  const about = useQuery({ queryKey: ['about'], queryFn: () => get<About>('/about') })
  const [publicUrl, setPublicUrl] = useState('')
  const [toast, setToast] = useState<{ text: string; level: 'ok' | 'error' } | null>(null)
  useEffect(() => {
    if (about.data) setPublicUrl(about.data.public_url)
  }, [about.data])
  return (
    <>
      <SettingsCard title={t('settings.system.publicUrl')} description={t('settings.system.publicUrlHelp')}>
        <Field label={t('settings.system.publicUrl')} htmlFor="s-url">
          <div className="flex gap-2">
            <input id="s-url" className="input" type="url" placeholder="https://deck.example.com" value={publicUrl} onChange={(e) => setPublicUrl(e.target.value)} />
            <button
              className="btn flex-none"
              onClick={() =>
                void patch('/settings', { public_url: publicUrl })
                  .then(() => about.refetch())
                  .then(() => setToast({ text: t('common.saved'), level: 'ok' }))
                  .catch((failure) => setToast({ text: failure instanceof ApiError ? failure.message : t('errors.network'), level: 'error' }))
              }
            >
              {t('common.save')}
            </button>
          </div>
        </Field>
      </SettingsCard>
      {toast && (
        <Toast level={toast.level} onClose={() => setToast(null)}>
          {toast.text}
        </Toast>
      )}
    </>
  )
}
