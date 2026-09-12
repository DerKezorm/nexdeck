/**
 * Small primitives: sheet, dialog, confirm, switch, select, field, toast,
 * password input. Every switch carries an accessible name; a label pointing
 * at a div names nothing for a screen reader, so the switch takes
 * ``aria-labelledby``.
 */
import { Eye, EyeOff, X } from 'lucide-react'
import { cloneElement, isValidElement, useEffect, useId, useRef, useState, type ReactElement, type ReactNode, type RefObject } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'

/**
 * Hold the focus inside an open dialog, and give it back on the way out.
 *
 * ⚠️ Both Sheet and Dialog said ``aria-modal="true"``, which promises exactly
 * this, and neither did it. Tab walked straight out of the dialog into the
 * page behind it, where a screen reader then read a form the person could not
 * see; and closing dropped the focus onto the document, so the next Tab
 * started again from the top of the page instead of at the button that had
 * opened the thing.
 */
function useFocusTrap(open: boolean, container: RefObject<HTMLElement | null>): void {
  useEffect(() => {
    if (!open) return
    const cameFrom = document.activeElement as HTMLElement | null
    const inside = (): HTMLElement[] => {
      const found = container.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )
      return [...(found ?? [])].filter((element) => element.offsetParent !== null || element === document.activeElement)
    }
    // The first thing inside, so the keyboard starts where the eye does.
    const first = inside()[0]
    first?.focus()

    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') return
      const stops = inside()
      if (!stops.length) return
      const edge = event.shiftKey ? stops[0] : stops[stops.length - 1]
      if (document.activeElement === edge || !container.current?.contains(document.activeElement)) {
        event.preventDefault()
        ;(event.shiftKey ? stops[stops.length - 1] : stops[0]).focus()
      }
    }
    document.addEventListener('keydown', onKey, true)
    return () => {
      document.removeEventListener('keydown', onKey, true)
      // Back to whatever opened it, if that is still on the page.
      if (cameFrom?.isConnected) cameFrom.focus()
    }
  }, [open, container])
}

export function Sheet({ open, onClose, title, children, wide, footer }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; wide?: boolean; footer?: ReactNode }) {
  const { t } = useTranslation()
  const panel = useRef<HTMLElement>(null)
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])
  useFocusTrap(open, panel)
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} aria-hidden="true" />
      <aside ref={panel} className={`relative glass-strong h-full ${wide ? 'w-full max-w-[640px]' : 'w-full max-w-[420px]'} flex flex-col shadow-2xl rounded-none border-y-0 border-r-0`}>
        <header className="flex items-center gap-2 px-4 h-12 border-b border-line">
          <h2 className="font-semibold text-[15px] flex-1 truncate">{title}</h2>
          <button className="btn btn-icon btn-flat" onClick={onClose} aria-label={t('common.close')}>
            <X size={16} />
          </button>
        </header>
        <div className="flex-1 min-h-0 scroll p-4">{children}</div>
        {footer && <footer className="px-4 py-3 border-t border-line flex justify-end gap-2">{footer}</footer>}
      </aside>
    </div>
  )
}

export function Dialog({ open, onClose, title, children, footer, size = 'md' }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; footer?: ReactNode; size?: 'sm' | 'md' | 'lg' }) {
  const { t } = useTranslation()
  const panel = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    // A dialog may sit on top of a sheet. Escape closes the dialog alone: the
    // capture-phase listener runs first and stops the event before the sheet
    // sees it.
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.stopPropagation()
      onClose()
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [open, onClose])
  useFocusTrap(open, panel)
  if (!open) return null
  const width = { sm: 'max-w-sm', md: 'max-w-lg', lg: 'max-w-3xl' }[size]
  // Rendered at the body: a glass surface with backdrop-filter would otherwise
  // confine a fixed dialog to itself, and a dialog opened from a sheet would
  // be squeezed into the sheet's column.
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} aria-hidden="true" />
      <div ref={panel} className={`relative glass-strong rounded-2xl w-full ${width} max-h-[90vh] flex flex-col shadow-2xl`}>
        <header className="flex items-center gap-2 px-5 h-12 border-b border-line">
          <h2 className="font-semibold text-[15px] flex-1 truncate">{title}</h2>
          <button className="btn btn-icon btn-flat" onClick={onClose} aria-label={t('common.close')}>
            <X size={16} />
          </button>
        </header>
        <div className="flex-1 min-h-0 scroll p-5">{children}</div>
        {footer && <footer className="px-5 py-3 border-t border-line flex justify-end gap-2">{footer}</footer>}
      </div>
    </div>,
    document.body,
  )
}

export function Confirm({ open, title, body, danger, onCancel, onConfirm, confirmLabel, confirmDisabled, children }: { open: boolean; title: string; body?: string; danger?: boolean; onCancel: () => void; onConfirm: () => void; confirmLabel?: string; confirmDisabled?: boolean; children?: ReactNode }) {
  const { t } = useTranslation()
  return (
    <Dialog
      open={open}
      onClose={onCancel}
      title={title}
      size="sm"
      footer={
        <>
          <button className="btn" onClick={onCancel}>
            {t('common.cancel')}
          </button>
          <button className={`btn ${danger ? 'btn-danger' : 'btn-accent'}`} onClick={onConfirm} disabled={confirmDisabled} autoFocus={!confirmDisabled}>
            {confirmLabel ?? t('common.confirm')}
          </button>
        </>
      }
    >
      {body && <p className="text-sm text-muted">{body}</p>}
      {children}
    </Dialog>
  )
}

