import { Bell, Images, KeyRound, LayoutDashboard, User } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'

import { AppShell } from '../../components/AppShell'
import { useAuth } from '../../stores/auth'
import { BoardsSettings } from './BoardsSettings'
import { MediaSettings } from './MediaSettings'
import { ChannelsSettings } from './ChannelsSettings'
import { ProfileSettings } from './ProfileSettings'
import { SettingsNav, type NavEntry } from './SettingsNav'
import { TokensSettings } from './TokensSettings'

/**
 * The old address of a page that now lives under ``/system``.
 *
 * The query string rides along: the widget library links straight to
 * ``?add=<kind>`` to open the sheet for a new connection.
 */
function Moved({ to }: { to: string }) {
  const { search } = useLocation()
  return <Navigate to={to + search} replace />
}

/**
 * Everything that belongs to the person signed in.
 *
 * Split from the system settings on purpose: one list held the own password
 * next to the instance's identity provider, and nothing said which of the two
 * a change would reach. What is here changes nobody else's dashboard.
 */
export function SettingsPage() {
  const { t } = useTranslation()
  const user = useAuth((state) => state.user)
  const member = user?.role !== 'guest'
  const entries: NavEntry[] = [
    { to: '', icon: User, label: t('settings.nav.profile') },
    { to: 'boards', icon: LayoutDashboard, label: t('settings.nav.boards'), show: member },
    { to: 'media', icon: Images, label: t('settings.nav.media'), show: member },
    { to: 'channels', icon: Bell, label: t('settings.nav.channels'), show: member },
    { to: 'tokens', icon: KeyRound, label: t('settings.nav.tokens'), show: member },
  ]
  return (
    <AppShell title={t('settings.title')}>
      <div className="max-w-5xl mx-auto px-3 sm:px-4 py-5 grid md:grid-cols-[200px_1fr] gap-5">
        <SettingsNav base="/settings" entries={entries} label={t('settings.title')} />
        <section className="min-w-0">
          <Routes>
            <Route index element={<ProfileSettings />} />
            <Route path="boards" element={<BoardsSettings />} />
            <Route path="media" element={<MediaSettings />} />
            <Route path="channels" element={<ChannelsSettings />} />
            <Route path="tokens" element={<TokensSettings />} />
            {/* The three that moved to /system; old links and bookmarks keep working. */}
            <Route path="integrations" element={<Moved to="/system/integrations" />} />
            <Route path="users" element={<Moved to="/system/users" />} />
            <Route path="system" element={<Moved to="/system/about" />} />
            <Route path="*" element={<Navigate to="/settings" replace />} />
          </Routes>
        </section>
      </div>
    </AppShell>
  )
}
