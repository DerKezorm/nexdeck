/**
 * The forecast at the foot of a card (roadmap M4): a quiet line, red once it
 * is under the two weeks after which it is told.
 */
import { Clock, TrendingUp } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { forecastTone, forecastWords, type Forecast } from '../lib/forecast'

const TONE = { bad: 'text-bad', warn: 'text-warn', quiet: 'text-muted' } as const

export function ForecastLine({ forecast }: { forecast: Forecast }) {
  const { t, i18n } = useTranslation()
  const { text, when } = forecastWords(forecast, t, i18n.language)
  const Icon = forecast.kind === 'full' ? Clock : TrendingUp
  return (
    <p className={`flex items-center gap-1.5 px-3 pb-2 pt-1 text-[11.5px] leading-tight ${TONE[forecastTone(forecast)]}`} title={t('forecast.basis')} data-testid="forecast">
      <Icon size={12} className="flex-none" aria-hidden="true" />
      <span className="truncate">
        {text}
        {when && <span className="text-faint"> · {when}</span>}
        {forecast.told && <span className="text-faint"> · {t('forecast.told')}</span>}
      </span>
    </p>
  )
}
