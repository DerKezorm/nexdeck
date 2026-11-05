/**
 * Maintenance for a connection or an app tile (roadmap M1): for how long, or
 * until a time today or tomorrow; and the running one moved or ended. Below,
 * the maintenance that comes back every week (issue #62).
 * Administrators only; the server says no to anybody else as well.
 */
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { del, get, post } from '../api/client'
import { browserZone, endOnTheClock, maintenanceTarget, plansPath, weekdayNames, type MaintenancePlan } from '../lib/maintenance'
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
        {target ? <WeeklyPlans target={target} open={open} /> : null}
      </div>
    </Dialog>
  )
}

const PLAN_HOURS = [1, 2, 3, 4, 6, 8, 12, 24] as const

/** Maintenance that comes back every week (issue #62): the plans of this connection or tile, and a new one. */
export function WeeklyPlans({ target, open }: { target: { integration_id: number } | { widget_id: number }; open: boolean }) {
  const { t, i18n } = useTranslation()
  const [plans, setPlans] = useState<MaintenancePlan[] | null>(null)
  const [adding, setAdding] = useState(false)
  const [days, setDays] = useState<number[]>([6])
  const [starts, setStarts] = useState('03:00')
  const [hours, setHours] = useState(2)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState('')
  const path = plansPath(target)
  const names = weekdayNames(i18n.language)

  useEffect(() => {
    if (!open) return
    let gone = false
    get<MaintenancePlan[]>(path).then((found) => { if (!gone) setPlans(found) }, () => { if (!gone) setPlans([]) })
    return () => { gone = true }
  }, [open, path])

  const clock = (value: string) => {
    const [hour, minute] = value.split(':').map(Number)
    return new Date(2026, 0, 1, hour, minute).toLocaleTimeString(i18n.language, { hour: '2-digit', minute: '2-digit' })
  }
  const line = (plan: MaintenancePlan) => {
    const said = t('maintenance.weeklyLine', {
      days: plan.days.length === 7 ? t('maintenance.everyDay') : plan.days.map((day) => names[day]).join(', '),
      from: clock(plan.starts),
      to: clock(endOnTheClock(plan.starts, plan.minutes)),
    })
    // Set in another time zone, the times are that zone's: say which.
    return plan.zone && plan.zone !== browserZone() ? `${said} (${plan.zone})` : said
  }
  const when = (iso: string) => new Date(iso).toLocaleString(i18n.language, { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
  const act = async (job: () => Promise<void>) => {
    setBusy(true)
    setFailure('')
    try {
      await job()
    } catch (error) {
      setFailure(t('maintenance.failed', { reason: error instanceof Error ? error.message : String(error) }))
    } finally {
      setBusy(false)
    }
  }
  const save = () => void act(async () => {
    const made = await post<MaintenancePlan>('/maintenance/plans', { ...target, days, starts, minutes: hours * 60, zone: browserZone() })
    setPlans((before) => [...(before ?? []), made])
    setAdding(false)
  })
  const remove = (plan: MaintenancePlan) => void act(async () => {
    await del(`/maintenance/plans/${plan.id}`)
    setPlans((before) => (before ?? []).filter((one) => one.id !== plan.id))
  })
  const toggle = (day: number) => setDays((before) => (before.includes(day) ? before.filter((one) => one !== day) : [...before, day].sort()))

  return (
    <section className="flex flex-col gap-1.5 border-t border-line pt-3" data-testid="maintenance-weekly">
      <h3 className="text-[12px] font-semibold">{t('maintenance.weekly')}</h3>
      <p className="text-muted">{t('maintenance.weeklyExplain')}</p>
      {plans && plans.length === 0 && !adding ? <p className="text-muted">{t('maintenance.weeklyNone')}</p> : null}
      {plans && plans.length > 0 ? (
        <ul className="flex flex-col gap-1">
          {plans.map((plan) => (
            <li key={plan.id} className="flex items-center gap-2 rounded-lg bg-surface px-2.5 py-1.5">
              <span className="flex-1 min-w-0">
                <span className="block font-medium">{line(plan)}</span>
                {plan.next_starts_at ? <span className="block text-[12px] text-muted">{t('maintenance.weeklyNext', { when: when(plan.next_starts_at) })}</span> : null}
              </span>
              <button type="button" className="btn btn-flat h-7 px-2 text-xs" onClick={() => remove(plan)} disabled={busy} aria-label={t('maintenance.weeklyRemove', { line: line(plan) })}>
                {t('maintenance.weeklyDrop')}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {adding ? (
        <div className="flex flex-col gap-2 rounded-lg bg-surface p-2.5" data-testid="maintenance-weekly-new">
          <fieldset>
            <legend className="text-[12px] font-semibold mb-1">{t('maintenance.weeklyDays')}</legend>
            <span className="inline-flex flex-wrap gap-0.5 text-xs">
              {names.map((label, day) => (
                <button key={day} type="button" className={`px-2 py-1 rounded-md ${days.includes(day) ? 'bg-accent-soft text-ink' : 'text-muted'}`} aria-pressed={days.includes(day)} onClick={() => toggle(day)}>
                  {label}
                </button>
              ))}
            </span>
          </fieldset>
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-[12px] font-semibold">
              {t('maintenance.weeklyFrom')}
              <input type="time" className="input h-8 w-28 font-normal" value={starts} onChange={(event) => setStarts(event.target.value)} />
            </label>
            <label className="flex flex-col gap-1 text-[12px] font-semibold">
              {t('maintenance.weeklyLength')}
              <select className="input h-8 w-32 font-normal" value={hours} onChange={(event) => setHours(Number(event.target.value))}>
                {PLAN_HOURS.map((one) => <option key={one} value={one}>{t('maintenance.hours', { count: one })}</option>)}
              </select>
            </label>
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" className="btn btn-flat" onClick={() => setAdding(false)} disabled={busy}>{t('common.cancel')}</button>
            <button type="button" className="btn btn-accent" onClick={save} disabled={busy || days.length === 0 || !/^\d{2}:\d{2}$/.test(starts)}>{t('maintenance.weeklySave')}</button>
          </div>
        </div>
      ) : (
        <button type="button" className="btn btn-flat self-start" onClick={() => setAdding(true)} disabled={plans === null}>{t('maintenance.weeklyAdd')}</button>
      )}
      {failure ? <p className="text-bad" role="alert">{failure}</p> : null}
    </section>
  )
}