export function Switch({ checked, onChange, label, description, disabled }: { checked: boolean; onChange: (value: boolean) => void; label: string; description?: string; disabled?: boolean }) {
  const id = useId()
  return (
    <div className="flex items-start justify-between gap-4 py-2">
      <div className="min-w-0">
        <span id={id} className="text-sm font-medium block">
          {label}
        </span>
        {description && <span className="text-xs text-muted block">{description}</span>}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-labelledby={id}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative flex-none w-10 h-6 rounded-full transition-colors ${checked ? 'bg-accent' : 'bg-[color-mix(in_srgb,var(--nd-text)_18%,transparent)]'} disabled:opacity-50`}
      >
        <span className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white shadow transition-transform ${checked ? 'translate-x-4' : ''}`} />
      </button>
    </div>
  )
}

export function Field({ label, help, children, htmlFor, required }: { label: string; help?: string; children: ReactNode; htmlFor?: string; required?: boolean }) {
  const fallback = useId()
  const forId = htmlFor ?? fallback
  const helpId = `${forId}-help`
  return (
    <div className="mb-3">
      <label htmlFor={forId} className="block text-xs font-medium text-muted mb-1">
        {label}
        {required && <span className="text-bad ml-0.5">*</span>}
      </label>
      {/* ⚠️ The help text is a sibling of the control, so nothing tied the two
          together: a screen reader read the label and stopped, and the sentence
          explaining what the field wants was never spoken. A child that carries
          no id of its own gets one here, along with the field's own label, so
          a bare `<input>` inside a Field is named without every caller having
          to remember. */}
      {isValidElement(children) && !(children.props as { id?: string }).id
        ? cloneElement(children as ReactElement<Record<string, unknown>>, {
            id: forId,
            'aria-describedby': help ? helpId : undefined,
          })
        : children}
      {help && (
        <p id={helpId} className="text-[11px] text-faint mt-1">
          {help}
        </p>
      )}
    </div>
  )
}

export function Select({ value, onChange, options, id, className = '', disabled }: { value: string; onChange: (value: string) => void; options: { value: string; label: string }[]; id?: string; className?: string; disabled?: boolean }) {
  return (
    <select id={id} className={`input ${className}`} value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)}>
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  )
}

/** A password field with an eye: what was typed can be checked before it is sent. */
export function PasswordInput({
  id,
  value,
  onChange,
  autoComplete = 'current-password',
  placeholder,
  autoFocus,
  className = '',
}: {
  id?: string
  value: string
  onChange: (value: string) => void
  autoComplete?: 'current-password' | 'new-password'
  placeholder?: string
  autoFocus?: boolean
  className?: string
}) {
  const { t } = useTranslation()
  const [shown, setShown] = useState(false)
  return (
    <div className={`relative ${className}`}>
      <input
        id={id}
        className="input pr-10"
        type={shown ? 'text' : 'password'}
        autoComplete={autoComplete}
        placeholder={placeholder}
        autoFocus={autoFocus}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
      <button
        type="button"
        className="btn btn-icon absolute right-1 top-1/2 -translate-y-1/2 h-7 w-7 btn-flat text-muted"
        onClick={() => setShown((current) => !current)}
        aria-label={shown ? t('auth.hidePassword') : t('auth.showPassword')}
        title={shown ? t('auth.hidePassword') : t('auth.showPassword')}
      >
        {shown ? <EyeOff size={15} /> : <Eye size={15} />}
      </button>
    </div>
  )
}

export function Toast({ children, onClose, level = 'info' }: { children: ReactNode; onClose: () => void; level?: 'info' | 'warn' | 'error' | 'ok' }) {
  const colour = { info: 'border-accent/50', warn: 'border-warn/60', error: 'border-bad/60', ok: 'border-ok/60' }[level]
  const timer = useRef<number>(0)
  useEffect(() => {
    timer.current = window.setTimeout(onClose, 5000)
    return () => window.clearTimeout(timer.current)
  }, [onClose])
  const { t } = useTranslation()
  // ⚠️ The bubble lets clicks through. It sits in the bottom right corner
  // for five seconds, and that is where a sheet keeps its Save button: a press
  // meant for Save landed on the message instead, and the person pressed again
  // and wondered. Nothing in here is clickable but the close button, which
  // takes its pointer events back. Measured on 10.09.2026, where one run of
  // the end-to-end suite spent a full minute retrying a single click against a
  // message that kept renewing itself.
  return (
    <div className={`fixed bottom-20 md:bottom-6 right-4 z-50 pointer-events-none glass-strong rounded-xl pl-4 pr-10 py-3 text-sm max-w-sm border ${colour} shadow-2xl rise`} role="status">
      {children}
      {/* ⚠️ Every window gets one visible way out. This one had exactly one
          exit, the timer, so a message that mattered could not be dismissed
          and a message that did not could not be got rid of. */}
      <button
        className="absolute top-2 right-2 h-6 w-6 rounded-md grid place-items-center text-muted hover:text-fg hover:bg-white/10 pointer-events-auto"
        onClick={onClose}
        aria-label={t('common.close')}
      >
        <X size={14} />
      </button>
    </div>
  )
}

export function EmptyState({ title, body, action }: { title: string; body?: string; action?: ReactNode }) {
  return (
    <div className="glass rounded-2xl p-8 text-center max-w-md mx-auto">
      <h3 className="font-semibold">{title}</h3>
      {body && <p className="text-sm text-muted mt-1">{body}</p>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  )
}

export function Spinner() {
  return <span className="inline-block w-4 h-4 border-2 border-accent border-t-transparent rounded-full animate-spin" aria-label="Loading" />
}
