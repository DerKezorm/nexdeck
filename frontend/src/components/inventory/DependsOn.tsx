/**
 * "Runs on / needs" (roadmap M5), on a connection and on an app tile: what it
 * was found to run on, what was set by hand, and a list to add one. For
 * administrators; the inventory under System shows the whole of it.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { X } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, del, get, post } from '../../api/client'
import { childrenOf, type Inventory } from '../../lib/inventory'
import { useLazyTexts } from '../../lib/lazyTexts'

export function DependsOn({ subject }: { subject: string }) {
  const ready = useLazyTexts('inventory')
  return ready ? <Field subject={subject} /> : null
}

function Field({ subject }: { subject: string }) {
  const { t } = useTranslation()
  const client = useQueryClient()
  const found = useQuery({ queryKey: ['inventory'], queryFn: () => get<Inventory>('/inventory') })
  const [failure, setFailure] = useState('')
  const inventory = found.data
  // ⚠️ Anything but an inventory (an older server, an error page) leaves the field out, never the whole sheet.
  if (!inventory || !Array.isArray(inventory.nodes) || !Array.isArray(inventory.relations)) return null
  const byRef = new Map(inventory.nodes.map((node) => [node.ref, node]))
  const mine = inventory.relations.filter((one) => one.child === subject && one.state === 'on')
  // Not itself, not what it already runs on, and nothing that runs on it: that would be a circle.
  const below = new Set<string>()
  const collect = (ref: string) => {
    for (const child of childrenOf(inventory, ref)) {
      if (!below.has(child.node.ref)) {
        below.add(child.node.ref)
        collect(child.node.ref)
      }
    }
  }
  collect(subject)
  const choices = inventory.nodes.filter((node) => node.ref !== subject && !below.has(node.ref) && !mine.some((one) => one.parent === node.ref))
  const changed = async (work: () => Promise<unknown>) => {
    setFailure('')
    try {
      await work()
      await client.invalidateQueries({ queryKey: ['inventory'] })
    } catch (error) {
      setFailure(error instanceof ApiError ? error.message : t('errors.network'))
    }
  }
  return (
    <div className="mb-3" data-testid="depends-on">
      <div className="mb-1 text-xs font-medium text-muted">{t('inventory.runsOn')}</div>
      <div className="flex flex-wrap items-center gap-1.5">
        {mine.length === 0 && <span className="text-[12px] text-faint">{t('inventory.nothing')}</span>}
        {mine.map((one) => {
          const name = byRef.get(one.parent)?.name ?? one.parent
          return (
            <span key={one.id} className="chip inline-flex items-center gap-1">
              {name}
              <span className="text-faint">· {t(`inventory.origin.${one.origin}`)}</span>
              <button type="button" className="text-muted hover:text-bad" aria-label={t('inventory.remove', { name })} onClick={() => void changed(() => del(`/relations/${one.id}`))}>
                <X size={11} />
              </button>
            </span>
          )
        })}
        <select
          className="input h-8 w-auto py-0 text-[12px]"
          value=""
          aria-label={t('inventory.pick')}
          onChange={(event) => {
            const parent = event.target.value
            if (parent) void changed(() => post('/relations', { child: subject, parent }))
          }}
        >
          <option value="">{t('inventory.pick')}</option>
          {choices.map((node) => (
            <option key={node.ref} value={node.ref}>
              {node.name} · {t(`inventory.kind.${node.kind}`)}
            </option>
          ))}
        </select>
      </div>
      <p className="mt-1 text-[11px] text-faint">{t('inventory.runsOnHelp')}</p>
      {failure && <p className="mt-1 text-[11px] text-bad" role="alert">{failure}</p>}
    </div>
  )
}
