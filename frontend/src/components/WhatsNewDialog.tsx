import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useAuth } from '../stores/auth'
import { Dialog } from './ui'
import { entriesFor, latestVersion } from '../lib/whatsnew'

/**
 * "Everything that is new": shown once per version to signed-in users.
 * An entry needs all four fields; one without them is ignored, and a guard
 * test keeps that from happening quietly.
 */
export function WhatsNewDialog() {
  const { t, i18n } = useTranslation()
  const { user, update } = useAuth()
  const [closed, setClosed] = useState(false)
  const version = latestVersion()
  if (closed || !user || !version || user.seen_version === version) return null
  const entry = entriesFor(i18n.language)[version]
  if (!entry) return null
  // ⚠️ Gone at once, and the note to the server follows. Every way out used to
  // wait for PATCH /auth/me, so with the server gone or the session expired the
  // X, Escape, the backdrop and the button did nothing and the board stayed out
  // of reach until the page was loaded again. A note that fails only means the
  // window comes back on the next visit.
  const close = () => {
    setClosed(true)
    update({ seen_version: version }).catch(() => undefined)
  }
  return (
    <Dialog
      open
      onClose={close}
      title={`${t('whatsnew.title')} · ${version}`}
      footer={
        <button className="btn btn-accent" onClick={close}>
          {t('whatsnew.gotIt')}
        </button>
      }
    >
      <p className="text-sm mb-4">{entry.lead}</p>
      {entry.sections.map((section, index) => (
        <div key={index} className="mb-3">
          <h3 className="text-sm font-semibold">{section.title}</h3>
          <p className="text-sm text-muted">{section.body}</p>
          {section.path && <p className="text-[11px] text-faint mt-0.5">{section.path}</p>}
        </div>
      ))}
      <h3 className="text-sm font-semibold mt-4">{entry.smallTitle}</h3>
      <ul className="text-sm text-muted list-disc pl-5">
        {entry.small.map((line, index) => (
          <li key={index}>{line}</li>
        ))}
      </ul>
    </Dialog>
  )
}
