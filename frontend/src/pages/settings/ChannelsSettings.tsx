import { useQuery } from '@tanstack/react-query'
import { Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, del, get, patch, post } from '../../api/client'
import type { Channel, ChannelKind } from '../../api/types'
import { FieldInput } from '../../components/FieldInput'
import { Confirm, Field, Sheet, Switch, Toast } from '../../components/ui'
import { currentSubscription, pushSupported, subscribePush, unsubscribePush } from '../../lib/push'
import { SettingsCard } from './SettingsPage'

/** Notification channels: where outages and failed actions go. */
export function ChannelsSettings() {
  const { t } = useTranslation()
  const kinds = useQuery({ queryKey: ['channel-kinds'], queryFn: () => get<ChannelKind[]>('/channel-kinds'), staleTime: 300_000 })
  const events = useQuery({ queryKey: ['events'], queryFn: () => get<{ event: string; label: string }[]>('/events'), staleTime: 300_000 })
  const channels = useQuery({ queryKey: ['channels'], queryFn: () => get<Channel[]>('/channels') })
  const [editing, setEditing] = useState<Channel | null>(null)
  const [adding, setAdding] = useState<string | null>(null)
  const [removing, setRemoving] = useState<Channel | null>(null)
  const [toast, setToast] = useState<{ text: string; level: 'ok' | 'error' } | null>(null)
  const [pushOn, setPushOn] = useState(false)
  useEffect(() => {
    void currentSubscription().then((s) => setPushOn(Boolean(s)))
  }, [])

  const togglePush = async (on: boolean) => {
    try {
      if (on) await subscribePush()
      else await unsubscribePush()
      setPushOn(on)
      void channels.refetch()
      setToast({ text: on ? t('channels.pushOn') : t('channels.pushOff'), level: 'ok' })
    } catch (failure) {
      const reason = failure instanceof Error ? failure.message : 'error'
      setToast({ text: reason === 'denied' ? t('channels.pushDenied') : reason === 'unsupported' ? t('channels.pushUnsupported') : t('errors.network'), level: 'error' })
    }
  }

  return (
    <>
      <SettingsCard title={t('settings.channels.title')} description={t('settings.channels.help')}>
        <Switch checked={pushOn} onChange={(on) => void togglePush(on)} label={t('channels.push')} description={pushSupported() ? t('channels.pushHelp') : t('channels.pushUnsupported')} disabled={!pushSupported()} />
        <ul className="space-y-1.5 mt-3">
          {(channels.data ?? []).map((channel) => (
            <li key={channel.id} className="flex items-center gap-3 rounded-xl border border-line p-2.5">
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium truncate">
                  {channel.name} <span className="text-faint text-xs">{kinds.data?.find((k) => k.kind === channel.kind)?.label ?? channel.kind}</span>
                </div>
                <div className="text-[11px] text-muted truncate">
                  {channel.events.map((e) => events.data?.find((x) => x.event === e)?.label ?? e).join(', ') || t('channels.noEvents')}
                  {channel.last_error && <span className="text-bad"> · {channel.last_error}</span>}
                </div>
              </div>
              <span className="dot" data-status={!channel.enabled ? 'unknown' : channel.last_error ? 'bad' : 'ok'} />
              <button className="btn h-7 text-xs" onClick={() => void post<{ ok: boolean; message: string }>(`/channels/${channel.id}/test`).then((r) => setToast({ text: r.message, level: r.ok ? 'ok' : 'error' }))}>
                {t('channels.test')}
              </button>
              <button className="btn h-7 text-xs" onClick={() => setEditing(channel)}>
                {t('common.edit')}
              </button>
              <button className="btn btn-icon h-7 w-7 btn-danger" onClick={() => setRemoving(channel)} aria-label={t('common.delete')}>
                <Trash2 size={14} />
              </button>
            </li>
          ))}
        </ul>
      </SettingsCard>
      <SettingsCard title={t('channels.add')}>
        <div className="flex flex-wrap gap-1.5">
          {(kinds.data ?? []).filter((k) => k.kind !== 'webpush').map((kind) => (
            <button key={kind.kind} className="btn h-8 text-xs" onClick={() => setAdding(kind.kind)}>
              {kind.label}
            </button>
          ))}
        </div>
      </SettingsCard>
      {(editing || adding) && kinds.data && events.data && (
        <ChannelSheet
          kinds={kinds.data}
          events={events.data}
          channel={editing}
          kind={adding ?? editing?.kind ?? ''}
          onClose={() => {
            setEditing(null)
            setAdding(null)
          }}
          onSaved={() => {
            setEditing(null)
            setAdding(null)
            void channels.refetch()
          }}
        />
      )}
      <Confirm open={removing !== null} title={t('channels.remove', { name: removing?.name ?? '' })} danger onCancel={() => setRemoving(null)} onConfirm={() => { const target = removing; setRemoving(null); if (target) void del(`/channels/${target.id}`).then(() => channels.refetch()) }} />
      {toast && (
        <Toast level={toast.level} onClose={() => setToast(null)}>
          {toast.text}
        </Toast>
      )}
    </>
  )
}

