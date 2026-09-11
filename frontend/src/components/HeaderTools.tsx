import { Bell, ChevronDown, LogOut, Moon, Server, Sun, UserRound } from 'lucide-react'
import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'

import type { User } from '../api/types'
import { LANGUAGES, setLanguage } from '../i18n'
import { applyTheme, currentTheme, useAuth } from '../stores/auth'
import { usePlayer } from '../stores/player'
import { Avatar } from './Avatar'

/** Loaded only once something plays and the viewer put the player in the top bar. */
const HeaderPill = lazy(() => import('./player/HeaderPill').then((module) => ({ default: module.HeaderPill })))

/** What the tools need to know about the account; the preview page invents one. */
export type HeaderUser = Pick<User, 'display_name' | 'username' | 'role' | 'avatar_url'>

interface Props {
  user: HeaderUser | null
  unread: number
  onNotices: () => void
}

const PILL = 'flex items-center rounded-full border border-line bg-bg/40 p-0.5'
const SEGMENT = 'rounded-full transition-colors'
const ACTIVE = 'bg-accent text-on-accent'
const IDLE = 'text-muted hover:text-ink'

/** Unread notices. The number sits on the bell, so it is seen without opening anything. */
function NoticeButton({ unread, onClick }: { unread: number; onClick: () => void }) {
  const { t } = useTranslation()
  return (
    <button
      type="button"
      className="relative flex h-8 w-8 items-center justify-center rounded-full border border-line text-muted transition-colors hover:border-line-strong hover:text-ink"
      onClick={onClick}
      aria-label={t('notices.title')}
      title={t('notices.title')}
    >
      <Bell size={15} />
      {unread > 0 && (
        <span className="num absolute -top-1 -right-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[10px] font-semibold text-on-accent">
          {unread > 9 ? '9+' : unread}
        </span>
      )}
    </button>
  )
}

/**
 * Dark and light side by side, not one button that swaps its icon.
 *
 * Two segments say which of the two is on; a single icon only says what a
 * click would do, and everyone reads that the other way round at least once.
 * "Follow the system" stays in the settings: it is a decision, not a switch.
 */
function ThemePill({ signedIn }: { signedIn: boolean }) {
  const { t } = useTranslation()
  const update = useAuth((s) => s.update)
  const [theme, setTheme] = useState(currentTheme())
  const choose = (next: 'dark' | 'light') => {
    if (next === theme) return
    setTheme(next)
    applyTheme(next)
    if (signedIn) void update({ theme: next })
  }
  return (
    <div className={PILL} role="group" aria-label={t('settings.profile.theme')}>
      {([
        ['dark', Moon, t('settings.profile.theme_dark')],
        ['light', Sun, t('settings.profile.theme_light')],
      ] as const).map(([value, Icon, label]) => (
        <button
          key={value}
          type="button"
          className={`${SEGMENT} p-1.5 ${theme === value ? ACTIVE : IDLE}`}
          onClick={() => choose(value)}
          aria-pressed={theme === value}
          aria-label={label}
          title={label}
        >
          <Icon size={14} />
        </button>
      ))}
    </div>
  )
}

/** The language, switched here and kept with the account. */
function LanguagePill({ signedIn }: { signedIn: boolean }) {
  const { t, i18n } = useTranslation()
  const update = useAuth((s) => s.update)
  const choose = async (code: string) => {
    if (code === i18n.language) return
    if (signedIn) await update({ locale: code })
    else await setLanguage(code)
  }
  return (
    <div className={PILL} role="group" aria-label={t('settings.profile.language')}>
      {Object.entries(LANGUAGES).map(([code, label]) => (
        <button
          key={code}
          type="button"
          className={`${SEGMENT} px-2 py-1 text-[11px] font-semibold uppercase ${i18n.language === code ? ACTIVE : IDLE}`}
          onClick={() => void choose(code)}
          aria-pressed={i18n.language === code}
          aria-label={label}
          title={label}
        >
          {code}
        </button>
      ))}
    </div>
  )
}

/**
 * The account menu behind the picture.
 *
 * Everything that belongs to a person hangs here, and next to it the way into
 * the system, so the two are never the same list again.
 */
function UserMenu({ user }: { user: HeaderUser }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const logout = useAuth((s) => s.logout)
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onClick = (event: MouseEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('mousedown', onClick)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('mousedown', onClick)
      window.removeEventListener('keydown', onKey)
    }
  }, [open])
  const name = user.display_name || user.username
  const entries = [
    { to: '/settings', icon: UserRound, label: t('menu.settings') },
    { to: '/system', icon: Server, label: t('menu.system') },
  ]
  return (
    <div className="relative" ref={box}>
      <button
        type="button"
        className="flex items-center gap-2 rounded-full border border-line py-0.5 pr-2.5 pl-0.5 transition-colors hover:border-line-strong"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={name}
      >
        <Avatar url={user.avatar_url} name={name} size={26} />
        <span className="hidden max-w-32 truncate text-[13px] text-muted sm:inline">{name}</span>
        <ChevronDown size={13} className="text-faint" />
      </button>
      {open && (
        <div role="menu" className="glass-strong absolute right-0 top-11 z-50 w-56 rounded-xl p-1 shadow-2xl">
          <div className="mb-1 flex items-center gap-2.5 border-b border-line px-3 py-2.5">
            <Avatar url={user.avatar_url} name={name} size={36} />
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold">{name}</p>
              <p className="truncate text-[11px] text-muted">{t(`users.role.${user.role}`)}</p>
            </div>
          </div>
          {entries.map((entry) => (
            <Link
              key={entry.to}
              to={entry.to}
              role="menuitem"
              className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-muted transition-colors hover:bg-surface-hover hover:text-ink"
              onClick={() => setOpen(false)}
            >
              <entry.icon size={15} />
              {entry.label}
            </Link>
          ))}
          <button
            type="button"
            role="menuitem"
            className="mt-1 flex w-full items-center gap-2 rounded-lg border-t border-line px-3 py-2 text-left text-sm text-muted transition-colors hover:bg-surface-hover hover:text-ink"
            onClick={() => void logout().then(() => navigate('/login'))}
          >
            <LogOut size={15} />
            {t('menu.signOut')}
          </button>
        </div>
      )}
    </div>
  )
}

/**
 * The right-hand end of every bar: notices, appearance, language, account.
 *
 * One component for both bars. They drifted apart once already, and a bar that
 * looks different depending on the page reads as a different app.
 */
export function HeaderTools({ user, unread, onNotices }: Props) {
  const signedIn = useAuth((s) => s.user !== null)
  const playing = usePlayer((s) => s.queue.length > 0 && s.barStyle === 'header')
  return (
    <div className="flex items-center gap-1.5">
      {playing && (
        <Suspense fallback={null}>
          <HeaderPill />
        </Suspense>
      )}
      <NoticeButton unread={unread} onClick={onNotices} />
      <span className="hidden sm:flex items-center gap-1.5">
        <ThemePill signedIn={signedIn} />
        <LanguagePill signedIn={signedIn} />
      </span>
      {user && <UserMenu user={user} />}
    </div>
  )
}
