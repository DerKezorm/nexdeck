import { useQuery } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, get, patch, post } from '../../api/client'
import type { About } from '../../api/types'
import { LogoMark } from '../../components/Logo'
import { Dialog, Switch, Toast } from '../../components/ui'
import { entriesFor, latestVersion } from '../../lib/whatsnew'
import { useAuth } from '../../stores/auth'
import { SettingsCard } from './SettingsCard'

/** A link that leaves nexdeck, always in a new tab. */
function Out({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noreferrer noopener" className="text-accent underline decoration-accent/40 underline-offset-4 hover:decoration-accent">
      {children}
    </a>
  )
}

/** One line of the fact list. */
function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 border-b border-line py-2.5 last:border-b-0">
      <dt className="text-sm text-muted">{label}</dt>
      <dd className="text-sm font-medium">{children}</dd>
    </div>
  )
}

/**
 * What nexdeck is built on, and who came first.
 *
 * Kept by hand. Generating it from the dependency files would list dozens of
 * packages nobody reads; these are the ones nexdeck actually stands on.
 */
const BUILT_WITH = [
  { name: 'FastAPI', url: 'https://fastapi.tiangolo.com', license: 'MIT' },
  { name: 'SQLAlchemy', url: 'https://www.sqlalchemy.org', license: 'MIT' },
  { name: 'Pydantic', url: 'https://docs.pydantic.dev', license: 'MIT' },
  { name: 'Uvicorn', url: 'https://www.uvicorn.org', license: 'BSD' },
  { name: 'HTTPX', url: 'https://www.python-httpx.org', license: 'BSD' },
  { name: 'websockets', url: 'https://websockets.readthedocs.io', license: 'BSD' },
  { name: 'cryptography', url: 'https://cryptography.io', license: 'Apache 2.0 / BSD' },
  { name: 'bcrypt', url: 'https://github.com/pyca/bcrypt', license: 'Apache 2.0' },
  { name: 'PyJWT', url: 'https://pyjwt.readthedocs.io', license: 'MIT' },
  { name: 'PyYAML', url: 'https://pyyaml.org', license: 'MIT' },
  { name: 'feedparser', url: 'https://feedparser.readthedocs.io', license: 'BSD' },
  { name: 'py-vapid', url: 'https://github.com/web-push-libs/vapid', license: 'MPL 2.0' },
  { name: 'React', url: 'https://react.dev', license: 'MIT' },
  { name: 'Vite', url: 'https://vite.dev', license: 'MIT' },
  { name: 'Tailwind CSS', url: 'https://tailwindcss.com', license: 'MIT' },
  { name: 'TanStack Query', url: 'https://tanstack.com/query', license: 'MIT' },
  { name: 'React Router', url: 'https://reactrouter.com', license: 'MIT' },
  { name: 'react-grid-layout', url: 'https://github.com/react-grid-layout/react-grid-layout', license: 'MIT' },
  { name: 'Zustand', url: 'https://zustand.docs.pmnd.rs', license: 'MIT' },
  { name: 'i18next', url: 'https://www.i18next.com', license: 'MIT' },
  { name: 'mpegts.js', url: 'https://github.com/xqq/mpegts.js', license: 'Apache 2.0' },
  { name: 'marked', url: 'https://marked.js.org', license: 'MIT' },
  { name: 'DOMPurify', url: 'https://github.com/cure53/DOMPurify', license: 'Apache 2.0 / MPL 2.0' },
  { name: 'Inter', url: 'https://rsms.me/inter', license: 'OFL 1.1' },
  { name: 'JetBrains Mono', url: 'https://www.jetbrains.com/lp/mono', license: 'OFL 1.1' },
]

