/**
 * The tab "AI" of the skin editor: say what the skin should look like, the
 * provider of the assistant makes or changes it, the stage wears it, and then
 * it looks at the stage once and improves what reads badly or does not yet look
 * like the request. Every answer is one step back (undo). Sections locked here
 * are put back by the server whatever the provider does with them.
 */
import { Lock, LockOpen, Send, Square } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, del, post } from '../../api/client'
import type { Draft, SkinDoc } from '../../lib/skin/draft'
import type { Seen } from '../../lib/skin/look'

/** The sections of a skin file a lock holds, as the server knows them (backend/app/skins/ai.py SECTIONS). */
export const LOCKABLE = ['tokens', 'options', 'sprites', 'frames', 'desk', 'decorations', 'status', 'parts', 'sounds', 'switches', 'css'] as const

interface Answer {
  ok: boolean
  skin: SkinDoc
  text: string
  problems: { path?: string; message: string; line?: number }[]
}

interface Said {
  who: 'you' | 'ai' | 'note' | 'error'
  text: string
}

/** The stage in dark and in light mode: what it found, and a picture of each where the provider sees one. */
export type LookAtStage = (picture: boolean) => Promise<Seen>

/** How long the stage needs to wear a new skin: the server checks it a moment after the change, then the stage draws it. */
const SETTLE_MS = 1500

export function AiTab({ doc, draft, locked, onLocked, sees, look }: { doc: SkinDoc; draft: Draft; locked: string[]; onLocked: (next: string[]) => void; sees: boolean; look: LookAtStage }) {
  const { t } = useTranslation()
  const [prompt, setPrompt] = useState('')
  const [said, setSaid] = useState<Said[]>([])
  const [working, setWorking] = useState<'' | 'making' | 'looking'>('')
  const tell = (entry: Said) => setSaid((current) => [...current, entry])

  const ask = async () => {
    const request = prompt.trim()
    if (!request || working) return
    setPrompt('')
    tell({ who: 'you', text: request })
    setWorking('making')
    try {
      const first = await post<Answer>('/skins/ai', { prompt: request, skin: doc, locked })
      if (!first.ok) {
        tell({ who: 'error', text: [t('skinEditor.ai.failed'), ...first.problems.slice(0, 5).map((problem) => `• ${problem.message}`)].join('\n') })
        return
      }
      draft.set(first.skin)
      if (first.text) tell({ who: 'ai', text: first.text })
      // A second look: the stage wears the skin first, then it is shown to the provider (a picture where it sees one).
      setWorking('looking')
      await new Promise((resolve) => window.setTimeout(resolve, SETTLE_MS))
      const seen = await look(sees)
      if (seen.pictures.length === 0 && seen.findings.length === 0) return
      tell({ who: 'note', text: seen.pictures.length > 0 ? t('skinEditor.ai.looking') : t('skinEditor.ai.checking', { count: seen.findings.length }) })
      const pictures = seen.pictures.map(({ mode, image }) => ({ mode, data: image, media_type: 'image/jpeg' }))
      const second = await post<Answer>('/skins/ai', { prompt: request, skin: first.skin, locked, review: true, pictures, audit: seen.findings })
      if (second.ok && JSON.stringify(second.skin) !== JSON.stringify(first.skin)) {
        draft.set(second.skin)
        tell({ who: 'ai', text: second.text || t('skinEditor.ai.improved') })
      } else if (second.ok) {
        tell({ who: 'note', text: t('skinEditor.ai.unchanged') })
      }
    } catch (failure) {
      const code = failure instanceof ApiError ? failure.code : ''
      if (code !== 'ai_cancelled') tell({ who: 'error', text: failure instanceof ApiError ? failure.message : t('errors.network') })
    } finally {
      setWorking('')
    }
  }

  const toggle = (section: string) => onLocked(locked.includes(section) ? locked.filter((name) => name !== section) : [...locked, section])

  return (
    <div className="flex flex-col gap-3" data-testid="skin-ai">
      <p className="text-xs text-muted">{sees ? t('skinEditor.ai.helpSees') : t('skinEditor.ai.help')}</p>
      <ol className="flex flex-col gap-2 text-sm" aria-live="polite">
        {said.map((entry, index) => (
          <li
            key={index}
            className={`rounded-lg px-3 py-2 whitespace-pre-line ${entry.who === 'you' ? 'bg-accent-soft self-end max-w-[90%]' : entry.who === 'error' ? 'bg-bad/10 text-bad' : entry.who === 'note' ? 'text-xs text-muted' : 'border border-line'}`}
          >
            {entry.text}
          </li>
        ))}
        {working && <li className="text-xs text-muted">{working === 'making' ? t('skinEditor.ai.making') : t('skinEditor.ai.lookingNow')}</li>}
      </ol>
      <textarea
        className="input h-24 text-sm"
        value={prompt}
        maxLength={2000}
        placeholder={t('skinEditor.ai.placeholder')}
        aria-label={t('skinEditor.ai.prompt')}
        onChange={(event) => setPrompt(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) void ask()
        }}
      />
      <div className="flex gap-2">
        <button type="button" className="btn btn-accent" disabled={!prompt.trim() || working !== ''} onClick={() => void ask()}>
          <Send size={14} /> {t('skinEditor.ai.send')}
        </button>
        {working && (
          <button type="button" className="btn" onClick={() => void del('/skins/ai').catch(() => undefined)}>
            <Square size={14} /> {t('skinEditor.ai.cancel')}
          </button>
        )}
      </div>
      <div className="border-t border-line pt-3">
        <p className="text-xs font-medium">{t('skinEditor.ai.locks')}</p>
        <p className="text-[11px] text-faint mb-2">{t('skinEditor.ai.locksHelp')}</p>
        <div className="flex flex-wrap gap-1">
          {LOCKABLE.map((section) => (
            <button key={section} type="button" className="btn btn-flat text-xs" aria-pressed={locked.includes(section)} onClick={() => toggle(section)}>
              {locked.includes(section) ? <Lock size={12} /> : <LockOpen size={12} />} {t(`skinEditor.ai.section.${section}`)}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
