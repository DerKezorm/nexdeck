/**
 * Maintenance for a connection or an app tile (roadmap M1): for how long, or
 * until a time today or tomorrow; and the running one moved or ended.
 * Administrators only; the server says no to anybody else as well.
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { del, post } from '../api/client'
import { maintenanceTarget } from '../lib/maintenance'
import type { WidgetView } from '../lib/types'
import { Dialog } from './ui'

const HOURS = [1, 2, 4, 8] as const

/** The next time the clock shows ``hh:mm``: today if that is still ahead, else tomorrow. */
export function nextTime(value: string, now = new Date()): Date | null {
  const match = /^(\d{1,2}):(\d{2})$/.exec(value)
  if (!match) return null
  const at = new Date(now)
  at.setHours(Number(match[1]), Number(match[2]), 0, 0)
  if (at.getTime() <= now.getTime() + 60_000) at.setDate(at.getDate() + 1)
  return at
}

export function MaintenanceDialog({ widget, open, onClose, onChanged }: { widget: WidgetView; open: boolean; onClose: () => void; onChanged?: () => void }) {
  const { t, i18n } = useTranslation()
  const [choice, setChoice] = useState<string>('2')
  const [until, setUntil] = useState('22:00')
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState('')
  const target = maintenanceTarget(widget)
  const running = widget.maintenance ?? null
  const name = (target && 'integration_id' in target ? widget.integration_name : '') || widget.title
  const time = (iso: string) => new Date(iso).toLocaleTimeString(i18n.language, { hour: '2-digit', minute: '2-digit' })

  const act = async (job: () => Promise<unknown>) => {
    setBusy(true)
    setFailure('')
    try {
      await job()
      onChanged?.()
      onClose()
    } catch (error) {
      setFailure(t('maintenance.failed', { reason: error instanceof Error ? error.message : String(error) }))
    } finally {
      setBusy(false)
    }
  }
  const start = () => {
    if (!target) return
    if (choice === 'until') {
      const at = nextTime(until)
      if (!at) return
      void act(() => post('/maintenance', { ...target, ends_at: at.toISOString() }))
    } else {
      void act(() => post('/maintenance', { ...target, minutes: Number(choice) * 60 }))
    }
  }
  const end = () => {
    if (running) void act(() => del(`/maintenance/${running.id}`))
  }

  return (
    <Dialog
      open={open && target != null}
      onClose={onClose}
      size="sm"
      title={t('maintenance.title', { name })}
      footer={
        <>
          {running ? (
            <button type="button" className="btn btn-flat mr-auto" onClick={end} disabled={busy}>{t('maintenance.end')}</button>
          ) : null}
          <button type="button" className="btn btn-accent" onClick={start} disabled={busy || (choice === 'until' && !nextTime(until))}>
            {running ? t('maintenance.move') : t('maintenance.start')}
          </button>
        </>
      }
    >
      <div className="flex flex-col gap-3 text-[13px]" data-testid="maintenance-dialog">
        {running ? <p className="font-medium">{t('maintenance.running', { time: time(running.until) })}</p> : null}
        <p className="text-muted">{t('maintenance.explain', { name })}</p>
        {target && 'integration_id' in target ? <p className="text-muted">{t('maintenance.whole')}</p> : null}
        <fieldset className="flex flex-col gap-1.5">
          <legend className="text-[12px] font-semibold mb-1">{t('maintenance.length')}</legend>
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex flex-wrap rounded-lg bg-surface p-0.5 gap-0.5 text-xs">
              {[...HOURS.map(String), 'until'].map((one) => (
                <button key={one} type="button" className={`px-2.5 py-1 rounded-md ${choice === one ? 'bg-accent-soft text-ink' : 'text-muted'}`} aria-pressed={choice === one} onClick={() => setChoice(one)}>
                  {one === 'until' ? t('maintenance.until') : t('maintenance.hours', { count: Number(one) })}
                </button>
              ))}
            </span>
            {choice === 'until' ? (
              <input type="time" className="input h-8 w-28" value={until} onChange={(event) => setUntil(event.target.value)} aria-label={t('maintenance.until')} />
            ) : null}
          </div>
        </fieldset>
        {failure ? <p className="text-bad" role="alert">{failure}</p> : null}
      </div>
    </Dialog>
  )
}
