import { Bell, Camera, ChevronDown, EyeOff, LogOut, Moon, Server, Sun, UserRound } from 'lucide-react'
import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'

import type { User } from '../api/types'
import { accountPair, guestPair, LANGUAGES, setLanguage } from '../i18n'
import { applyTheme, currentTheme, useAuth } from '../stores/auth'
import { usePicture } from '../lib/boardPicture'
import { madeUp, useShowcase } from '../lib/showcase'
import { usePlayer } from '../stores/player'
import { Avatar } from './Avatar'

/** Loaded only once something plays and the viewer put the player in the top bar. */
const HeaderPill = lazy(() => import('./player/HeaderPill').then((module) => ({ default: module.HeaderPill })))

/** What the tools need to know about the account; the preview page invents one. */
export type HeaderUser = Pick<User, 'display_name' | 'username' | 'role' | 'avatar_url'> & Partial<Pick<User, 'auth_kind'>>

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

/**
 * The language, switched here and kept with the account.
 *
 * Two buttons, whatever nexdeck speaks: the account chooses which two in its
 * profile, and the language on screen is always one of them. Where nobody is
 * signed in the pair is guessed from the screen and the browser.
 */
export function LanguagePill({ signedIn }: { signedIn: boolean }) {
  const { t, i18n } = useTranslation()
  const update = useAuth((s) => s.update)
  const chosen = useAuth((s) => s.user?.language_pair)
  const pair = signedIn ? accountPair(chosen) : guestPair(i18n.language)
  const choose = async (code: string) => {
    if (code === i18n.language) return
    if (signedIn) await update({ locale: code })
    else await setLanguage(code)
  }
  return (
    <div className={PILL} role="group" aria-label={t('settings.profile.language')}>
      {pair.map((code) => (
        <button
          key={code}
          type="button"
          className={`${SEGMENT} px-2 py-1 text-[11px] font-semibold uppercase ${i18n.language === code ? ACTIVE : IDLE}`}
          onClick={() => void choose(code)}
          aria-pressed={i18n.language === code}
          aria-label={LANGUAGES[code]}
          title={LANGUAGES[code]}
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
  const showcase = useShowcase((state) => state.on)
  const media = useShowcase((state) => state.media)
  const setShowcase = useShowcase((state) => state.setOn)
  const setMedia = useShowcase((state) => state.setMedia)
  const pictureAvailable = usePicture((state) => state.available)
  const openPicture = usePicture((state) => state.setOpen)
  const real = user.display_name || user.username
  // In showcase mode the account has a made-up name and no picture of its own.
  const name = showcase ? madeUp('person', real) : real
  const avatar = showcase ? undefined : user.avatar_url
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
        <Avatar url={avatar} name={name} size={26} />
        <span className="hidden max-w-32 truncate text-[13px] text-muted lg:inline">{name}</span>
        <ChevronDown size={13} className="text-faint" />
      </button>
      {open && (
        <div role="menu" className="glass-strong absolute right-0 top-11 z-50 w-56 rounded-xl p-1 shadow-2xl">
          <div className="mb-1 flex items-center gap-2.5 border-b border-line px-3 py-2.5">
            <Avatar url={avatar} name={name} size={36} />
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
          {/* Showcase mode: a way of drawing, kept in this browser, never stored on the server. */}
          <div className="mt-1 border-t border-line pt-1">
            <MenuSwitch checked={showcase} onChange={setShowcase} icon={<EyeOff size={15} />} label={t('showcase.mode')} />
            {showcase && <MenuSwitch checked={media} onChange={setMedia} label={t('showcase.media')} indent />}
            {pictureAvailable && (
              <button
                type="button"
                role="menuitem"
                className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-muted transition-colors hover:bg-surface-hover hover:text-ink"
                onClick={() => {
                  setOpen(false)
                  openPicture(true)
                }}
              >
                <Camera size={15} />
                {t('picture.menu')}
              </button>
            )}
          </div>
          <button
            type="button"
            role="menuitem"
            className="mt-1 flex w-full items-center gap-2 rounded-lg border-t border-line px-3 py-2 text-left text-sm text-muted transition-colors hover:bg-surface-hover hover:text-ink"
            onClick={() => void logout().then(() => navigate('/login'))}
          >
            <LogOut size={15} />
            {/* Signed in on the home network without a password: leaving
                means signing in as somebody, and the page will not sign
                straight back in for twelve hours. */}
            {user.auth_kind === 'home' ? t('menu.signInWithPassword') : t('menu.signOut')}
          </button>
        </div>
      )}
    </div>
  )
}

/** A switch in the account menu: a row that says what it is, and a small toggle that says whether it is on. */
function MenuSwitch({ checked, onChange, label, icon, indent = false }: { checked: boolean; onChange: (value: boolean) => void; label: string; icon?: React.ReactNode; indent?: boolean }) {
  return (
    <button
      type="button"
      role="menuitemcheckbox"
      aria-checked={checked}
      className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-muted transition-colors hover:bg-surface-hover hover:text-ink ${indent ? 'pl-9 text-[13px]' : ''}`}
      onClick={() => onChange(!checked)}
    >
      {icon}
      <span className="flex-1">{label}</span>
      <span className={`relative h-4 w-7 flex-none rounded-full transition-colors ${checked ? 'bg-accent' : 'bg-line-strong'}`} aria-hidden="true">
        <span className={`absolute top-0.5 h-3 w-3 rounded-full bg-white transition-all ${checked ? 'left-3.5' : 'left-0.5'}`} />
      </span>
    </button>
  )
}

/**
 * While showcase mode is on, a mark in the bar says so, and a press on it
 * switches it off: a board that lies about its names must not look like one
 * that does not.
 */
function ShowcaseMark() {
  const { t } = useTranslation()
  const on = useShowcase((state) => state.on)
  const setOn = useShowcase((state) => state.setOn)
  if (!on) return null
  return (
    <button
      type="button"
      className="flex h-8 items-center gap-1.5 rounded-full border border-accent/50 bg-accent-soft px-2.5 text-[12px] font-medium text-accent"
      onClick={() => setOn(false)}
      title={t('showcase.offTitle')}
      aria-label={t('showcase.offTitle')}
      data-testid="showcase-mark"
    >
      <EyeOff size={13} />
      <span className="hidden sm:inline">{t('showcase.on')}</span>
    </button>
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
      <ShowcaseMark />
      <NoticeButton unread={unread} onClick={onNotices} />
      <span className="hidden sm:flex items-center gap-1.5">
        <ThemePill signedIn={signedIn} />
        <LanguagePill signedIn={signedIn} />
      </span>
      {user && <UserMenu user={user} />}
    </div>
  )
}
