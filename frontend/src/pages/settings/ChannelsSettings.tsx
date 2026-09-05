import { useQuery } from '@tanstack/react-query'
import { HelpCircle, Pencil, Plus, Power, Send, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, del, get, patch, post } from '../../api/client'
import type { Channel, ChannelKind } from '../../api/types'
import { FieldInput } from '../../components/FieldInput'
import { ServiceIcon } from '../../components/ServiceIcon'
import { Confirm, Field, Switch, Toast } from '../../components/ui'
import { tAdapter } from '../../i18n/texts'
import { currentSubscription, pushSupported, subscribePush, unsubscribePush } from '../../lib/push'
import { GUIDES, KIND_ICONS, hasGuide } from './channelGuides'
import { SettingsCard } from './SettingsCard'

type Notice = { text: string; level: 'ok' | 'error' }
type EventSpec = { event: string; label: string }

/** Which events a new channel starts with: the ones nobody wants to miss. */
const DEFAULT_EVENTS = ['outage', 'recovery', 'action_failed']

/**
 * Where nexdeck writes when something happens.
 *
 * One row of services, the ways you have set up as tiles below it, and the one
 * you are working on opened underneath. A service can hold as many as you like:
 * one Telegram chat for outages, another for everything, a mail address for the
 * rest. The guide next to the fields stays open until the first one works.
 */
export function ChannelsSettings() {
  const { t } = useTranslation()
  const kinds = useQuery({ queryKey: ['channel-kinds'], queryFn: () => get<ChannelKind[]>('/channel-kinds'), staleTime: 300_000 })
  const events = useQuery({ queryKey: ['events'], queryFn: () => get<EventSpec[]>('/events'), staleTime: 300_000 })
  const channels = useQuery({ queryKey: ['channels'], queryFn: () => get<Channel[]>('/channels') })
  const [kind, setKind] = useState('')
  /** ``null`` nothing open, ``'new'`` adding, otherwise the channel being edited. */
  const [open, setOpen] = useState<number | 'new' | null>(null)
  const [removing, setRemoving] = useState<Channel | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)

  const specs = (kinds.data ?? []).filter((k) => k.kind !== 'webpush')
  const current = kind || specs[0]?.kind || ''
  const spec = specs.find((k) => k.kind === current)
  const mine = (channels.data ?? []).filter((c) => c.kind === current)
  const editing = typeof open === 'number' ? mine.find((c) => c.id === open) : undefined
  const fail = (failure: unknown) => setNotice({ text: failure instanceof ApiError ? failure.message : t('errors.network'), level: 'error' })

  return (
    <>
      <ThisBrowser onNotice={setNotice} onChanged={() => void channels.refetch()} />

      <SettingsCard title={t('settings.channels.title')} description={t('settings.channels.help')}>
        {/* One tab per service, with its logo. The count says where something
            is already set up, so the page answers "what do I have" at a glance. */}
        <div className="flex flex-wrap gap-1.5 mb-4" role="tablist" aria-label={t('settings.channels.title')}>
          {specs.map((entry) => {
            const count = (channels.data ?? []).filter((c) => c.kind === entry.kind).length
            const active = entry.kind === current
            return (
              <button
                key={entry.kind}
                role="tab"
                aria-selected={active}
                className={`flex items-center gap-2 h-9 px-3 rounded-xl border text-sm transition-colors ${active ? 'border-accent/50 bg-accent-soft text-accent font-medium' : 'border-line text-muted hover:text-ink hover:bg-surface-hover'}`}
                onClick={() => {
                  setKind(entry.kind)
                  setOpen(null)
                }}
              >
                <ServiceIcon icon={KIND_ICONS[entry.kind] ?? 'lucide:bell'} size={16} />
                {entry.label}
                {count > 0 && <span className="num text-[11px] text-faint">{count}</span>}
              </button>
            )
          })}
        </div>

        {/* The ways of this service, and the tile that adds one. While one is
            open the others step aside; what is being worked on should be plain. */}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {mine
            .filter((channel) => open === null || open === channel.id)
            .map((channel) => (
              <ChannelTile
                key={channel.id}
                channel={channel}
                events={events.data ?? []}
                active={open === channel.id}
                onEdit={() => setOpen(open === channel.id ? null : channel.id)}
                onToggle={() =>
                  void patch(`/channels/${channel.id}`, { enabled: !channel.enabled })
                    .then(() => channels.refetch())
                    .catch(fail)
                }
                onRemove={() => setRemoving(channel)}
              />
            ))}
          {(open === null || open === 'new') && (
            <button
              className={`flex min-h-24 flex-col items-center justify-center gap-1 rounded-2xl border border-dashed text-sm transition-colors ${open === 'new' ? 'border-accent/60 bg-accent-soft text-accent' : 'border-line text-muted hover:border-line-strong hover:text-ink'}`}
              onClick={() => setOpen(open === 'new' ? null : 'new')}
            >
              <Plus size={18} />
              {t('channels.addOne', { label: spec?.label ?? '' })}
            </button>
          )}
        </div>

        {mine.length === 0 && open === null && <p className="text-sm text-muted mt-3">{t('channels.emptyHint')}</p>}
      </SettingsCard>

      {spec && (open === 'new' || editing) && (
        <ChannelEditor
          key={editing ? editing.id : 'new'}
          spec={spec}
          channel={editing ?? null}
          events={events.data ?? []}
          onNotice={setNotice}
          onSaved={(saved) => {
            setOpen(saved.id)
            void channels.refetch()
          }}
          onClose={() => setOpen(null)}
        />
      )}

      <Confirm
        open={removing !== null}
        title={t('channels.remove', { name: removing?.name ?? '' })}
        danger
        onCancel={() => setRemoving(null)}
        onConfirm={() => {
          const target = removing
          setRemoving(null)
          if (!target) return
          void del(`/channels/${target.id}`)
            .then(() => {
              setOpen(null)
              return channels.refetch()
            })
            .catch(fail)
        }}
      />
      {notice && (
        <Toast level={notice.level} onClose={() => setNotice(null)}>
          {notice.text}
        </Toast>
      )}
    </>
  )
}

