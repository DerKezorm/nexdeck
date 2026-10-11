import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, ApiError, put } from '../api/client'
import { Dialog } from './ui'

/**
 * The board as text, changed where it stands (issue #36). The text carries the
 * numbers of pages and cards: whatever keeps its number keeps its card, with
 * its check and its history, and whatever is left out is deleted.
 */
export function BoardYamlDialog({ open, slug, onClose, onSaved }: { open: boolean; slug: string; onClose: () => void; onSaved: () => void }) {
  const { t } = useTranslation()
  const [text, setText] = useState('')
  const [loaded, setLoaded] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!open) return
    let dropped = false
    setLoaded(false)
    setError('')
    void api<Response>(`/boards/${slug}/export?ids=true`, { raw: true })
      .then(async (response) => {
        if (!response.ok) throw new Error(String(response.status))
        const body = await response.text()
        if (!dropped) {
          setText(body)
          setLoaded(true)
        }
      })
      .catch(() => {
        if (!dropped) setError(t('errors.network'))
      })
    return () => {
      dropped = true
    }
  }, [open, slug, t])

  const save = () => {
    setSaving(true)
    setError('')
    void put(`/boards/${slug}/yaml`, { yaml_text: text })
      .then(() => {
        onSaved()
        onClose()
      })
      .catch((failure) => setError(failure instanceof ApiError ? failure.message : t('errors.network')))
      .finally(() => setSaving(false))
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      title={t('board.editYaml')}
      footer={
        <>
          <button className="btn" onClick={onClose}>
            {t('common.cancel')}
          </button>
          <button className="btn btn-accent" onClick={save} disabled={!loaded || saving || !text.trim()}>
            {t('common.save')}
          </button>
        </>
      }
    >
      <p className="text-xs text-muted mb-2">{t('board.editYamlHelp')}</p>
      <textarea
        className="input font-mono text-xs w-full"
        rows={22}
        spellCheck={false}
        aria-label={t('board.editYaml')}
        value={text}
        disabled={!loaded}
        onChange={(e) => setText(e.target.value)}
      />
      {error && (
        <p className="text-xs text-bad mt-2" role="alert">
          {error}
        </p>
      )}
    </Dialog>
  )
}
