import { useQuery } from '@tanstack/react-query'
import { Check } from 'lucide-react'
import { useEffect } from 'react'
import { useTranslation } from 'react-i18next'

import { get } from '../../../api/client'
import type { CardSource } from '../../../lib/customCards'
import { runProbe, useConnections } from '../connections'
import { useCardEditor } from '../store'
import { DataStep } from './DataStep'
import { DisplayStep } from './DisplayStep'
import { FinishStep } from './FinishStep'
import { GUIDED_STEPS, type GuidedStep } from './guided'
import { ServiceStep } from './ServiceStep'
import { shapeNow, useGuidedAnswer } from './useGuided'

/** Which steps can be opened: Data once there is a service, Display and Finish once the card has a display (U2). */
export function useReachable(): Record<GuidedStep, boolean> {
  const { kind } = useGuidedAnswer()
  const shaped = useCardEditor((state) => state.shapedPath !== null && state.pendingShape === null)
  return { service: true, data: Boolean(kind), display: Boolean(kind) && shaped, finish: Boolean(kind) && shaped }
}

/** Back and Next under a step; Next only while the next step can be opened. */
export function StepNav({ children }: { children?: React.ReactNode }) {
  const { t } = useTranslation()
  const step = useCardEditor((state) => state.guidedStep)
  const reach = useReachable()
  const index = GUIDED_STEPS.indexOf(step)
  const next = GUIDED_STEPS[index + 1]
  const go = (to: GuidedStep) => {
    useCardEditor.getState().setGuidedStep(to)
    window.scrollTo?.({ top: 0, behavior: 'smooth' })
  }
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3 min-w-0">
      {index > 0 ? (
        <button type="button" className="btn" onClick={() => go(GUIDED_STEPS[index - 1])}>
          {t('editor.guided.back')}
        </button>
      ) : (
        <span />
      )}
      {children ??
        (next && (
          <button type="button" className="btn btn-accent" disabled={!reach[next]} onClick={() => go(next)}>
            {t('editor.guided.next')}
          </button>
        ))}
    </div>
  )
}

/** The frame of a step of the guided way: its question as the heading, one line below it, and its parts. */
export function GuidedFrame({ id, title, lead, children }: { id: GuidedStep; title: string; lead: string; children: React.ReactNode }) {
  return (
    <section className="glass rounded-2xl p-4 sm:p-5 min-w-0 grid gap-4" aria-labelledby={`card-guided-${id}`}>
      <div className="grid gap-1 min-w-0">
        <h2 id={`card-guided-${id}`} className="font-semibold text-[17px] break-words hyphens-auto">
          {title}
        </h2>
        <p className="text-sm text-muted break-words hyphens-auto">{lead}</p>
      </div>
      {children}
    </section>
  )
}

const PAGES: Record<GuidedStep, (props: { onSave: () => void; canSave: boolean; busy: boolean }) => React.ReactElement | null> = {
  service: ServiceStep,
  data: DataStep,
  display: DisplayStep,
  finish: FinishStep,
}

/**
 * The guided way (U1, U2): Service, Data, Display and Finish, one after the other, in words without the language of
 * programmers (U10). It edits the same document as "All settings" and the YAML view.
 *
 * It asks the service as soon as there is something to ask, and makes the card's display from the first answer to a
 * newly picked path.
 */
export function GuidedWay(props: { onSave: () => void; canSave: boolean; busy: boolean }) {
  const { t } = useTranslation()
  const step = useCardEditor((state) => state.guidedStep)
  const pending = useCardEditor((state) => state.pendingShape)
  const shaped = useCardEditor((state) => state.shapedPath !== null && state.pendingShape === null)
  const reach = useReachable()
  const { kind, requestId, path, probe, tree, suggestion } = useGuidedAnswer()
  const { chosen } = useConnections()
  const sources = useQuery({ queryKey: ['cards-sources'], queryFn: () => get<CardSource[]>('/cards/sources'), staleTime: 60_000 })
  const serviceName = sources.data?.find((one) => one.kind === kind)?.label ?? kind ?? ''

  // A card that has its display asks its path once a step needs the answer, so that the table is there. A path being
  // typed is asked with "Ask" only.
  const needsAnswer = (step === 'data' || step === 'display') && shaped
  useEffect(() => {
    if (!needsAnswer || !chosen || !requestId || !path || path === '/' || probe) return
    void runProbe(requestId, chosen.id, path)
  }, [needsAnswer, chosen, requestId, path, probe])

  // The first answer to a path just picked makes the card's display (U6).
  useEffect(() => {
    if (pending && tree && path === pending) shapeNow(tree, suggestion, kind, serviceName)
  }, [pending, tree, path, suggestion, kind, serviceName])

  // A step that cannot be opened any more (the service changed) gives way to the last one that can.
  useEffect(() => {
    if (!reach[step]) useCardEditor.getState().setGuidedStep([...GUIDED_STEPS].reverse().find((one) => reach[one]) ?? 'service')
  }, [reach, step])

  const Page = PAGES[step]
  const current = GUIDED_STEPS.indexOf(step)
  return (
    <div className="grid gap-4 min-w-0">
      <nav aria-label={t('editor.steps.label')}>
        <ol className="flex flex-wrap gap-1.5">
          {GUIDED_STEPS.map((one, index) => {
            const done = index < current && reach[GUIDED_STEPS[index + 1]]
            const name = t(`editor.guided.steps.${one}`)
            return (
              <li key={one}>
                <button
                  type="button"
                  aria-current={step === one ? 'step' : undefined}
                  disabled={!reach[one]}
                  aria-label={done ? t('editor.guided.stepDone', { number: index + 1, name }) : t('editor.stepNumber', { number: index + 1, name })}
                  className={`h-9 pl-1.5 pr-3.5 rounded-full border inline-flex items-center gap-2 text-sm break-words hyphens-auto disabled:opacity-50 disabled:cursor-not-allowed ${step === one ? 'border-accent bg-accent-soft text-ink font-medium' : 'border-line text-muted hover:text-ink hover:bg-surface-hover'}`}
                  onClick={() => useCardEditor.getState().setGuidedStep(one)}
                >
                  <span
                    className={`w-6 h-6 rounded-full grid place-items-center text-[11.5px] font-semibold border ${step === one ? 'bg-accent text-on-accent border-accent' : done ? 'bg-ok text-on-accent border-ok' : 'bg-surface-hover border-line'}`}
                    aria-hidden="true"
                  >
                    {done ? <Check size={13} /> : index + 1}
                  </span>
                  {name}
                </button>
              </li>
            )
          })}
        </ol>
      </nav>
      <Page {...props} />
    </div>
  )
}
