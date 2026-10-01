import { Copy, Download } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { boardCanvas, fileName, framed, painted, type Frame } from '../lib/boardPicture'
import { useShowcase } from '../lib/showcase'
import { Dialog, Select, Switch } from './ui'

/**
 * Save the board as a picture: a preview of what will be saved, a frame to
 * choose, the note in the corner, and showcase mode for the moment the
 * picture is taken, on by default, since a picture is taken to be shown.
 */
export function PictureDialog({ open, onClose, boardName }: { open: boolean; onClose: () => void; boardName: string }) {
  const { t } = useTranslation()
  const [frame, setFrame] = useState<Frame>('gradient')
  const [note, setNote] = useState(true)
  const [showcase, setShowcase] = useState(true)
  const [board, setBoard] = useState<HTMLCanvasElement | null>(null)
  const [preview, setPreview] = useState('')
  const [state, setState] = useState<'drawing' | 'ready' | 'failed'>('drawing')
  const [copied, setCopied] = useState(false)
  const result = useRef<HTMLCanvasElement | null>(null)

  // The board is drawn once per opening, and again only when showcase mode
  // for the picture is switched: frame and note are put on afterwards.
  useEffect(() => {
    if (!open) return
    let current = true
    setState('drawing')
    setBoard(null)
    const take = async () => {
      const page = document.querySelector<HTMLElement>('[data-board-page]')
      if (!page) throw new Error('no board on the page')
      const before = useShowcase.getState().on
      // Switched on for the picture only: the setting of the browser stays as it was.
      if (showcase !== before) useShowcase.setState({ on: showcase })
      try {
        await painted()
        return await boardCanvas(page)
      } finally {
        if (showcase !== before) useShowcase.setState({ on: before })
      }
    }
    take().then(
      (drawn) => {
        if (current) setBoard(drawn)
      },
      () => {
        if (current) setState('failed')
      },
    )
    return () => {
      current = false
    }
  }, [open, showcase])

  useEffect(() => {
    if (!board) return
    const picture = framed(board, { frame, note })
    result.current = picture
    setPreview(picture.toDataURL('image/png'))
    setState('ready')
  }, [board, frame, note])

  useEffect(() => {
    if (!open) {
      setPreview('')
      setCopied(false)
      result.current = null
    }
  }, [open])

  const save = () => {
    const picture = result.current
    if (!picture) return
    picture.toBlob((blob) => {
      if (!blob) return
      const link = document.createElement('a')
      link.href = URL.createObjectURL(blob)
      link.download = fileName(boardName)
      link.click()
      window.setTimeout(() => URL.revokeObjectURL(link.href), 10_000)
    }, 'image/png')
  }
  // Copying a picture needs ClipboardItem, which some browsers lack and which
  // only works on https or localhost. Without it the button is not offered.
  const canCopy = typeof window !== 'undefined' && 'ClipboardItem' in window && Boolean(navigator.clipboard?.write)
  const copy = () => {
    const picture = result.current
    if (!picture) return
    picture.toBlob((blob) => {
      if (!blob) return
      void navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]).then(() => setCopied(true), () => setCopied(false))
    }, 'image/png')
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={t('picture.title')}
      size="lg"
      footer={
        <>
          {canCopy && (
            <button className="btn" onClick={copy} disabled={state !== 'ready'}>
              <Copy size={14} />
              {copied ? t('picture.copied') : t('picture.copy')}
            </button>
          )}
          <button className="btn btn-accent" onClick={save} disabled={state !== 'ready'}>
            <Download size={14} />
            {t('picture.save')}
          </button>
        </>
      }
    >
      <p className="text-xs text-muted mb-3">{t('picture.help')}</p>
      <div className="rounded-xl border border-line bg-bg/40 min-h-48 grid place-items-center overflow-hidden" aria-live="polite">
        {state === 'failed' ? (
          <p className="text-sm text-bad p-6">{t('picture.failed')}</p>
        ) : preview && state === 'ready' ? (
          <img src={preview} alt={t('picture.preview')} className="max-h-[52vh] w-auto max-w-full" data-testid="picture-preview" />
        ) : (
          <p className="text-sm text-muted p-6">{t('picture.drawing')}</p>
        )}
      </div>
      <div className="grid sm:grid-cols-2 gap-x-6 gap-y-1 mt-4 items-start">
        <div>
          <label className="block text-xs font-medium text-muted mb-1.5" htmlFor="picture-frame">
            {t('picture.frame')}
          </label>
          <Select id="picture-frame" value={frame} onChange={(value) => setFrame(value as Frame)} options={(['gradient', 'accent', 'none'] as const).map((value) => ({ value, label: t(`picture.frames.${value}`) }))} />
        </div>
        <div>
          <Switch checked={note} onChange={setNote} label={t('picture.note')} />
          <Switch checked={showcase} onChange={setShowcase} label={t('picture.showcase')} description={t('picture.showcaseHelp')} />
        </div>
      </div>
    </Dialog>
  )
}
