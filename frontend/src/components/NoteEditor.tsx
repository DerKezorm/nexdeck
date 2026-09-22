/**
 * Writing a Notes card from the card itself.
 *
 * Saved when the typing pauses and when the field is left, through its own
 * address, which refuses a save whose starting point is no longer what is
 * stored (`PUT /widgets/{id}/note`). Two tablets on one shopping list would
 * otherwise take turns wiping out each other's lines. On a refusal both
 * texts are offered: keep mine, or take the one that is stored.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, put } from '../api/client'
import { NOTE_LIMIT } from '../lib/notes'

export type NoteState = 'idle' | 'saving' | 'saved' | 'conflict' | 'failed'

/** One save of a note; on a refusal, the text that is stored. */
export async function saveNote(widgetId: number, content: string, basedOn: string): Promise<{ ok: true } | { ok: false; current?: string; message: string }> {
  try {
    await put(`/widgets/${widgetId}/note`, { content, based_on: basedOn })
    return { ok: true }
  } catch (failure) {
    if (failure instanceof ApiError && failure.code === 'note_changed') {
      return { ok: false, current: String(failure.detail.current ?? ''), message: failure.message }
    }
    return { ok: false, message: failure instanceof ApiError ? failure.message : '' }
  }
}

const PAUSE_MS = 800

export function NoteEditor({ widgetId, initial, onSaved, onClose }: { widgetId: number; initial: string; onSaved: (text: string) => void; onClose: () => void }) {
  const { t } = useTranslation()
  const [text, setText] = useState(initial)
  const [state, setState] = useState<NoteState>('idle')
  const [stored, setStored] = useState('')
  // What the server holds as far as this editor knows: the starting point of the next save.
  const base = useRef(initial)
  const timer = useRef(0)
  const latest = useRef(initial)

  const save = useCallback(
    (content: string, from: string = base.current) => {
      window.clearTimeout(timer.current)
      if (content === base.current && from === base.current) return Promise.resolve()
      setState('saving')
      return saveNote(widgetId, content, from).then((answer) => {
        if (answer.ok) {
          base.current = content
          onSaved(content)
          setState(latest.current === content ? 'saved' : 'idle')
        } else if (answer.current !== undefined) {
          setStored(answer.current)
          setState('conflict')
        } else {
          setState('failed')
        }
      })
    },
    [widgetId, onSaved],
  )

  useEffect(() => () => window.clearTimeout(timer.current), [])

  const change = (value: string) => {
    setText(value)
    latest.current = value
    if (state === 'conflict') return
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(() => void save(value), PAUSE_MS)
  }

  const finish = () => {
    if (state === 'conflict') return
    void save(latest.current).then(onClose)
  }

  return (
    <div className="flex-1 min-h-0 flex flex-col px-2 pb-2 gap-1.5 no-drag">
      <textarea
        className="input flex-1 min-h-0 resize-none font-mono text-[12px] leading-relaxed"
        value={text}
        maxLength={NOTE_LIMIT}
        autoFocus
        aria-label={t('card.note.field')}
        onChange={(event) => change(event.target.value)}
        onBlur={() => {
          if (state !== 'conflict') void save(latest.current)
        }}
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            event.preventDefault()
            finish()
          }
        }}
      />
      {state === 'conflict' ? (
        <div className="rounded-lg border border-warn/40 bg-warn/10 px-2 py-1.5 text-[12px]" role="alert">
          <p>{t('card.note.conflict')}</p>
          <div className="flex gap-1.5 mt-1.5">
            <button type="button" className="btn h-7 px-2 text-xs" onClick={() => void save(latest.current, stored)}>
              {t('card.note.keepMine')}
            </button>
            <button
              type="button"
              className="btn h-7 px-2 text-xs"
              onClick={() => {
                base.current = stored
                latest.current = stored
                setText(stored)
                onSaved(stored)
                setState('idle')
              }}
            >
              {t('card.note.takeTheirs')}
            </button>
          </div>
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-faint flex-1" aria-live="polite">
            {state === 'saving' ? t('card.note.saving') : state === 'saved' ? t('card.note.saved') : state === 'failed' ? t('card.note.failed') : ''}
          </span>
          <button type="button" className="btn h-7 px-2 text-xs" onClick={finish}>
            {t('card.note.done')}
          </button>
        </div>
      )}
    </div>
  )
}