/**
 * Web Push, the one way that belongs to this browser and not to an account.
 *
 * It has no fields and nothing to set up elsewhere, so it stays a switch above
 * the services instead of pretending to be one of them.
 */
function ThisBrowser({ onNotice, onChanged }: { onNotice: (notice: Notice) => void; onChanged: () => void }) {
  const { t } = useTranslation()
  const [on, setOn] = useState(false)
  useEffect(() => {
    void currentSubscription().then((subscription) => setOn(Boolean(subscription)))
  }, [])
  const toggle = async (wanted: boolean) => {
    try {
      if (wanted) await subscribePush()
      else await unsubscribePush()
      setOn(wanted)
      onChanged()
      onNotice({ text: wanted ? t('channels.pushOn') : t('channels.pushOff'), level: 'ok' })
    } catch (failure) {
      const reason = failure instanceof Error ? failure.message : 'error'
      onNotice({
        text: reason === 'denied' ? t('channels.pushDenied') : reason === 'unsupported' ? t('channels.pushUnsupported') : t('errors.network'),
        level: 'error',
      })
    }
  }
  return (
    <SettingsCard title={t('channels.push')}>
      <Switch checked={on} onChange={(wanted) => void toggle(wanted)} label={t('channels.push')} description={pushSupported() ? t('channels.pushHelp') : t('channels.pushUnsupported')} disabled={!pushSupported()} />
    </SettingsCard>
  )
}

