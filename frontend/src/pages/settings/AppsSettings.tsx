import { useQuery } from '@tanstack/react-query'
import { Pencil, Plus, Trash2, X } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, del, get, patch, post } from '../../api/client'
import type { AppAddress, AppEntry } from '../../api/types'
import { IconPicker } from '../../components/IconPicker'
import { ServiceIcon } from '../../components/ServiceIcon'
import { Confirm, Field, Select, Sheet } from '../../components/ui'
import { SettingsCard } from './SettingsCard'

interface Draft {
  id: number | null
  name: string
  icon: string
  description: string
  addresses: AppAddress[]
  home: string
  away: string
}

const EMPTY: Draft = { id: null, name: '', icon: '', description: '', addresses: [{ label: '', url: '' }], home: '', away: '' }

/**
 * The app catalog (issue #37): an app set up once, with every address it is
 * reached by, and placed as a tile on any board. A tile that follows an app
 * changes with it, so an address is changed here and nowhere else.
 */
export function AppsSettings() {
  const { t } = useTranslation()
  const apps = useQuery({ queryKey: ['apps'], queryFn: () => get<AppEntry[]>('/apps') })
  const [draft, setDraft] = useState<Draft | null>(null)
  const [removing, setRemoving] = useState<AppEntry | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const open = (app: AppEntry | null) => {
    setError('')
    setDraft(app ? { id: app.id, name: app.name, icon: app.icon, description: app.description, addresses: app.addresses.map((one) => ({ ...one })), home: app.home, away: app.away } : { ...EMPTY, addresses: [{ label: '', url: '' }] })
  }

  const setAddress = (index: number, change: Partial<AppAddress>) =>
    setDraft((d) => (d ? { ...d, addresses: d.addresses.map((one, at) => (at === index ? { ...one, ...change } : one)) } : d))

  const save = async () => {
    if (!draft) return
    setBusy(true)
    setError('')
    // A label that no longer names an address cannot stay home or away.
    const labels = new Set(draft.addresses.map((one) => one.label.trim()))
    const body = {
      name: draft.name.trim(),
      icon: draft.icon,
      description: draft.description.trim(),
      addresses: draft.addresses.map((one) => ({ label: one.label.trim(), url: one.url.trim() })),
      home: labels.has(draft.home) ? draft.home : '',
      away: labels.has(draft.away) ? draft.away : '',
    }
    try {
      if (draft.id === null) await post('/apps', body)
      else await patch(`/apps/${draft.id}`, body)
      await apps.refetch()
      setDraft(null)
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : t('errors.network'))
    } finally {
      setBusy(false)
    }
  }

  const labelChoices = (draft?.addresses ?? []).filter((one) => one.label.trim()).map((one) => ({ value: one.label.trim(), label: one.label.trim() }))

  return (
    <>
      <SettingsCard title={t('apps.title')}>
        <p className="text-sm text-muted mb-3">{t('apps.lead')}</p>
        {!draft && error && (
          <p className="text-sm text-bad mb-3" role="alert">
            {error}
          </p>
        )}
        {apps.data?.length ? (
          <ul className="divide-y divide-line mb-3">
            {apps.data.map((app) => (
              <li key={app.id} className="flex items-center gap-3 py-2">
                <ServiceIcon icon={app.icon} size={22} />
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium truncate">{app.name}</div>
                  <div className="text-[11px] text-muted truncate">
                    {app.addresses.map((one) => one.label).join(' · ')}
                    {' · '}
                    {t('apps.tiles', { count: app.tiles })}
                  </div>
                </div>
                <button className="btn btn-icon btn-flat" onClick={() => open(app)} aria-label={t('apps.editNamed', { name: app.name })} title={t('apps.edit')}>
                  <Pencil size={15} />
                </button>
                <button className="btn btn-icon btn-flat btn-danger" onClick={() => setRemoving(app)} aria-label={t('apps.deleteThis', { name: app.name })} title={t('apps.delete')}>
                  <Trash2 size={15} />
                </button>
              </li>
            ))}
          </ul>
        ) : (
          apps.isSuccess && <p className="text-sm text-faint mb-3">{t('apps.none')}</p>
        )}
        <button className="btn btn-accent" onClick={() => open(null)}>
          <Plus size={15} /> {t('apps.add')}
        </button>
      </SettingsCard>

      {draft && (
        <Sheet
          open
          onClose={() => setDraft(null)}
          title={draft.id === null ? t('apps.add') : t('apps.edit')}
          footer={
            <>
              <button className="btn" onClick={() => setDraft(null)}>
                {t('common.cancel')}
              </button>
              <button className="btn btn-accent" onClick={() => void save()} disabled={busy || !draft.name.trim()}>
                {t('common.save')}
              </button>
            </>
          }
        >
          {error && (
            <p className="text-sm text-bad mb-3 rounded-lg border border-bad/40 px-3 py-2" role="alert">
              {error}
            </p>
          )}
          <Field label={t('apps.name')} htmlFor="app-name">
            <input id="app-name" className="input" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
          </Field>
          <IconPicker value={draft.icon} onChange={(icon) => setDraft({ ...draft, icon })} label={t('apps.icon')} />
          <Field label={t('apps.description')} htmlFor="app-description">
            <input id="app-description" className="input" value={draft.description} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
          </Field>
          <fieldset className="mb-3">
            <legend className="text-[13px] font-medium mb-1">{t('apps.addresses')}</legend>
            <p className="text-[11px] text-muted mb-2">{t('apps.addressesHelp')}</p>
            {draft.addresses.map((address, index) => (
              <div key={index} className="flex gap-2 mb-2">
                <input
                  className="input w-32 flex-none"
                  value={address.label}
                  placeholder={t('apps.labelPlaceholder')}
                  aria-label={t('apps.label', { number: index + 1 })}
                  onChange={(e) => setAddress(index, { label: e.target.value })}
                />
                <input
                  className="input flex-1 min-w-0"
                  type="url"
                  value={address.url}
                  placeholder="https://"
                  aria-label={t('apps.url', { number: index + 1 })}
                  onChange={(e) => setAddress(index, { url: e.target.value })}
                />
                <button
                  className="btn btn-icon btn-flat flex-none"
                  disabled={draft.addresses.length === 1}
                  onClick={() => setDraft({ ...draft, addresses: draft.addresses.filter((_, at) => at !== index) })}
                  aria-label={t('apps.removeAddress', { number: index + 1 })}
                  title={t('apps.removeAddress', { number: index + 1 })}
                >
                  <X size={15} />
                </button>
              </div>
            ))}
            {draft.addresses.length < 8 && (
              <button className="btn h-8 text-xs" onClick={() => setDraft({ ...draft, addresses: [...draft.addresses, { label: '', url: '' }] })}>
                <Plus size={14} /> {t('apps.addAddress')}
              </button>
            )}
          </fieldset>
          <div className="grid grid-cols-2 gap-2">
            <Field label={t('apps.home')} htmlFor="app-home">
              <Select id="app-home" value={draft.home} onChange={(home) => setDraft({ ...draft, home })} options={[{ value: '', label: t('apps.notSet') }, ...labelChoices]} />
            </Field>
            <Field label={t('apps.away')} htmlFor="app-away">
              <Select id="app-away" value={draft.away} onChange={(away) => setDraft({ ...draft, away })} options={[{ value: '', label: t('apps.notSet') }, ...labelChoices]} />
            </Field>
          </div>
          <p className="text-[11px] text-muted">{t('apps.automaticHelp')}</p>
        </Sheet>
      )}

      <Confirm
        open={removing !== null}
        title={t('apps.deleteNamed', { name: removing?.name ?? '' })}
        body={t('apps.deleteBody', { count: removing?.tiles ?? 0 })}
        danger
        onCancel={() => setRemoving(null)}
        onConfirm={() => {
          const app = removing
          setRemoving(null)
          if (app) void del(`/apps/${app.id}`).then(() => apps.refetch()).catch((failure) => setError(failure instanceof ApiError ? failure.message : t('errors.network')))
        }}
      />
    </>
  )
}
