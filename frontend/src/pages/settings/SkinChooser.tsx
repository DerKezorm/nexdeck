import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Download, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, del, get, post } from '../../api/client'
import { Confirm, Field, Select, Switch } from '../../components/ui'
import { NATIVE_1984, type SkinChoice } from '../../lib/skin/wear'

export interface SkinEntry {
  key: string
  name: string
  description: string
  author: string
  origin: 'builtin' | 'own' | 'shop'
  native: string | null
  wearable: boolean
  options: { key: string; label: string; default: string; choices: { key: string; label: string }[] }[]
  swatches: (string | null)[]
}

export function useSkins() {
  return useQuery({ queryKey: ['skins'], queryFn: () => get<{ skins: SkinEntry[] }>('/skins') })
}

/**
 * Which skin is worn, with its options. For the installation (administrators,
 * on the look's page) without 1984, which is a card style there, and with a
 * way to bring a skin in and to delete one; for an account with every skin,
 * "the installation's" and the switch for sounds.
 */
export function SkinChooser({ value, onChange, forAccount = false }: { value: SkinChoice; onChange: (next: SkinChoice) => void; forAccount?: boolean }) {
  const { t } = useTranslation()
  const skins = useSkins()
  const shown = (skins.data?.skins ?? []).filter((skin) => forAccount || skin.key !== NATIVE_1984)
  const chosen = shown.find((skin) => skin.key === value.key)
  const words = useWords()
  const pick = (skin: SkinEntry | null) =>
    onChange(skin ? { ...value, key: skin.key, options: Object.fromEntries(skin.options.map((option) => [option.key, option.default])) } : { sounds: value.sounds })
  return (
    <div className="flex flex-col gap-3">
      <ul className="grid gap-2 sm:grid-cols-3" aria-label={t('settings.skins.title')}>
        <SkinButton label={forAccount ? t('settings.skins.installation') : t('settings.skins.none')} chosen={!value.key} onClick={() => pick(null)} />
        {shown.map((skin) => (
          <SkinButton key={skin.key} label={skin.name} chosen={value.key === skin.key} swatches={skin.swatches} note={skin.wearable ? skin.author : t('settings.skins.off')} onClick={() => pick(skin)} />
        ))}
      </ul>
      {chosen && chosen.options.length > 0 && (
        <div className="grid sm:grid-cols-2 gap-x-6">
          {chosen.options.map((option) => (
            <Field key={option.key} label={words(chosen, option.key, 'title', option.label)} htmlFor={`skin-${option.key}`}>
              <Select
                id={`skin-${option.key}`}
                value={value.options?.[option.key] ?? option.default}
                onChange={(choice) => onChange({ ...value, options: { ...value.options, [option.key]: choice } })}
                options={option.choices.map((choice) => ({ value: choice.key, label: words(chosen, option.key, choice.key, choice.label) }))}
              />
            </Field>
          ))}
        </div>
      )}
      {forAccount && <Switch checked={value.sounds === true} onChange={(sounds) => onChange({ ...value, sounds })} label={t('settings.skins.sounds')} description={t('settings.skins.soundsHelp')} />}
    </div>
  )
}

/**
 * The words of an option: a skin's own as its author wrote them, 1984's in the language of the page, from the
 * same texts its choices had as a card style.
 */
function useWords() {
  const { t } = useTranslation()
  return (skin: SkinEntry, option: string, choice: string, own: string) => (skin.key === NATIVE_1984 ? t(`settings.appearance.retro.${option}.${choice}`) : own)
}

function SkinButton({ label, chosen, swatches, note, onClick }: { label: string; chosen: boolean; swatches?: (string | null)[]; note?: string; onClick: () => void }) {
  return (
    <li>
      <button type="button" aria-pressed={chosen} onClick={onClick} className={`w-full text-left rounded-xl border p-2 ${chosen ? 'border-accent bg-accent-soft' : 'border-line hover:bg-surface-hover'}`}>
        <span className="flex gap-1 h-3" aria-hidden="true">
          {(swatches ?? []).filter(Boolean).map((colour, index) => (
            <span key={index} className="w-3 h-3 rounded-full border border-line" style={{ background: colour ?? undefined }} />
          ))}
        </span>
        <span className="mt-1 flex items-center gap-1 text-xs font-medium">
          {chosen && <Check size={12} className="text-accent" />}
          {label}
        </span>
        {note && <span className="block text-[11px] text-faint truncate">{note}</span>}
      </button>
    </li>
  )
}

/** Bringing a skin in, taking it out as a file, deleting it: the installation's skins (administrators). */
export function SkinShelf({ onMessage }: { onMessage: (text: string, level: 'ok' | 'error') => void }) {
  const { t } = useTranslation()
  const client = useQueryClient()
  const skins = useSkins()
  const [text, setText] = useState('')
  const [going, setGoing] = useState<SkinEntry | null>(null)
  const own = (skins.data?.skins ?? []).filter((skin) => skin.origin !== 'builtin')
  const bringIn = async () => {
    try {
      await post('/skins/import', { text })
      setText('')
      await client.invalidateQueries({ queryKey: ['skins'] })
      onMessage(t('settings.skins.imported'), 'ok')
    } catch (failure) {
      onMessage(failure instanceof ApiError ? failure.message : t('errors.network'), 'error')
    }
  }
  const remove = async (skin: SkinEntry) => {
    setGoing(null)
    try {
      await del(`/skins/${encodeURIComponent(skin.key)}`)
      await client.invalidateQueries({ queryKey: ['skins'] })
    } catch (failure) {
      onMessage(failure instanceof ApiError ? failure.message : t('errors.network'), 'error')
    }
  }
  return (
    <div className="flex flex-col gap-3">
      {own.length > 0 && (
        <ul className="divide-y divide-line text-sm">
          {own.map((skin) => (
            <li key={skin.key} className="flex items-center gap-2 py-1.5">
              <span className="flex-1 truncate">{skin.name}</span>
              <a className="btn btn-flat btn-icon" href={`/api/v1/skins/${encodeURIComponent(skin.key)}/file`} download aria-label={t('settings.skins.download', { name: skin.name })}>
                <Download size={14} />
              </a>
              <button type="button" className="btn btn-flat btn-icon" onClick={() => setGoing(skin)} aria-label={t('settings.skins.delete', { name: skin.name })}>
                <Trash2 size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}
      <Field label={t('settings.skins.import')} help={t('settings.skins.importHelp')} htmlFor="skin-import">
        <textarea id="skin-import" className="input font-mono text-xs h-24" value={text} onChange={(event) => setText(event.target.value)} placeholder='{ "nexdeck_skin": 1, … }' spellCheck={false} />
      </Field>
      <div>
        <button type="button" className="btn" disabled={!text.trim()} onClick={() => void bringIn()}>
          {t('settings.skins.importButton')}
        </button>
      </div>
      <Confirm
        open={going !== null}
        danger
        title={t('settings.skins.deleteTitle', { name: going?.name ?? '' })}
        body={t('settings.skins.deleteBody')}
        confirmLabel={t('common.delete')}
        onCancel={() => setGoing(null)}
        onConfirm={() => going && void remove(going)}
      />
    </div>
  )
}
