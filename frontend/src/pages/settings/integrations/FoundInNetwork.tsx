/**
 * "Found in your network": services the inventory knows that are not connected yet.
 *
 * Read from what nexdeck has already found (``GET /integrations/found``), so
 * opening the catalog asks nothing of the network. Without an inventory, or
 * with nothing found, the section is not there at all.
 */
import { useQuery } from '@tanstack/react-query'
import { Radar } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, del, get, post } from '../../../api/client'
import { ServiceIcon } from '../../../components/ServiceIcon'
import { timeAgo } from '../../../lib/format'
import { matches } from './own'

export interface FoundService {
  key: string
  kind: string
  label: string
  icon: string
  beta: boolean
  thing: 'container' | 'guest'
  name: string
  engine: string
  /** Where it answers, as far as the inventory knows; empty when the host is not known. */
  address: string
}

interface FoundAnswer {
  found: FoundService[]
  ignored: number
  looked_at: string | null
}

function Card({ service, onConnect, onIgnore }: { service: FoundService; onConnect: (kind: string, address: string) => void; onIgnore: (key: string) => void }) {
  const { t } = useTranslation()
  const [address, setAddress] = useState(service.address)
  const where = t(service.thing === 'guest' ? 'settings.integrations.found.guest' : 'settings.integrations.found.container', { name: service.name, engine: service.engine })
  return (
    <div className="flex flex-col gap-2 min-w-0 rounded-xl border border-line bg-surface px-3 py-2.5 max-md:flex-[0_0_82%] max-md:snap-start">
      <div className="flex items-center gap-2.5 min-w-0">
        <ServiceIcon icon={service.icon} size={30} />
        <div className="min-w-0">
          <div className="text-[13.5px] font-semibold">{service.label}</div>
          <div className="text-xs text-muted truncate" title={where}>
            {where}
          </div>
        </div>
      </div>
      <input
        className="input !h-[30px] !rounded-lg !px-2.5 num text-[12.5px]"
        value={address}
        placeholder="http://192.0.2.10:8080"
        spellCheck={false}
        aria-label={t('settings.integrations.found.address', { name: service.label })}
        onChange={(event) => setAddress(event.target.value)}
      />
      <div className="flex gap-1.5">
        <button type="button" className="btn btn-accent btn-xs flex-1 !h-7" onClick={() => onConnect(service.kind, address.trim())} aria-label={t('settings.integrations.found.connectOne', { name: service.label })}>
          {t('settings.integrations.found.connect')}
        </button>
        <button type="button" className="btn btn-flat btn-xs !h-7" onClick={() => onIgnore(service.key)} aria-label={t('settings.integrations.found.ignoreOne', { name: service.label })}>
          {t('settings.integrations.found.ignore')}
        </button>
      </div>
    </div>
  )
}

export function FoundInNetwork({ query, onConnect }: { query: string; onConnect: (kind: string, address: string) => void }) {
  const { t } = useTranslation()
  const answer = useQuery({ queryKey: ['integrations-found'], queryFn: () => get<FoundAnswer>('/integrations/found'), staleTime: 60_000 })
  const [failed, setFailed] = useState('')
  const data = answer.data
  if (!data?.found) return null
  const shown = data.found.filter((service) => matches(`${service.label} ${service.kind} ${service.name} ${service.engine}`, query))
  // Nothing found, or the search passes them by: the section is not there. Ignored ones are offered back only while nothing is typed.
  if (!shown.length && (query || !data.ignored)) return null

  const act = (done: Promise<unknown>) => {
    setFailed('')
    done.then(() => answer.refetch()).catch((failure) => setFailed(failure instanceof ApiError ? failure.message : t('errors.network')))
  }
  return (
    <section className="rounded-2xl border border-accent/30 bg-accent/[0.06] p-3.5 max-md:p-3 mb-[22px] max-md:mb-[18px]" aria-label={t('settings.integrations.found.title')}>
      <div className="flex items-center gap-2 mb-2.5">
        <Radar size={15} className="text-accent" />
        <h3 className="text-sm font-semibold">{t('settings.integrations.found.title')}</h3>
        <span className="ml-auto text-xs text-faint max-md:hidden">
          {t('settings.integrations.found.help')}
          {data.looked_at && ` · ${t('settings.integrations.found.looked', { ago: timeAgo(Date.parse(data.looked_at) / 1000) })}`}
        </span>
      </div>
      {shown.length > 0 && (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(250px,1fr))] gap-2 max-md:flex max-md:overflow-x-auto max-md:snap-x max-md:snap-mandatory scrollbar-none max-md:-mx-3 max-md:px-3">
          {shown.map((service) => (
            <Card key={service.key} service={service} onConnect={onConnect} onIgnore={(key) => act(post('/integrations/found/ignore', { key }))} />
          ))}
        </div>
      )}
      {data.ignored > 0 && !query && (
        <p className={`text-[12.5px] text-muted ${shown.length ? 'mt-2.5' : ''}`}>
          {t('settings.integrations.found.ignored', { count: data.ignored })}{' '}
          <button type="button" className="text-accent hover:underline" onClick={() => act(del('/integrations/found/ignore'))}>
            {t('settings.integrations.found.showAgain')}
          </button>
        </p>
      )}
      {failed && (
        <p className="text-xs text-bad mt-2" role="alert">
          {failed}
        </p>
      )}
    </section>
  )
}
