/**
 * Two cards out of the chronicle (roadmap M2): "What happened", its latest
 * lines, and "Daily report", the last 24 hours and what is still red.
 */
import { useTranslation } from 'react-i18next'

import type { ChronicleLine } from '../lib/chronicle'
import { useDisguise } from '../lib/showcase'
import { ChronicleRow } from './ChronicleLines'
import type { RenderProps } from './renderers'

export function ChronicleCard({ data }: RenderProps) {
  const { t } = useTranslation()
  const lines = (data?.items ?? []) as unknown as ChronicleLine[]
  if (!lines.length) {
    return <div className="flex-1 flex items-center justify-center text-xs text-faint px-3 pb-3">{t('chronicle.cardEmpty')}</div>
  }
  return (
    <div className="flex-1 min-h-0 overflow-y-auto px-1.5 pb-2 flex flex-col gap-0.5" data-testid="chronicle-card">
      {lines.map((line, index) => <ChronicleRow key={line.id ?? index} line={line} compact={false} />)}
    </div>
  )
}

interface Report {
  outages: string[]
  red: string[]
  now_red: string[]
  versions: { name: string; before: string; after: string }[]
  containers: string[]
  restarted: string[]
  backups: string[]
}

export function ReportCard({ data }: RenderProps) {
  const { t } = useTranslation()
  const disguise = useDisguise()
  const report = (data?.meta?.report ?? null) as Report | null
  if (!report) return <div className="flex-1" />
  const updates = report.versions.length + report.containers.length
  const facts: { key: string; status: string; label: string; list: string }[] = [
    { key: 'now_red', status: 'bad', label: t('report.nowRed'), list: report.now_red.join(', ') },
    { key: 'outages', status: 'bad', label: t('report.outages'), list: report.outages.join(', ') },
    { key: 'red', status: 'warn', label: t('report.turnedRed'), list: report.red.join(', ') },
    { key: 'backups', status: 'warn', label: t('report.backups'), list: report.backups.join('; ') },
    { key: 'versions', status: 'accent', label: t('report.versions'), list: report.versions.map((one) => `${one.name} ${one.before} → ${one.after}`).join(', ') },
    { key: 'containers', status: 'accent', label: t('report.containers'), list: report.containers.join(', ') },
    { key: 'restarted', status: 'accent', label: t('report.restarted'), list: report.restarted.join(', ') },
  ].filter((fact) => fact.list)
  return (
    <div className="flex-1 min-h-0 flex flex-col px-3 pb-3" data-testid="report-card">
      <div className="flex flex-wrap gap-x-4 gap-y-1 mb-2 flex-none">
        <span className="text-[12px]"><b className="num text-[20px] font-semibold mr-1">{report.outages.length}</b>{t('report.outagesCount', { count: report.outages.length })}</span>
        <span className="text-[12px]"><b className="num text-[20px] font-semibold mr-1">{report.now_red.length}</b>{t('report.redCount', { count: report.now_red.length })}</span>
        <span className="text-[12px]"><b className="num text-[20px] font-semibold mr-1">{updates}</b>{t('report.updatesCount', { count: updates })}</span>
      </div>
      {facts.length ? (
        <div className="flex-1 min-h-0 overflow-y-auto flex flex-col gap-1.5">
          {facts.map((fact) => (
            <p key={fact.key} className="text-[12.5px] leading-snug flex gap-2">
              <span className="dot flex-none mt-[5px]" data-status={fact.status} aria-hidden="true" />
              <span className="min-w-0"><b className="font-semibold">{fact.label}:</b> {disguise.free(fact.list)}</span>
            </p>
          ))}
        </div>
      ) : (
        <p className="text-[13px] text-muted">{t('report.quiet')}</p>
      )}
    </div>
  )
}
