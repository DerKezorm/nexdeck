import { useTranslation } from 'react-i18next'

import { SettingsCard } from './SettingsCard'

/**
 * How to reach nexdeck from the browser's address bar: short names of app
 * tiles (``/go/<name>``) and nexdeck as a search engine (OpenSearch).
 *
 * ⚠️ Safari reads no OpenSearch description, so there is no engine to add.
 * That is said here as what it is, a limit of Safari, not as an error.
 */
export function AddressBarHelp() {
  const { t } = useTranslation()
  const example = `${window.location.origin}/go/plex`
  return (
    <SettingsCard title={t('settings.addressBar.title')} description={t('settings.addressBar.tiles', { example })}>
      <p className="text-sm text-muted mb-2">{t('settings.addressBar.engines')}</p>
      <p className="text-sm text-muted">{t('settings.addressBar.safari')}</p>
    </SettingsCard>
  )
}
