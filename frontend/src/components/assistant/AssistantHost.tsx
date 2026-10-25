/**
 * Where the chat lives: once, above every page, so a conversation goes on
 * from one board to the next and on into the settings.
 *
 * The panel is fetched the first time it opens and then stays, hidden while
 * closed, with its conversation.
 */
import { Sparkles } from 'lucide-react'
import { lazy, Suspense, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useAssistant } from '../../lib/assistant'
import { useAuth } from '../../stores/auth'

const AssistantPanel = lazy(() => import('./AssistantPanel').then((module) => ({ default: module.AssistantPanel })))

export function AssistantHost() {
  const admin = useAuth((s) => s.user?.role === 'admin')
  const open = useAssistant((s) => s.open)
  const [opened, setOpened] = useState(false)
  useEffect(() => {
    if (open) setOpened(true)
  }, [open])
  if (!admin || !opened) return null
  return (
    <Suspense fallback={null}>
      <AssistantPanel open={open} />
    </Suspense>
  )
}

/** The ✦ next to the bell, for administrators once a provider is set up. */
export function AssistantButton() {
  const { t } = useTranslation()
  const admin = useAuth((s) => s.user?.role === 'admin')
  const ready = useAssistant((s) => s.state?.ready ?? false)
  const open = useAssistant((s) => s.open)
  const setOpen = useAssistant((s) => s.setOpen)
  const load = useAssistant((s) => s.load)
  useEffect(() => {
    // Once per page load: the setting page reads it again after a change.
    if (admin && useAssistant.getState().state === null) void load()
  }, [admin, load])
  if (!admin || !ready) return null
  return (
    <button
      type="button"
      className={`flex h-8 w-8 items-center justify-center rounded-full border transition-colors ${open ? 'border-accent bg-accent-soft text-accent' : 'border-accent/40 text-accent hover:border-accent'}`}
      onClick={() => setOpen(!open)}
      aria-pressed={open}
      aria-label={t('assistant.title')}
      title={t('assistant.title')}
      data-testid="assistant-button"
    >
      <Sparkles size={15} />
    </button>
  )
}
