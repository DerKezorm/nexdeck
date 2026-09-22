/**
 * Ready-made boards. A tile per template with a sketch of its first page; the
 * chosen one asks which connection fills each of its slots, draws the board
 * as it will come out, and makes it in one call.
 *
 * A slot can take several services, "Jellyfin, Plex or Emby", and offers
 * every connection of any of them. Leaving one out takes its cards along; the
 * sketch shows that before anything is made, holes closed as the server will
 * close them.
 */
import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'

import { ApiError, get, post } from '../api/client'
import { tAdapter } from '../i18n/texts'
import { closeGaps } from '../lib/arranging'
import { useAuth } from '../stores/auth'
import { ServiceIcon } from './ServiceIcon'
import { Field, Select } from './ui'

export interface TemplateSummary {
  id: string
  name: string
  description: string
  icon: string
  columns: number
  pages: number
  cards: number
  slots: { name: string; kinds: { kind: string; label: string; icon: string }[]; cards: number }[]
  sketch: { slot: string | null; at: [number, number, number, number] }[]
  words: string[]
}

interface TemplateDetail extends TemplateSummary {
  choices: Record<string, { id: number; name: string; kind: string; demo: boolean }[]>
}

const LEAVE_OUT = ''

/** The first page as rectangles: cards of a slot in the accent, the rest plain; left-out slots gone, holes closed. */
export function Sketch({ template, without = [] }: { template: TemplateSummary; without?: string[] }) {
  const cards = useMemo(() => {
    const kept = template.sketch.map((card, index) => ({ ...card, i: String(index) })).filter((card) => !card.slot || !without.includes(card.slot))
    const placed = closeGaps(kept.map(({ i, at: [x, y, w, h] }) => ({ i, x, y, w, h })))
    return placed.map((spot) => ({ ...spot, slot: kept.find((card) => card.i === spot.i)?.slot ?? null }))
  }, [template, without])
  const rows = Math.max(1, ...cards.map((card) => card.y + card.h))
  return (
    <svg viewBox={`0 0 ${template.columns} ${rows}`} preserveAspectRatio="none" className="w-full h-full" aria-hidden="true">
      {cards.map((card) => (
        <rect
          key={card.i}
          x={card.x + 0.15}
          y={card.y + 0.15}
          width={card.w - 0.3}
          height={card.h - 0.3}
          rx={0.35}
          className={card.slot ? 'fill-accent/35 stroke-accent/60' : 'fill-faint/20 stroke-faint/40'}
          strokeWidth={0.08}
          vectorEffect="non-scaling-stroke"
        />
      ))}
    </svg>
  )
}

