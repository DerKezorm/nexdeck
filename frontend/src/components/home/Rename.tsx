import { Pencil } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

/** How long a name of the page's own may be; the server cuts at the same length (``MAX_NAME``). */
export const MAX_LABEL = 80

interface Props {
  /** The page's own name, empty for Home Assistant's. */
  label: string
  /** Home Assistant's name, shown while the field is empty and taken back with the button. */
  fallback: string
  onLabel: (label: string) => void
}

/**
 * The pencil beside an element while arranging: a name of the page's own
 * instead of Home Assistant's. Empty takes Home Assistant's again; a name of
 * its own stays when the device is renamed there.
 */
export function Rename({ label, fallback, onLabel }: Props) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [text, setText] = useState(label)
  const box = useRef<HTMLSpanElement>(null)
  // Closes as menus do: a press anywhere else.
  useEffect(() => {
    if (!open) return
    const away = (event: PointerEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('pointerdown', away)
    return () => document.removeEventListener('pointerdown', away)
  }, [open])
  const done = (value: string) => {
    setOpen(false)
    if (value !== label) onLabel(value)
  }
  return (
    <span ref={box} className="relative" data-element-tool>
      <button type="button" className={`btn btn-icon h-6 w-6 rounded-full glass-strong ${label ? 'text-accent' : ''}`} aria-label={t('homePage.rename')} title={t('homePage.rename')}
        aria-expanded={open} onClick={() => {
          setText(label)
          setOpen((now) => !now)
        }}>
        <Pencil size={12} />
      </button>
      {open && (
        <form className="absolute right-0 top-full mt-2 z-30 glass-strong rounded-xl p-2.5 shadow-2xl grid gap-2 w-64" data-rename
          onSubmit={(event) => {
            event.preventDefault()
            done(text.trim())
          }}>
          <input className="input" autoFocus value={text} maxLength={MAX_LABEL} placeholder={fallback} aria-label={t('homePage.rename')}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              event.stopPropagation()
              if (event.key === 'Escape') setOpen(false)
            }} />
          <span className="text-[11.5px] text-faint">{t('homePage.renameHint', { name: fallback })}</span>
          <span className="flex justify-end gap-1.5">
            {label && (
              <button type="button" className="btn btn-flat text-[12.5px]" onClick={() => done('')}>
                {t('homePage.useHaName')}
              </button>
            )}
            <button type="submit" className="btn btn-accent text-[12.5px]">{t('common.save')}</button>
          </span>
        </form>
      )}
    </span>
  )
}
