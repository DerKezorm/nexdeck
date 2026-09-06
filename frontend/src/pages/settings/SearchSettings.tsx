import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2, Wand2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, get, put } from '../../api/client'
import { ServiceIcon } from '../../components/ServiceIcon'
import { Switch, Toast } from '../../components/ui'
import type { SearchSettings as Settings, SearchTarget } from '../../lib/search'
import { SettingsCard } from './SettingsCard'

const EMPTY: Settings = { enabled: true, targets: [] }

/**
 * Where the bar may hand a typed word to.
 *
 * The bar itself finds boards, cards and settings. Everything listed here is
 * the way out: a search engine, or a service that is already connected. The
 * shortcut is what makes it quick, so it stands next to the name.
 */
export function SearchSettings() {
  const { t } = useTranslation()
  const client = useQueryClient()
  const saved = useQuery({ queryKey: ['search-settings'], queryFn: () => get<Settings>('/settings/search') })
  const [form, setForm] = useState<Settings>(EMPTY)
  const [toast, setToast] = useState<{ text: string; level: 'ok' | 'error' } | null>(null)
  useEffect(() => {
    if (saved.data) setForm(saved.data)
  }, [saved.data])

  const change = (index: number, key: keyof SearchTarget, value: string) =>
    setForm((current) => ({ ...current, targets: current.targets.map((target, i) => (i === index ? { ...target, [key]: value } : target)) }))

  const store = async (next: Settings) => {
    try {
      const answer = await put<Settings>('/settings/search', next)
      setForm(answer)
      // The bar reads the same list; it must not keep the old one.
      await client.invalidateQueries({ queryKey: ['search-targets'] })
      setToast({ text: t('common.saved'), level: 'ok' })
    } catch (failure) {
      setToast({ text: failure instanceof ApiError ? failure.message : t('errors.network'), level: 'error' })
    }
  }

  const takeSuggestions = async () => {
    try {
      const answer = await get<{ targets: SearchTarget[] }>('/settings/search/suggestions')
      const known = new Set(form.targets.map((target) => target.url))
      const fresh = answer.targets.filter((target) => !known.has(target.url))
      if (!fresh.length) {
        setToast({ text: t('settings.search.nothingNew'), level: 'ok' })
        return
      }
      setForm((current) => ({ ...current, targets: [...current.targets, ...fresh].slice(0, 20) }))
      setToast({ text: t('settings.search.added', { count: fresh.length }), level: 'ok' })
    } catch (failure) {
      setToast({ text: failure instanceof ApiError ? failure.message : t('errors.network'), level: 'error' })
    }
  }

  return (
    <>
      <SettingsCard title={t('settings.search.title')} description={t('settings.search.help')}>
        <Switch
          checked={form.enabled}
          onChange={(enabled) => setForm((current) => ({ ...current, enabled }))}
          label={t('settings.search.enabled')}
          description={t('settings.search.enabledHelp')}
        />

        <ul className="mt-4 flex flex-col gap-2">
          {form.targets.map((target, index) => (
            <li key={index} className="grid grid-cols-[auto_1fr_auto] sm:grid-cols-[auto_10rem_1fr_4.5rem_auto] gap-2 items-center">
              <span className="w-6 flex justify-center">{target.icon ? <ServiceIcon icon={target.icon} size={18} /> : <span className="dot" data-status="unknown" />}</span>
              <input
                className="input"
                aria-label={t('settings.search.name')}
                placeholder={t('settings.search.name')}
                value={target.name}
                onChange={(e) => change(index, 'name', e.target.value)}
              />
              <input
                className="input font-mono text-[12px] col-span-3 sm:col-span-1"
                aria-label={t('settings.search.url')}
                placeholder="https://example.com/?q={query}"
                value={target.url}
                onChange={(e) => change(index, 'url', e.target.value)}
              />
              <input
                className="input text-center"
                aria-label={t('settings.search.prefix')}
                placeholder="d"
                maxLength={6}
                value={target.prefix}
                onChange={(e) => change(index, 'prefix', e.target.value)}
              />
              <button
                className="btn h-9 w-9 grid place-items-center"
                aria-label={t('settings.search.remove', { name: target.name })}
                onClick={() => setForm((current) => ({ ...current, targets: current.targets.filter((_, i) => i !== index) }))}
              >
                <Trash2 size={15} />
              </button>
            </li>
          ))}
          {form.targets.length === 0 && <li className="text-sm text-muted py-2">{t('settings.search.empty')}</li>}
        </ul>

        <div className="mt-4 flex flex-wrap gap-2">
          <button
            className="btn"
            onClick={() => setForm((current) => ({ ...current, targets: [...current.targets, { name: '', url: 'https://example.com/?q={query}', prefix: '', icon: '' }] }))}
          >
            <Plus size={15} /> {t('settings.search.add')}
          </button>
          <button className="btn" onClick={takeSuggestions}>
            <Wand2 size={15} /> {t('settings.search.fromIntegrations')}
          </button>
          <button className="btn btn-accent ml-auto" onClick={() => store(form)}>
            {t('common.save')}
          </button>
        </div>
      </SettingsCard>
      {toast && (
        <Toast level={toast.level} onClose={() => setToast(null)}>
          {toast.text}
        </Toast>
      )}
    </>
  )
}
