import { Bell, Info, KeyRound, LayoutDashboard, Plug, User, Users } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { NavLink, Navigate, Route, Routes } from 'react-router-dom'

import { AppShell } from '../../components/AppShell'
import { useAuth } from '../../stores/auth'
import { BoardsSettings } from './BoardsSettings'
import { ChannelsSettings } from './ChannelsSettings'
import { IntegrationsSettings } from './IntegrationsSettings'
import { ProfileSettings } from './ProfileSettings'
import { SystemSettings } from './SystemSettings'
import { TokensSettings } from './TokensSettings'
import { UsersSettings } from './UsersSettings'

export function SettingsPage() {
  const { t } = useTranslation()
  const user = useAuth((s) => s.user)
  const admin = user?.role === 'admin'
  const member = user?.role !== 'guest'
  const entries = [
    { to: '', icon: User, label: t('settings.nav.profile') },
    { to: 'boards', icon: LayoutDashboard, label: t('settings.nav.boards'), show: member },
    { to: 'integrations', icon: Plug, label: t('settings.nav.integrations'), show: true },
    { to: 'channels', icon: Bell, label: t('settings.nav.channels'), show: member },
    { to: 'tokens', icon: KeyRound, label: t('settings.nav.tokens'), show: member },
    { to: 'users', icon: Users, label: t('settings.nav.users'), show: admin },
    { to: 'system', icon: Info, label: t('settings.nav.system'), show: true },
  ].filter((e) => e.show !== false)
  return (
    <AppShell title={t('settings.title')}>
      <div className="max-w-5xl mx-auto px-3 sm:px-4 py-5 grid md:grid-cols-[200px_1fr] gap-5">
        <nav className="flex md:flex-col gap-1 overflow-x-auto" aria-label={t('settings.title')}>
          {entries.map((entry) => (
            <NavLink
              key={entry.to}
              to={`/settings/${entry.to}`}
              end={entry.to === ''}
              className={({ isActive }) => `flex items-center gap-2 h-9 px-3 rounded-lg text-sm whitespace-nowrap ${isActive ? 'bg-accent-soft text-accent font-medium' : 'text-muted hover:text-ink hover:bg-surface-hover'}`}
            >
              <entry.icon size={15} />
              {entry.label}
            </NavLink>
          ))}
        </nav>
        <section className="min-w-0">
          <Routes>
            <Route index element={<ProfileSettings />} />
            <Route path="boards" element={<BoardsSettings />} />
            <Route path="integrations" element={<IntegrationsSettings />} />
            <Route path="channels" element={<ChannelsSettings />} />
            <Route path="tokens" element={<TokensSettings />} />
            <Route path="users" element={admin ? <UsersSettings /> : <Navigate to="/settings" replace />} />
            <Route path="system" element={<SystemSettings />} />
            <Route path="*" element={<Navigate to="/settings" replace />} />
          </Routes>
        </section>
      </div>
    </AppShell>
  )
}

export function SettingsCard({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <div className="glass rounded-2xl p-5 mb-4">
      <h2 className="font-semibold text-[15px]">{title}</h2>
      {description && <p className="text-sm text-muted mt-0.5 mb-3">{description}</p>}
      {!description && <div className="mb-3" />}
      {children}
    </div>
  )
}