/** Thanks, and the notes that are not politeness but obligation. */
function Thanks() {
  const { t } = useTranslation()
  return (
    <SettingsCard title={t('about.thanks')} description={t('about.thanksIntro')}>
      <div className="flex flex-col gap-5">
        <div>
          <p className="text-[11px] uppercase tracking-wide text-faint">{t('about.forerunners')}</p>
          <ul className="mt-1.5 flex flex-col gap-1.5 text-sm">
            <li>
              <Out href="https://homarr.dev">Homarr</Out>
              {' · '}
              <Out href="https://gethomepage.dev">Homepage</Out>
              {' · '}
              <Out href="https://github.com/glanceapp/glance">Glance</Out>
              <span className="mt-0.5 block text-xs leading-relaxed text-muted">{t('about.forerunnersNote')}</span>
            </li>
          </ul>
        </div>

        <div>
          <p className="text-[11px] uppercase tracking-wide text-faint">{t('about.icons')}</p>
          <ul className="mt-1.5 flex flex-col gap-1.5 text-sm">
            <li>
              <Out href="https://github.com/homarr-labs/dashboard-icons">Dashboard Icons</Out>
              {' · '}
              <Out href="https://lucide.dev">Lucide</Out>
              <span className="mt-0.5 block text-xs leading-relaxed text-muted">{t('about.iconsNote')}</span>
            </li>
          </ul>
        </div>

        <div>
          <p className="text-[11px] uppercase tracking-wide text-faint">{t('about.dataSources')}</p>
          <ul className="mt-1.5 flex flex-col gap-1.5 text-sm">
            <li>
              <Out href="https://open-meteo.com">Open-Meteo</Out>
              <span className="mt-0.5 block text-xs leading-relaxed text-muted">{t('about.weatherNote')}</span>
            </li>
            <li>
              <span className="text-ink">{t('about.services')}</span>
              <span className="mt-0.5 block text-xs leading-relaxed text-muted">{t('about.servicesNote')}</span>
            </li>
          </ul>
        </div>

        <div>
          <p className="text-[11px] uppercase tracking-wide text-faint">{t('about.notifyServices')}</p>
          <ul className="mt-1.5 flex flex-col gap-1.5 text-sm">
            <li>
              <Out href="https://ntfy.sh">ntfy</Out>
              {' · '}
              <Out href="https://gotify.net">Gotify</Out>
              {' · '}
              <Out href="https://telegram.org">Telegram</Out>
              {' · '}
              <Out href="https://discord.com">Discord</Out>
              {' · '}
              <Out href="https://slack.com">Slack</Out>
              {' · '}
              <Out href="https://github.com/caronc/apprise">Apprise</Out>
              <span className="mt-0.5 block text-xs leading-relaxed text-muted">{t('about.notifyNote')}</span>
            </li>
          </ul>
        </div>

        <div>
          <p className="text-[11px] uppercase tracking-wide text-faint">{t('about.builtWith')}</p>
          <ul className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1.5 text-sm">
            {BUILT_WITH.map((part) => (
              <li key={part.name}>
                <Out href={part.url}>{part.name}</Out>
                <span className="ml-1 text-xs text-faint">({part.license})</span>
              </li>
            ))}
          </ul>
        </div>

        <div>
          <p className="text-[11px] uppercase tracking-wide text-faint">{t('about.family')}</p>
          <p className="mt-1.5 text-sm">
            <Out href="https://nexview.nexapps.dev">Nexview</Out>
            {' · '}
            <Out href="https://nexmail.nexapps.dev">nexmail</Out>
            <span className="mt-0.5 block text-xs leading-relaxed text-muted">{t('about.familyNote')}</span>
          </p>
        </div>
      </div>
    </SettingsCard>
  )
}

/**
 * About nexdeck: what this installation is, where it comes from, what it
 * stands on.
 *
 * The update check lives here and not with the other switches: whoever wants
 * to know what goes out looks at the page that shows the answer.
 */
