import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { get } from '../../api/client'
import { duration, temperature, type ClimateHistory as History } from '../../lib/home'
import { HEATING } from './ClimateControl'
import { StatChart, timeLabels, useWidth } from './StatChart'

const TARGET = 'color-mix(in srgb, var(--nd-text) 70%, transparent)'

/**
 * What a thermostat did over the last 24 hours or week, in its details: the
 * room as a line, the target dashed, the times it heated as bars along the
 * bottom, and the day in numbers. A thermostat that never says when it heats
 * is said to, rather than drawn as one that never did.
 */
export function ClimateHistory({ pageId, elementId }: { pageId: number; elementId: string }) {
  const { t, i18n } = useTranslation()
  const [period, setPeriod] = useState<'24h' | '7d'>('24h')
  const history = useQuery({
    queryKey: ['home-climate-history', pageId, elementId, period],
    queryFn: () => get<History>(`/pages/${pageId}/home/climates/${elementId}/history?period=${period}`),
    refetchInterval: 60_000,
    staleTime: 50_000,
  })
  const data = history.data
  const [box, width] = useWidth(440)
  const room = (data?.room ?? []).map((point) => [point[0], point[1]] as [number, number])

  return (
    <div ref={box} className="grid gap-2" data-climate-history>
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium">{t('homePage.history.title')}</span>
        <span className="ml-auto inline-flex gap-1 p-[3px] rounded-full border border-[var(--nd-border)]" role="radiogroup" aria-label={t('homePage.stats.period')}>
          {(['24h', '7d'] as const).map((one) => (
            <button key={one} type="button" role="radio" aria-checked={one === period} onClick={() => setPeriod(one)}
              className={`text-[11px] px-2.5 py-0.5 rounded-full ${one === period ? 'bg-[var(--nd-accent)] text-[var(--nd-on-accent)] font-semibold' : 'text-muted'}`}>
              {t(`homePage.stats.periods.${one}`)}
            </button>
          ))}
        </span>
      </div>
      {history.isLoading ? (
        <div className="h-[150px] grid place-items-center text-xs text-muted">…</div>
      ) : !data || history.isError || data.problem ? (
        <p className="text-xs text-muted">{data?.problem ? t(`homePage.problems.${data.problem.code}`, { defaultValue: data.problem.message }) : t('homePage.stats.failed')}</p>
      ) : room.length === 0 && data.target.length === 0 ? (
        <p className="text-xs text-muted">{t('homePage.history.empty')}</p>
      ) : (
        <>
          <div>
            <StatChart width={width} height={150} from={data.start} to={data.end} labels={timeLabels(period, data.start, data.end, data.zone, i18n.language, width, t('homePage.stats.now'))}
              tick={(value) => `${Math.round(value)}°`}
              lines={[{ points: room, colour: HEATING, fill: true, dot: true, label: t('homePage.history.room') }]}
              steps={{ points: data.target, colour: TARGET }}
              spans={data.heating ? { spans: data.heating, colour: HEATING } : undefined} />
          </div>
          <div className="flex flex-wrap gap-3 text-[11.5px] text-muted">
            <span><i className="inline-block w-2.5 h-[3px] rounded align-middle mr-1.5" style={{ background: HEATING }} />{t('homePage.history.room')}</span>
            <span><i className="inline-block w-2.5 h-[3px] rounded align-middle mr-1.5" style={{ background: TARGET }} />{t('homePage.history.target')}</span>
            {data.heating && <span><i className="inline-block w-2.5 h-1.5 rounded align-middle mr-1.5" style={{ background: HEATING }} />{t('homePage.history.heats')}</span>}
          </div>
          <div className="num flex flex-wrap gap-x-5 gap-y-1 text-[12px] text-muted" data-history-stats>
            <span>{t('homePage.history.todayLow')} <b className="text-[var(--nd-text)]">{temperature(data.today.low)}</b></span>
            <span>{t('homePage.history.todayHigh')} <b className="text-[var(--nd-text)]">{temperature(data.today.high)}</b></span>
            {data.heating && (
              <>
                <span>{t('homePage.history.heated')} <b className="text-[var(--nd-text)]" data-heated>{duration(data.today.heated)}</b></span>
                <span>{t('homePage.history.yesterdayHeated')} <b className="text-[var(--nd-text)]">{duration(data.yesterday.heated)}</b></span>
              </>
            )}
          </div>
          {!data.heating && (
            <p className="text-[11.5px] text-faint" data-no-heating>
              <b className="text-muted">{t('homePage.history.noHeating')}</b> {t('homePage.history.noHeatingText')}
            </p>
          )}
        </>
      )}
    </div>
  )
}
