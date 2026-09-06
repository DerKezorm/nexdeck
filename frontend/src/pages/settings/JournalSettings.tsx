/**
 * nexdeck's own log, for an administrator who was asked what happened.
 *
 * The level can be raised here without a restart, because a restart usually
 * destroys the state somebody wanted to look at. A deep level carries an end
 * from the moment it is set: without one, somebody turns tracing on for a
 * single problem and it is still on months later, writing gigabytes.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, RefreshCw, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, del, get, put, serverUrl } from '../../api/client'
import { Confirm, Field, Select, Toast } from '../../components/ui'
import { SettingsCard } from './SettingsCard'

interface Line {
  time: string
  level: string
  logger: string
  message: string
  request_id: string | null
}

interface Mode {
  mode: string
  until: string | null
  fixed_by_env: boolean
  modes: string[]
  durations: number[]
}

const LEVEL_COLOURS: Record<string, string> = {
  DEBUG: 'text-faint',
  INFO: 'text-muted',
  WARNING: 'text-warn',
  ERROR: 'text-bad',
  CRITICAL: 'text-bad',
}

export function JournalSettings() {
  const { t } = useTranslation()
  const queries = useQueryClient()
  const [level, setLevel] = useState('')
  const [search, setSearch] = useState('')
  const [clearing, setClearing] = useState(false)
  const [toast, setToast] = useState<{ text: string; level: 'ok' | 'error' } | null>(null)

  const params = new URLSearchParams({ limit: '300' })
  if (level) params.set('level', level)
  if (search.trim()) params.set('search', search.trim())

  const lines = useQuery({
    queryKey: ['journal', level, search],
    queryFn: () => get<Line[]>(`/journal?${params.toString()}`),
    refetchInterval: 15_000,
  })
  const mode = useQuery({ queryKey: ['journal-level'], queryFn: () => get<Mode>('/journal/level') })

  async function changeLevel(next: string, minutes: number) {
    try {
      await put('/journal/level', { mode: next, minutes })
      await queries.invalidateQueries({ queryKey: ['journal-level'] })
      await queries.invalidateQueries({ queryKey: ['journal'] })
    } catch (failure) {
      setToast({ text: failure instanceof ApiError ? failure.message : t('errors.network'), level: 'error' })
    }
  }

  async function clear() {
    setClearing(false)
    try {
      await del('/journal')
      await queries.invalidateQueries({ queryKey: ['journal'] })
      setToast({ text: t('settings.journal.cleared'), level: 'ok' })
    } catch (failure) {
      setToast({ text: failure instanceof ApiError ? failure.message : t('errors.network'), level: 'error' })
    }
  }

  const state = mode.data
  const deep = state ? ['detailed', 'trace'].includes(state.mode) : false

  return (
    <>
      <SettingsCard title={t('settings.journal.title')} description={t('settings.journal.intro')}>
        <div className="flex flex-wrap items-end gap-3">
          <Field label={t('settings.journal.level')} help={state?.fixed_by_env ? t('settings.journal.fixedByEnv') : undefined}>
            <Select
              value={state?.mode ?? 'normal'}
              onChange={(next) => void changeLevel(next, 0)}
              disabled={state?.fixed_by_env}
              options={(state?.modes ?? []).map((one) => ({ value: one, label: t(`settings.journal.modes.${one}`) }))}
            />
          </Field>
          {deep && !state?.fixed_by_env && (
            <Field label={t('settings.journal.duration')} help={t('settings.journal.durationHelp')}>
              <Select
                value="0"
                onChange={(next) => void changeLevel(state!.mode, Number(next))}
                options={(state?.durations ?? []).map((minutes) => ({
                  value: String(minutes),
                  label: minutes === 0 ? t('settings.journal.untilRestart') : t('settings.journal.minutes', { count: minutes }),
                }))}
              />
            </Field>
          )}
          {state?.until && (
            <p className="text-xs text-muted pb-2">
              {t('settings.journal.endsAt', { time: new Date(state.until).toLocaleString() })}
            </p>
          )}
        </div>
      </SettingsCard>

      <SettingsCard title={t('settings.journal.lines')} description={t('settings.journal.linesIntro')}>
        {/* One row. The search field gives way; the buttons never drop to a
            line of their own, which reads as if one of them belonged
            somewhere else. */}
        <div className="flex items-end gap-3 mb-3">
          <Field label={t('settings.journal.from')}>
            <Select
              className="w-32"
              value={level}
              onChange={setLevel}
              options={[
                { value: '', label: t('settings.journal.allLevels') },
                { value: 'INFO', label: 'INFO' },
                { value: 'WARNING', label: 'WARNING' },
                { value: 'ERROR', label: 'ERROR' },
              ]}
            />
          </Field>
          <div className="flex-1 min-w-0">
            <Field label={t('settings.journal.search')} htmlFor="journal-search">
              <input
                id="journal-search"
                className="input w-full"
                value={search}
                placeholder={t('settings.journal.searchPlaceholder')}
                onChange={(event) => setSearch(event.target.value)}
              />
            </Field>
          </div>
          <div className="flex items-center gap-2 mb-3 flex-none">
            <button className="btn" onClick={() => void lines.refetch()} title={t('common.refresh')}>
              <RefreshCw size={15} /> {t('common.refresh')}
            </button>
            <a className="btn" href={serverUrl('/api/v1/journal/download')} download title={t('common.download')}>
              <Download size={15} /> {t('common.download')}
            </a>
            <button className="btn btn-danger" onClick={() => setClearing(true)}>
              <Trash2 size={15} /> {t('settings.journal.clear')}
            </button>
          </div>
        </div>

        {lines.isLoading && <p className="text-sm text-muted">{t('common.loading')}</p>}
        {!lines.isLoading && (lines.data ?? []).length === 0 && <p className="text-sm text-muted">{t('settings.journal.empty')}</p>}
        {(lines.data ?? []).length > 0 && (
          // Its own scroller in both directions: a trace-level log is thousands
          // of lines, and one entry has to stay on one row. A message that
          // wraps turns a list you scan into a wall you read.
          <div className="overflow-auto max-h-[60vh] rounded-lg border border-line">
            <table className="min-w-full text-xs num">
              <tbody>
                {(lines.data ?? []).map((line, index) => (
                  <tr key={`${line.time}-${index}`} className="border-b border-line last:border-0 align-top">
                    <td className="py-1 px-2 whitespace-nowrap text-faint">{line.time}</td>
                    <td className={`py-1 px-2 whitespace-nowrap font-semibold ${LEVEL_COLOURS[line.level] ?? 'text-muted'}`}>{line.level}</td>
                    <td className="py-1 px-2 whitespace-nowrap text-faint">{line.logger.replace(/^nexdeck\./, '')}</td>
                    <td className="py-1 px-2 whitespace-nowrap text-faint">{line.request_id === '-' ? '' : line.request_id}</td>
                    <td className="py-1 px-2 whitespace-pre">{line.message}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SettingsCard>

      {clearing && (
        <Confirm
          open
          title={t('settings.journal.clearTitle')}
          body={t('settings.journal.clearBody')}
          confirmLabel={t('settings.journal.clear')}
          danger
          onConfirm={() => void clear()}
          onCancel={() => setClearing(false)}
        />
      )}
      {toast && (
        <Toast level={toast.level} onClose={() => setToast(null)}>
          {toast.text}
        </Toast>
      )}
    </>
  )
}