export function TemplatePicker() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const admin = useAuth((state) => state.user?.role === 'admin')
  const list = useQuery({ queryKey: ['templates'], queryFn: () => get<TemplateSummary[]>('/templates') })
  const [chosen, setChosen] = useState<string | null>(null)
  const detail = useQuery({ queryKey: ['templates', chosen], queryFn: () => get<TemplateDetail>(`/templates/${chosen}`), enabled: chosen !== null })
  const [name, setName] = useState('')
  const [slots, setSlots] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  // A fresh choice starts from the template's name in this language and, for
  // every slot, the first connection that fits: the usual case is one press.
  useEffect(() => {
    if (!detail.data) return
    setName(tAdapter(detail.data.name))
    setSlots(Object.fromEntries(detail.data.slots.map((slot) => [slot.name, String(detail.data.choices[slot.name]?.[0]?.id ?? LEAVE_OUT)])))
    setError('')
  }, [detail.data])

  const leftOut = detail.data ? detail.data.slots.filter((slot) => (slots[slot.name] ?? LEAVE_OUT) === LEAVE_OUT).map((slot) => slot.name) : []
  const keptCards = detail.data ? detail.data.cards - detail.data.slots.filter((slot) => leftOut.includes(slot.name)).reduce((sum, slot) => sum + slot.cards, 0) : 0

  const create = () => {
    if (!detail.data) return
    setBusy(true)
    setError('')
    post<{ slug: string }>(`/templates/${detail.data.id}`, {
      name: name.trim() || null,
      slots: Object.fromEntries(Object.entries(slots).map(([slot, id]) => [slot, id === LEAVE_OUT ? null : Number(id)])),
      // The template's words in this language, so the cards come out the way a card from the library would.
      texts: Object.fromEntries(detail.data.words.map((word) => [word, tAdapter(word)])),
    })
      .then((board) => navigate(`/b/${board.slug}`))
      .catch((failure) => setError(failure instanceof ApiError ? failure.message : t('errors.network')))
      .finally(() => setBusy(false))
  }

  if (list.isError) return <p className="text-sm text-bad">{t('errors.network')}</p>

  return (
    <div>
      <ul className="grid gap-3 sm:grid-cols-2">
        {(list.data ?? []).map((template) => (
          <li key={template.id}>
            <button
              type="button"
              aria-pressed={chosen === template.id}
              onClick={() => setChosen(template.id)}
              className={`w-full h-full text-left rounded-xl border p-3 flex gap-3 transition-colors ${chosen === template.id ? 'border-accent bg-accent-soft' : 'border-line hover:bg-surface-hover'}`}
            >
              <span className="flex-none w-24 h-16 rounded-lg bg-surface/60 p-1">
                <Sketch template={template} />
              </span>
              <span className="min-w-0">
                <span className="flex items-center gap-1.5 font-medium text-sm">
                  <ServiceIcon icon={`lucide:${template.icon}`} size={14} />
                  {tAdapter(template.name)}
                  <span className="text-[11px] text-faint font-normal">{t('templates.cards', { count: template.cards })}</span>
                </span>
                <span className="block text-xs text-muted mt-0.5 line-clamp-3">{tAdapter(template.description)}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>

      {detail.data && (
        <div className="mt-4 rounded-xl border border-line p-4">
          <div className="grid gap-4 md:grid-cols-[1fr_14rem]">
            <div>
              <Field label={t('templates.name')} htmlFor="template-name">
                <input id="template-name" className="input" value={name} maxLength={80} onChange={(event) => setName(event.target.value)} />
              </Field>
              {detail.data.slots.length > 0 && <p className="text-xs font-medium text-muted mb-2">{t('templates.slots')}</p>}
              {detail.data.slots.map((slot) => {
                const offered = detail.data.choices[slot.name] ?? []
                const services = slot.kinds.map((kind) => kind.label).join(', ')
                return (
                  <div key={slot.name} className="mb-3">
                    <label className="flex items-center gap-2 text-sm mb-1" htmlFor={`slot-${slot.name}`}>
                      <span className="flex -space-x-1">
                        {slot.kinds.map((kind) => (
                          <ServiceIcon key={kind.kind} icon={kind.icon} size={16} />
                        ))}
                      </span>
                      {tAdapter(slot.name)}
                      <span className="text-[11px] text-faint">{services}</span>
                    </label>
                    <Select
                      id={`slot-${slot.name}`}
                      value={slots[slot.name] ?? LEAVE_OUT}
                      onChange={(value) => setSlots((current) => ({ ...current, [slot.name]: value }))}
                      options={[
                        ...offered.map((choice) => ({ value: String(choice.id), label: choice.demo ? `${choice.name} (${t('templates.demo')})` : choice.name })),
                        { value: LEAVE_OUT, label: t('templates.leaveOut', { count: slot.cards }) },
                      ]}
                    />
                    {offered.length === 0 && (
                      <p className="text-[11px] text-muted mt-1">
                        {t('templates.none', { services })}{' '}
                        {admin && (
                          <Link className="text-accent underline" to="/system/integrations">
                            {t('templates.addConnection')}
                          </Link>
                        )}
                      </p>
                    )}
                  </div>
                )
              })}
            </div>
            <div>
              <p className="text-xs font-medium text-muted mb-2">{t('templates.preview')}</p>
              <div className="aspect-[4/3] rounded-lg bg-surface/60 p-2">
                <Sketch template={detail.data} without={leftOut} />
              </div>
              <p className="text-[11px] text-muted mt-2">{t('templates.willHave', { count: keptCards, columns: detail.data.columns })}</p>
            </div>
          </div>
          {error && (
            <p className="text-sm text-bad mt-2" role="alert">
              {error}
            </p>
          )}
          <button className="btn btn-accent mt-2" disabled={busy || keptCards === 0} onClick={create}>
            {t('templates.create')}
          </button>
        </div>
      )}
    </div>
  )
}