/** One set-up way: name, what it reports, and the three buttons. */
function ChannelTile({
  channel,
  events,
  active,
  onEdit,
  onToggle,
  onRemove,
}: {
  channel: Channel
  events: EventSpec[]
  active: boolean
  onEdit: () => void
  onToggle: () => void
  onRemove: () => void
}) {
  const { t } = useTranslation()
  const subscribed = channel.events.map((event) => tAdapter(events.find((spec) => spec.event === event)?.label ?? event))
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onEdit}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onEdit()
        }
      }}
      className={`relative flex min-h-24 cursor-pointer flex-col justify-between overflow-hidden rounded-2xl border p-3 transition-colors ${active ? 'border-accent/60 bg-accent-soft' : 'border-line hover:border-line-strong'} ${channel.enabled ? '' : 'opacity-50'}`}
    >
      <ServiceIcon icon={KIND_ICONS[channel.kind] ?? 'lucide:bell'} size={64} className="pointer-events-none absolute -right-3 -bottom-3 opacity-[0.08]" />
      <div className="relative min-w-0">
        <div className="flex items-center gap-2">
          <span className="dot" data-status={!channel.enabled ? 'unknown' : channel.last_error ? 'bad' : 'ok'} />
          <span className="font-semibold truncate">{channel.name}</span>
        </div>
        <p className="text-[11px] text-muted truncate mt-0.5">{subscribed.join(', ') || t('channels.noEvents')}</p>
        {channel.last_error && <p className="text-[11px] text-bad truncate">{channel.last_error}</p>}
      </div>
      <div className="relative mt-2 flex justify-end gap-1">
        <button
          className="btn btn-icon h-7 w-7"
          aria-pressed={channel.enabled}
          onClick={(event) => {
            event.stopPropagation()
            onToggle()
          }}
          aria-label={t(channel.enabled ? 'channels.disable' : 'channels.enable')}
          title={t(channel.enabled ? 'channels.disable' : 'channels.enable')}
        >
          <Power size={13} />
        </button>
        <button
          className="btn btn-icon h-7 w-7"
          onClick={(event) => {
            event.stopPropagation()
            onEdit()
          }}
          aria-label={t('common.edit')}
          title={t('common.edit')}
        >
          <Pencil size={13} />
        </button>
        <button
          className="btn btn-icon h-7 w-7 btn-danger"
          onClick={(event) => {
            event.stopPropagation()
            onRemove()
          }}
          aria-label={t('common.delete')}
          title={t('common.delete')}
        >
          <Trash2 size={13} />
        </button>
      </div>
    </div>
  )
}

/** The steps of a service, in the column next to its fields. */
function Guide({ kind }: { kind: string }) {
  const { t } = useTranslation()
  return (
    <ol className="flex flex-col gap-3">
      {(GUIDES[kind] ?? []).map((step, index) => (
        <li key={step.key} className="flex gap-3">
          <span className="num flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent-soft text-[11px] font-semibold text-accent">{index + 1}</span>
          <div className="min-w-0">
            <p className="text-sm leading-relaxed text-muted">{t(`channels.guide.${kind}.${step.key}`)}</p>
            {step.links?.map((link) => (
              <a key={link.href} href={link.href} target="_blank" rel="noreferrer" className="text-[13px] text-accent hover:underline">
                {link.label} ↗
              </a>
            ))}
          </div>
        </li>
      ))}
    </ol>
  )
}

/**
 * The panel of one way: fields on the left, the guide or the events on the right.
 *
 * The guide stands open as long as it is needed, which is until this way has
 * been saved once. After that the same place holds what it reports.
 */
