import { Bell, Bot, Disc3, Images, KeyRound, LayoutDashboard, User } from 'lucide-react'
import { lazy, Suspense } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, Navigate, Route, Routes, useLocation } from 'react-router-dom'

import { AppShell } from '../../components/AppShell'
import { useMcpTexts } from '../../lib/mcpTexts'
import { useAuth } from '../../stores/auth'
import { BoardsSettings } from './BoardsSettings'
import { MediaSettings } from './MediaSettings'
import { ChannelsSettings } from './ChannelsSettings'
import { PlayerSettings } from './PlayerSettings'
import { ProfileSettings } from './ProfileSettings'
import { SettingsNav, type NavEntry } from './SettingsNav'
import { TokensSettings } from './TokensSettings'
import { AddressBarHelp } from './AddressBarHelp'

// The MCP keys have a page of their own and load on their own, with their own words.
const McpKeys = lazy(() => import('./McpKeys').then((m) => ({ default: m.McpKeys })))

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
 * The API tokens, with a pointer to the MCP keys above them.
 *
 * ⚠️ The MCP keys stood right under the tokens and looked alike: the first
 * key for Claude Code was an API token, which MCP does not take. They have a
 * page of their own now, and the old address (``#mcp``) leads there.
 */
function Tokens({ mcpWords }: { mcpWords: boolean }) {
  const { t } = useTranslation()
  const { hash } = useLocation()
  if (hash === '#mcp') return <Navigate to="/settings/mcp" replace />
  return (
    <>
      {mcpWords && (
        <p className="glass rounded-xl px-4 py-3 mb-4 text-sm" data-testid="mcp-hint">
          {t('mcp.keys.tokensHint')}{' '}
          <Link to="/settings/mcp" className="text-accent font-medium">
            {t('mcp.nav')}
          </Link>
        </p>
      )}
      <TokensSettings />
    </>
  )
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
  // The MCP entry's name is one of the MCP words, which come in a language a moment after the page.
  const mcpWords = useMcpTexts()
  const entries: NavEntry[] = [
    { to: '', icon: User, label: t('settings.nav.profile') },
    { to: 'boards', icon: LayoutDashboard, label: t('settings.nav.boards'), show: member },
    { to: 'media', icon: Images, label: t('settings.nav.media'), show: member },
    { to: 'channels', icon: Bell, label: t('settings.nav.channels'), show: member },
    { to: 'player', icon: Disc3, label: t('settings.nav.player'), show: member },
    { to: 'tokens', icon: KeyRound, label: t('settings.nav.tokens'), show: member },
    { to: 'mcp', icon: Bot, label: t('mcp.nav'), show: member && mcpWords },
  ]
  return (
    <AppShell title={t('settings.title')}>
      <div className="max-w-5xl mx-auto px-3 sm:px-4 py-5 grid md:grid-cols-[200px_1fr] gap-5">
        <SettingsNav base="/settings" entries={entries} label={t('settings.title')} />
        <section className="min-w-0">
          <Routes>
            <Route index element={<ProfileSettings />} />
            <Route
              path="boards"
              element={
                <>
                  <BoardsSettings />
                  <AddressBarHelp />
                </>
              }
            />
            <Route path="media" element={<MediaSettings />} />
            <Route path="channels" element={<ChannelsSettings />} />
            <Route path="player" element={<PlayerSettings />} />
            <Route path="tokens" element={<Tokens mcpWords={mcpWords} />} />
            <Route
              path="mcp"
              element={
                <Suspense fallback={null}>
                  <McpKeys />
                </Suspense>
              }
            />
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
