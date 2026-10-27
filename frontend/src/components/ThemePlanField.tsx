/**
 * Light or dark, and when: the same four answers for an account and for a
 * wall display, and with "by the clock" the two times it turns at.
 */
import { useTranslation } from 'react-i18next'

import { DARK_FROM, LIGHT_FROM, type ThemeChoice, type ThemePlan } from '../lib/themeMode'
import { Field, Select } from './ui'

const CHOICES: ThemeChoice[] = ['dark', 'light', 'system', 'schedule']
const CLOCK = /^([01]\d|2[0-3]):[0-5]\d$/

export function ThemePlanField({ id, value, onChange }: { id: string; value: ThemePlan; onChange: (plan: ThemePlan) => void }) {
  const { t } = useTranslation()
  const light = value.light_from || LIGHT_FROM
  const dark = value.dark_from || DARK_FROM
  // A half-typed time is not handed on, and neither is one equal to the other: both would be refused.
  const time = (which: 'light_from' | 'dark_from', clock: string) => {
    const other = which === 'light_from' ? dark : light
    if (CLOCK.test(clock) && clock !== other) onChange({ theme: 'schedule', light_from: light, dark_from: dark, [which]: clock })
  }
  return (
    <>
      <Field label={t('settings.profile.theme')} htmlFor={id}>
        <Select
          id={id}
          value={value.theme}
          onChange={(theme) => onChange({ theme: theme as ThemeChoice, light_from: light, dark_from: dark })}
          options={CHOICES.map((choice) => ({ value: choice, label: t(`settings.profile.theme_${choice}`) }))}
        />
      </Field>
      {value.theme === 'schedule' && (
        <div className="grid grid-cols-2 gap-2 sm:col-span-2 sm:col-start-2">
          <Field label={t('settings.profile.lightFrom')} htmlFor={`${id}-light`} help={t('settings.profile.scheduleHelp')}>
            <input id={`${id}-light`} className="input" type="time" required defaultValue={light} onChange={(event) => time('light_from', event.target.value)} />
          </Field>
          <Field label={t('settings.profile.darkFrom')} htmlFor={`${id}-dark`}>
            <input id={`${id}-dark`} className="input" type="time" required defaultValue={dark} onChange={(event) => time('dark_from', event.target.value)} />
          </Field>
        </div>
      )}
    </>
  )
}