function ChannelSheet({ kinds, events, channel, kind, onClose, onSaved }: { kinds: ChannelKind[]; events: { event: string; label: string }[]; channel: Channel | null; kind: string; onClose: () => void; onSaved: () => void }) {
  const { t } = useTranslation()
  const spec = kinds.find((k) => k.kind === kind)
  const [name, setName] = useState(channel?.name ?? spec?.label ?? '')
  const [config, setConfig] = useState<Record<string, unknown>>(channel?.config ?? Object.fromEntries((spec?.fields ?? []).filter((f) => f.default !== null && f.default !== undefined).map((f) => [f.name, f.default])))
  const [selected, setSelected] = useState<string[]>(channel?.events ?? ['outage', 'recovery', 'action_failed'])
  const [enabled, setEnabled] = useState(channel?.enabled ?? true)
  const [error, setError] = useState('')
  if (!spec) return null
  const save = async () => {
    setError('')
    try {
      if (channel) await patch(`/channels/${channel.id}`, { name, config, enabled, events: selected })
      else await post('/channels', { kind, name, config, enabled, events: selected })
      onSaved()
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : t('errors.network'))
    }
  }
  return (
    <Sheet
      open
      onClose={onClose}
      title={channel ? t('channels.edit', { name: channel.name }) : t('channels.new', { name: spec.label })}
      footer={
        <>
          <button className="btn" onClick={onClose}>
            {t('common.cancel')}
          </button>
          <button className="btn btn-accent" onClick={() => void save()} disabled={!name.trim()}>
            {t('common.save')}
          </button>
        </>
      }
    >
      {spec.help && <p className="text-xs text-muted mb-3">{spec.help}</p>}
      <Field label={t('channels.name')} htmlFor="c-name">
        <input id="c-name" className="input" value={name} onChange={(e) => setName(e.target.value)} />
      </Field>
      {spec.fields.map((field) => <FieldInput key={field.name} spec={field} value={config[field.name]} onChange={(value) => setConfig((c) => ({ ...c, [field.name]: value }))} />)}
      <Field label={t('channels.events')} help={t('channels.eventsHelp')}>
        <div className="flex flex-wrap gap-1.5">
          {events.filter((e) => e.event !== 'test').map((event) => {
            const on = selected.includes(event.event)
            return (
              <button key={event.event} type="button" className="btn h-8 text-xs" aria-pressed={on} onClick={() => setSelected((s) => (on ? s.filter((x) => x !== event.event) : [...s, event.event]))}>
                {event.label}
              </button>
            )
          })}
        </div>
      </Field>
      <Switch checked={enabled} onChange={setEnabled} label={t('channels.enabled')} />
      {error && (
        <p className="text-sm text-bad mt-2" role="alert">
          {error}
        </p>
      )}
    </Sheet>
  )
}