export function AboutSettings() {
  const { t, i18n } = useTranslation()
  const admin = useAuth((state) => state.user?.role === 'admin')
  const about = useQuery({ queryKey: ['about'], queryFn: () => get<About>('/about') })
  const [toast, setToast] = useState<{ text: string; level: 'ok' | 'error' } | null>(null)
  const [whatsNew, setWhatsNew] = useState(false)
  const data = about.data
  const version = latestVersion()
  const entry = version ? entriesFor(i18n.language)[version] : undefined
  const fail = (failure: unknown) => setToast({ text: failure instanceof ApiError ? failure.message : t('errors.network'), level: 'error' })
  const newer = Boolean(data?.latest_version && data.latest_version !== data.version)

  return (
    <>
      <div className="flex flex-col items-center gap-2 py-6 text-center">
        <LogoMark size={44} />
        <h1 className="text-2xl font-bold tracking-tight">
          nex<span className="text-accent">deck</span>
        </h1>
        <p className="max-w-md text-sm leading-relaxed text-muted">{t('about.tagline')}</p>
      </div>

      <SettingsCard title={t('about.thisInstallation')}>
        <dl>
          <Row label={t('settings.system.version')}>
            <span className="num">{data?.version ?? '…'}</span>
            {newer && <span className="chip ml-2 !py-0 text-[10px]">{t('settings.system.updateAvailable', { version: data?.latest_version })}</span>}
          </Row>
          <Row label={t('settings.system.boards')}>
            <span className="num">{data?.counts.boards ?? 0}</span>
          </Row>
          <Row label={t('settings.system.widgets')}>
            <span className="num">{data?.counts.widgets ?? 0}</span>
          </Row>
          <Row label={t('settings.nav.integrations')}>
            <span className="num">{data?.counts.integrations ?? 0}</span>
          </Row>
          <Row label={t('settings.system.connections')}>
            <span className="num">{data?.connections ?? 0}</span>
          </Row>
          {entry && (
            <Row label={t('whatsnew.title')}>
              <button type="button" className="text-accent underline underline-offset-2" onClick={() => setWhatsNew(true)}>
                {t('about.whatsNewOpen')}
              </button>
            </Row>
          )}
        </dl>
      </SettingsCard>

      <SettingsCard title={t('about.project')}>
        <dl>
          <Row label={t('about.source')}>
            <Out href={data?.repo_url ?? '#'}>{t('about.onGithub')}</Out>
          </Row>
          <Row label={t('about.releases')}>
            <Out href={data?.release_url ?? '#'}>{t('about.allVersions')}</Out>
          </Row>
          <Row label={t('about.issues')}>
            <Out href={data?.issues_url ?? '#'}>{t('about.issuesOpen')}</Out>
          </Row>
          <Row label={t('about.website')}>
            <Out href={data?.website_url ?? '#'}>{(data?.website_url ?? '').replace('https://', '')}</Out>
          </Row>
          <Row label={t('about.license')}>{data?.license ?? 'AGPL-3.0-or-later'}</Row>
        </dl>
      </SettingsCard>

      {admin && data && (
        <SettingsCard title={t('settings.system.updateCheck')} description={t('settings.system.updateCheckHelp')}>
          <Switch
            checked={data.update_check}
            onChange={(update_check) =>
              void patch('/settings', { update_check })
                .then(() => about.refetch())
                .catch(fail)
            }
            label={t('about.updateCheckLabel')}
          />
          {/* ⚠️ Always, not only while the daily check is on. It used to hang
              off that switch, so the one person who most wants to look now and
              then, the one who deliberately keeps the daily outbound call off,
              was the one with no button. The switch decides whether nexdeck
              asks by itself; this asks once, because somebody pressed it. */}
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <button
              className="btn"
              onClick={() =>
                void post<About>('/about/check')
                  .then(() => about.refetch())
                  .then(() => setToast({ text: t('about.checked'), level: 'ok' }))
                  .catch(fail)
              }
            >
              {t('about.checkNow')}
            </button>
            <span className="text-xs text-muted">
              {newer
                ? t('about.updateAvailable', { version: data.latest_version })
                : data.latest_version
                  ? t('about.upToDate')
                  : data.checked_at
                    ? t('about.askFailed')
                    : t('about.neverChecked')}
            </span>
            {data.checked_at && <span className="text-xs text-faint">{t('about.lastChecked', { when: new Date(data.checked_at).toLocaleString(i18n.language) })}</span>}
          </div>
        </SettingsCard>
      )}

      <Thanks />

      {entry && (
        <Dialog open={whatsNew} onClose={() => setWhatsNew(false)} title={`${t('whatsnew.title')} · ${version}`}>
          <p className="text-sm mb-4">{entry.lead}</p>
          {entry.sections.map((section) => (
            <div key={section.title} className="mb-3">
              <h3 className="text-sm font-semibold">{section.title}</h3>
              <p className="text-sm text-muted">{section.body}</p>
              {section.path && <p className="text-[11px] text-faint mt-0.5">{section.path}</p>}
            </div>
          ))}
          <h3 className="text-sm font-semibold mt-4">{entry.smallTitle}</h3>
          <ul className="text-sm text-muted list-disc pl-5">
            {entry.small.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </Dialog>
      )}

      {toast && (
        <Toast level={toast.level} onClose={() => setToast(null)}>
          {toast.text}
        </Toast>
      )}
    </>
  )
}
