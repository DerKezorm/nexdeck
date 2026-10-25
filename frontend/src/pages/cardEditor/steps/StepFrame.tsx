import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import type { EditorStep } from '../store'

/** The frame of one step of the editor: its heading, a line on what it is for, and its fields. */
export function StepFrame({ step, children }: { step: EditorStep; children?: ReactNode }) {
  const { t } = useTranslation()
  return (
    <section className="glass rounded-2xl p-4 sm:p-5 min-w-0" aria-labelledby={`card-step-${step}`}>
      <h2 id={`card-step-${step}`} className="font-semibold text-[15px] break-words hyphens-auto">
        {t(`editor.steps.${step}`)}
      </h2>
      <p className="text-sm text-muted mt-1 break-words hyphens-auto">{t(`editor.lead.${step}`)}</p>
      {children && <div className="mt-4 grid gap-4 min-w-0">{children}</div>}
    </section>
  )
}
