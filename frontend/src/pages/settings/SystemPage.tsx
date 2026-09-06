import { Archive, Globe, Info, KeyRound, Mail, Palette, Plug, ScrollText, Search, Users } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Navigate, Route, Routes } from 'react-router-dom'

import { AppShell } from '../../components/AppShell'
import { useAuth } from '../../stores/auth'
import { AboutSettings } from './AboutSettings'
import { AppearanceSettings } from './AppearanceSettings'
import { BackupsSettings } from './BackupsSettings'
import { AddressSettings } from './AddressSettings'
import { IntegrationsSettings } from './IntegrationsSettings'
import { MailSettings } from './MailSettings'
import { OidcSettings } from './OidcSettings'
import { SearchSettings } from './SearchSettings'
import { JournalSettings } from './JournalSettings'
import { SettingsNav, type NavEntry } from './SettingsNav'
import { UsersSettings } from './UsersSettings'

/**
 * Everything that belongs to the instance, not to a person.
 *
 * Open to every signed-in account on purpose, unlike most of the pages inside
 * it: the connections say which service is answering and which one is not, and
 * that is the first thing anyone asks when a card turns red. Changing anything
 * here stays with the administrator, as it was before the split.
 */
export function SystemPage() {
  const { t } = useTranslation()
  const user = useAuth((state) => state.user)
  const admin = user?.role === 'admin'
  const entries: NavEntry[] = [
    { to: 'integrations', icon: Plug, label: t('settings.nav.integrations') },
    { to: 'users', icon: Users, label: t('settings.nav.users'), show: admin },
    { to: 'address', icon: Globe, label: t('settings.nav.address'), show: admin },
    { to: 'mail', icon: Mail, label: t('settings.nav.mail'), show: admin },
    { to: 'search', icon: Search, label: t('settings.nav.search'), show: admin },
    { to: 'appearance', icon: Palette, label: t('settings.nav.appearance'), show: admin },
    { to: 'oidc', icon: KeyRound, label: t('settings.nav.oidc'), show: admin },
    { to: 'journal', icon: ScrollText, label: t('settings.nav.journal'), show: admin },
    { to: 'backups', icon: Archive, label: t('settings.nav.backups'), show: admin },
    { to: 'about', icon: Info, label: t('settings.nav.about') },
  ]
  /** Pages only an administrator may see; anyone else lands on the connections. */
  const forAdmin = (page: React.ReactElement) => (admin ? page : <Navigate to="/system" replace />)
  return (
    <AppShell title={t('settings.systemTitle')}>
      <div className="max-w-5xl mx-auto px-3 sm:px-4 py-5 grid md:grid-cols-[200px_1fr] gap-5">
        <SettingsNav base="/system" entries={entries} label={t('settings.systemTitle')} />
        <section className="min-w-0">
          <Routes>
            {/* The connections are the first page; they carry ``?add=<kind>``
                from the widget library, so they need an address of their own. */}
            <Route index element={<Navigate to="/system/integrations" replace />} />
            <Route path="integrations" element={<IntegrationsSettings />} />
            <Route path="users" element={forAdmin(<UsersSettings />)} />
            <Route path="address" element={forAdmin(<AddressSettings />)} />
            <Route path="mail" element={forAdmin(<MailSettings />)} />
            <Route path="search" element={forAdmin(<SearchSettings />)} />
            <Route path="appearance" element={forAdmin(<AppearanceSettings />)} />
            <Route path="oidc" element={forAdmin(<OidcSettings />)} />
            <Route path="journal" element={forAdmin(<JournalSettings />)} />
            <Route path="backups" element={forAdmin(<BackupsSettings />)} />
            <Route path="about" element={<AboutSettings />} />
            <Route path="*" element={<Navigate to="/system" replace />} />
          </Routes>
        </section>
      </div>
    </AppShell>
  )
}
