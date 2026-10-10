import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, get, patch } from '../../api/client'
import type { About } from '../../api/types'
import { Confirm, Field, Toast } from '../../components/ui'
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
  // The address carries the redirect addresses of the sign-in providers: the server asks before it saves (409).
  const [question, setQuestion] = useState<{ count: number; address: string; hand: number } | null>(null)
  useEffect(() => {
    if (about.data) setPublicUrl(about.data.public_url)
  }, [about.data])
  const save = (confirm: boolean) =>
    void patch('/settings', confirm ? { public_url: publicUrl, confirm_address: true } : { public_url: publicUrl })
      .then(() => about.refetch())
      .then(() => setToast({ text: t('common.saved'), level: 'ok' }))
      .catch((failure) => {
        if (failure instanceof ApiError && failure.code === 'public_url_change') {
          const { count, address, hand } = failure.detail
          return setQuestion({ count: Number(count ?? 0), address: String(address ?? ''), hand: Number(hand ?? 0) })
        }
        const text = failure instanceof ApiError ? (failure.code === 'public_url_invalid' ? t('oidc.authentik.why.unusable') : failure.message) : t('errors.network')
        setToast({ text, level: 'error' })
      })
  return (
    <>
      <SettingsCard title={t('settings.system.publicUrl')} description={t('settings.system.publicUrlHelp')}>
        <Field label={t('settings.system.publicUrl')} htmlFor="s-url">
          <div className="flex gap-2">
            <input id="s-url" className="input" type="url" placeholder="https://deck.example.com" value={publicUrl} onChange={(e) => setPublicUrl(e.target.value)} />
            <button className="btn flex-none" onClick={() => save(false)}>
              {t('common.save')}
            </button>
          </div>
        </Field>
      </SettingsCard>
      <Confirm
        open={question !== null}
        title={t('oidc.admin.address')}
        confirmLabel={t('common.save')}
        danger
        onCancel={() => setQuestion(null)}
        onConfirm={() => {
          setQuestion(null)
          save(true)
        }}
      >
        {question && (
          <div className="space-y-2 text-sm text-muted" data-testid="address-question">
            {question.count > 0 && <p>{t('oidc.admin.addressChangeConfirm', { address: question.address })}</p>}
            {question.hand > 0 && <p>{t('oidc.admin.addressChangeHand', { count: question.hand })}</p>}
          </div>
        )}
      </Confirm>
      {toast && (
        <Toast level={toast.level} onClose={() => setToast(null)}>
          {toast.text}
        </Toast>
      )}
    </>
  )
}