function ChannelEditor({
  spec,
  channel,
  events,
  onSaved,
  onClose,
  onNotice,
}: {
  spec: ChannelKind
  channel: Channel | null
  events: EventSpec[]
  onSaved: (channel: Channel) => void
  onClose: () => void
  onNotice: (notice: Notice) => void
}) {
  const { t } = useTranslation()
  const [name, setName] = useState(channel?.name ?? spec.label)
  const [config, setConfig] = useState<Record<string, unknown>>(
    channel?.config ?? Object.fromEntries(spec.fields.filter((field) => field.default !== null && field.default !== undefined).map((field) => [field.name, field.default])),
  )
  const [selected, setSelected] = useState<string[]>(channel?.events ?? DEFAULT_EVENTS)
  const [enabled, setEnabled] = useState(channel?.enabled ?? true)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  /** ``null`` means nobody has decided; then the guide shows until this is saved. */
  const [guideByHand, setGuideByHand] = useState<boolean | null>(null)
  const guide = hasGuide(spec.kind) && (guideByHand ?? channel === null)

  const save = async (): Promise<Channel | null> => {
    setError('')
    setSaving(true)
    try {
      const body = { name, config, enabled, events: selected }
      const saved = channel ? await patch<Channel>(`/channels/${channel.id}`, body) : await post<Channel>('/channels', { kind: spec.kind, ...body })
      onSaved(saved)
      return saved
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : t('errors.network'))
      return null
    } finally {
      setSaving(false)
    }
  }

  /** Save first, then send: a test says nothing about fields nobody kept. */
  const sendTest = async () => {
    const saved = await save()
    if (!saved) return
    setTesting(true)
    try {
      const result = await post<{ ok: boolean; message: string }>(`/channels/${saved.id}/test`)
      onNotice({ text: result.message, level: result.ok ? 'ok' : 'error' })
    } catch (failure) {
      onNotice({ text: failure instanceof ApiError ? failure.message : t('errors.network'), level: 'error' })
    } finally {
      setTesting(false)
    }
  }

  return (
    <SettingsCard title={channel ? t('channels.edit', { name: channel.name }) : t('channels.new', { name: spec.label })}>
      <div className="grid gap-x-6 gap-y-4 lg:grid-cols-2 lg:items-start">
        <div className="flex flex-col gap-3">
          {spec.help && <p className="text-xs text-muted">{tAdapter(spec.help)}</p>}
          <Field label={t('channels.name')} htmlFor="c-name" help={t('channels.nameHelp')}>
            <input id="c-name" className="input" value={name} onChange={(event) => setName(event.target.value)} />
          </Field>
          {spec.fields.map((field) => (
            <FieldInput key={field.name} spec={field} value={config[field.name]} onChange={(value) => setConfig((current) => ({ ...current, [field.name]: value }))} />
          ))}
          <Switch checked={enabled} onChange={setEnabled} label={t('channels.enabled')} />
        </div>

        <div className="flex flex-col gap-3">
          <div className="flex items-start justify-between gap-2">
            <h3 className="font-medium text-[14px]">{guide ? t('channels.guideHeading') : t('channels.events')}</h3>
            {hasGuide(spec.kind) && (
              <button className="btn btn-icon h-7 w-7" onClick={() => setGuideByHand(!guide)} aria-pressed={guide} aria-label={t('channels.guideHeading')} title={t('channels.guideHeading')}>
                <HelpCircle size={14} />
              </button>
            )}
          </div>
          {guide ? (
            <Guide kind={spec.kind} />
          ) : (
            <>
              <p className="text-xs text-muted">{t('channels.eventsHelp')}</p>
              <div className="flex flex-wrap gap-1.5">
                {events
                  .filter((event) => event.event !== 'test')
                  .map((event) => {
                    const on = selected.includes(event.event)
                    return (
                      <button
                        key={event.event}
                        type="button"
                        className="btn h-8 text-xs"
                        aria-pressed={on}
                        onClick={() => setSelected((current) => (on ? current.filter((entry) => entry !== event.event) : [...current, event.event]))}
                      >
                        {tAdapter(event.label)}
                      </button>
                    )
                  })}
              </div>
            </>
          )}
        </div>
      </div>

      {error && (
        <p className="text-sm text-bad mt-3" role="alert">
          {error}
        </p>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-line pt-4">
        <button className="btn btn-accent" onClick={() => void save()} disabled={!name.trim() || saving}>
          {t('common.save')}
        </button>
        {/* Saving and sending in one: what arrives proves the way, not the form. */}
        <button className="btn" onClick={() => void sendTest()} disabled={!name.trim() || saving || testing}>
          <Send size={14} /> {t('channels.test')}
        </button>
        <button className="btn" onClick={onClose}>
          {t('common.cancel')}
        </button>
      </div>
    </SettingsCard>
  )
}
