import { useQuery } from '@tanstack/react-query'
import { ClipboardPaste, Plus } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { get } from '../../../api/client'
import type { Integration } from '../../../api/types'
import { ServiceIcon } from '../../../components/ServiceIcon'
import { deleteAt, setAt } from '../../../lib/cardDocument'
import type { CardSource } from '../../../lib/customCards'
import { useConnections } from '../connections'
import { useCardEditor } from '../store'
import { GuidedFrame, StepNav } from './GuidedWay'
import { writeShape } from './guided'

/**
 * Step 1, Service (U3): the connections a card can read from, as tiles with their logo and name. A tile sets the kind
 * of the card (`requires`, replaced, never added to) and the connection the answers and the preview come from, which
 * the card itself never names (decision 4). Another kind of service takes the card back to nothing chosen.
 */
export function ServiceStep() {
  const { t } = useTranslation()
  const sources = useQuery({ queryKey: ['cards-sources'], queryFn: () => get<CardSource[]>('/cards/sources'), staleTime: 60_000 })
  const integrations = useQuery({ queryKey: ['integrations'], queryFn: () => get<Integration[]>('/integrations') })
  const { kinds, chosen } = useConnections()
  const slug = useCardEditor((state) => state.slug)
  const readable = new Map((sources.data ?? []).map((one) => [one.kind, one]))
  const tiles = (integrations.data ?? []).filter((one) => one.enabled !== false && readable.has(one.kind))

  const pick = (one: Integration) => {
    const editor = useCardEditor.getState()
    const same = kinds.length === 1 && kinds[0] === one.kind
    if (!same) {
      editor.change((doc) => {
        setAt(doc, ['requires'], [one.kind])
        // What was read from another service means nothing here: back to one request that asks nothing yet.
        setAt(doc, ['requests'], [{ id: 'main', path: '/' }])
        deleteAt(doc, ['demo'])
        writeShape(doc, { form: 'value', number: { kind: 'field', path: '@' } })
      })
      useCardEditor.setState({ shapedPath: null, pendingShape: null })
    }
    editor.setIntegration(one.id)
    editor.setGuidedStep('data')
  }

  return (
    <GuidedFrame id="service" title={t('editor.guided.service.title')} lead={t('editor.guided.service.lead')}>
      {integrations.isSuccess && sources.isSuccess && !tiles.length && (
        <p className="rounded-xl border border-warn/40 px-3 py-2 text-sm break-words hyphens-auto" role="status" data-testid="card-no-connection">
          {t('editor.guided.service.none')}
        </p>
      )}
      <div className="grid gap-2.5 grid-cols-[repeat(auto-fill,minmax(170px,1fr))] min-w-0">
        {tiles.map((one) => {
          const pressed = chosen?.id === one.id && kinds.length === 1 && kinds[0] === one.kind
          return (
            <button
              key={one.id}
              type="button"
              aria-pressed={pressed}
              className={`text-left grid gap-1.5 rounded-2xl border p-3 min-w-0 ${pressed ? 'border-accent ring-[3px] ring-accent/20' : 'border-line hover:border-line-strong hover:bg-surface-hover'}`}
              onClick={() => pick(one)}
            >
              <span className="flex items-center gap-2.5 min-w-0">
                <ServiceIcon icon={one.icon || readable.get(one.kind)?.icon || one.kind} size={28} />
                <span className="font-semibold text-sm min-w-0 break-words hyphens-auto">{one.name}</span>
              </span>
              <small className="text-[12px] text-muted break-words hyphens-auto">{readable.get(one.kind)?.label ?? one.kind}</small>
            </button>
          )
        })}
      </div>
      <p className="text-[12px] text-faint flex flex-wrap items-center gap-x-2 gap-y-1 break-words hyphens-auto">
        <span>{t('editor.guided.service.missing')}</span>
        <Link className="text-accent font-medium inline-flex items-center gap-1" to="/system/integrations">
          <Plus size={13} /> {t('editor.guided.service.add')}
        </Link>
      </p>
      {slug === null && (
        <button
          type="button"
          className="btn btn-flat justify-self-start"
          onClick={() => useCardEditor.getState().open({ slug: null, text: '', base: null, saved: null, view: 'yaml' })}
        >
          <ClipboardPaste size={15} /> {t('editor.guided.service.paste')}
        </button>
      )}
      <StepNav />
    </GuidedFrame>
  )
}
