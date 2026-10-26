import { useQuery } from '@tanstack/react-query'
import { useId, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { ApiError, get, post } from '../../../api/client'
import type { BoardSummary } from '../../../api/types'
import { Spinner } from '../../../components/ui'
import { readAt, readIn, setAt } from '../../../lib/cardDocument'
import { pickText, type CardText } from '../../../lib/cardText'
import type { CardForm } from '../../../lib/customCards'
import { useConnections } from '../connections'
import { DemoDialog } from '../DemoDialog'
import { everyText } from '../steps/SourceStep'
import { languageName } from '../steps/TextsStep'
import { useCardEditor } from '../store'
import { slugFrom } from '../templates'
import { OFFERED_LANGUAGES, textIn, writeText, type TextSpot } from '../texts'
import { useLanguage } from './DisplayStep'
import { GUIDED_EVERY, thresholdsOf, writeLocal, writeThresholds } from './guided'
import { GuidedFrame, StepNav } from './GuidedWay'

const LABEL = 'text-[12px] font-medium text-muted break-words hyphens-auto'
const NAME: TextSpot = { id: 'name', path: ['name'], label: { key: 'editor.texts.name' }, required: true }

/** A threshold typed: a number, or nothing for "never". */
function thresholdOf(text: string): number | null {
  const trimmed = text.trim().replace(',', '.')
  return trimmed !== '' && Number.isFinite(Number(trimmed)) ? Number(trimmed) : null
}

/** "Saved. Put it on a board right away?" (U8): a board and a page this account may change, and the card goes there. */
function PutOnBoard() {
  const { t, i18n } = useTranslation()
  const ids = useId()
  const card = useCardEditor((state) => state.card ?? state.lastValid?.card ?? null)
  const slug = useCardEditor((state) => state.slug)
  const { chosen } = useConnections()
  const boards = useQuery({ queryKey: ['boards'], queryFn: () => get<BoardSummary[]>('/boards') })
  const mine = (boards.data ?? []).filter((one) => one.permission === 'owner' || one.permission === 'edit')
  const [boardId, setBoardId] = useState<number | null>(null)
  const [pageId, setPageId] = useState<number | null>(null)
  const [state, setState] = useState<{ status: 'idle' | 'busy' | 'later' } | { status: 'placed'; board: BoardSummary } | { status: 'failed'; message: string }>({ status: 'idle' })
  const board = mine.find((one) => one.id === boardId) ?? mine[0]
  const page = board?.pages.find((one) => one.id === pageId) ?? board?.pages[0]
  if (state.status === 'later' || !card || !slug) return null

  const place = async () => {
    if (!board || !page) return
    setState({ status: 'busy' })
    try {
      // As the library places a custom card: its form as the kind, its short name as the option `card`.
      await post(`/pages/${page.id}/widgets`, {
        kind: `custom.${readAt(card, ['form']) as CardForm}`,
        title: pickText(readAt(card, ['name']) as CardText, i18n.language),
        integration_id: chosen?.id ?? null,
        options: { card: slug },
      })
      setState({ status: 'placed', board })
    } catch (failure) {
      setState({ status: 'failed', message: failure instanceof ApiError ? failure.message : t('errors.network') })
    }
  }

  return (
    <div className="grid gap-2.5 rounded-2xl border border-ok/60 bg-ok/10 p-3.5 min-w-0" role="status" data-testid="card-guided-saved">
      <strong>{t('editor.guided.finish.savedTitle')}</strong>
      {state.status === 'placed' ? (
        <p className="text-sm flex flex-wrap items-center gap-2 break-words hyphens-auto">
          {t('editor.guided.finish.placed', { board: state.board.name })}
          <Link className="text-accent font-medium" to={`/b/${state.board.slug}`}>
            {t('editor.guided.finish.openBoard')}
          </Link>
        </p>
      ) : !mine.length && boards.isSuccess ? (
        <p className="text-sm break-words hyphens-auto">{t('editor.guided.finish.noBoard')}</p>
      ) : (
        <>
          <span className="text-sm break-words hyphens-auto">{t('editor.guided.finish.savedBody')}</span>
          <div className="flex flex-wrap items-center gap-2 min-w-0">
            <select id={`${ids}-board`} className="input !w-auto max-w-full" aria-label={t('editor.guided.finish.board')} value={board?.id ?? ''} onChange={(event) => setBoardId(Number(event.target.value))}>
              {mine.map((one) => (
                <option key={one.id} value={one.id}>
                  {one.name}
                </option>
              ))}
            </select>
            {board && board.pages.length > 1 && (
              <select className="input !w-auto max-w-full" aria-label={t('editor.guided.finish.page')} value={page?.id ?? ''} onChange={(event) => setPageId(Number(event.target.value))}>
                {board.pages.map((one) => (
                  <option key={one.id} value={one.id}>
                    {one.name}
                  </option>
                ))}
              </select>
            )}
            <button type="button" className="btn btn-accent" disabled={!page || state.status === 'busy'} onClick={() => void place()}>
              {state.status === 'busy' ? <Spinner /> : null}
              {t('editor.guided.finish.place')}
            </button>
            <button type="button" className="text-accent font-medium text-sm" onClick={() => setState({ status: 'later' })}>
              {t('editor.guided.finish.later')}
            </button>
          </div>
          {state.status === 'failed' && (
            <p className="text-sm text-bad break-words" role="alert">
              {state.message}
            </p>
          )}
        </>
      )}
    </div>
  )
}

/**
 * Step 4, Finish (U8): the name, with its English beside it away from English and more languages to add; how often
 * the card looks again; for numbers the colour sentences; example data from the answer; Save, and after the first
 * save of a new card the offer to put it on a board.
 */
export function FinishStep({ onSave, canSave, busy }: { onSave: () => void; canSave: boolean; busy: boolean }) {
  const { t, i18n } = useTranslation()
  const ids = useId()
  const language = useLanguage()
  const card = useCardEditor((state) => state.card ?? state.lastValid?.card ?? null)
  const slug = useCardEditor((state) => state.slug)
  const created = useCardEditor((state) => state.created)
  const change = useCardEditor((state) => state.change)
  const { chosen } = useConnections()
  const [more, setMore] = useState<string[]>([])
  const [adding, setAdding] = useState(false)
  const [demoOpen, setDemoOpen] = useState(false)
  if (!card) return null

  const name = readAt(card, ['name'])
  const written = name && typeof name === 'object' ? Object.keys(name as object).filter((code) => code !== 'en' && code !== language) : []
  const others = [...new Set([...written, ...more])]
  const own = textIn(card, NAME, language)
  const english = textIn(card, NAME, 'en')
  const setName = (code: string, text: string) =>
    change((doc) => {
      if (code === language) writeLocal(doc, NAME, language, text)
      else writeText(doc, NAME, code, text)
      // A new card's short name follows its English name until it is saved; "All settings" can change it.
      if (slug === null) {
        const now = readIn(doc, ['name']) as CardText | undefined
        const base = typeof now === 'string' ? now : (now?.en ?? text)
        setAt(doc, ['slug'], slugFrom(base) || 'new-card')
      }
    }, `field:guided.name.${code}`)

  const form = readAt(card, ['form']) as CardForm
  const requests = readAt(card, ['requests'])
  const count = Array.isArray(requests) ? requests.length : 0
  const every = String(readAt(card, ['requests', 0, 'every']) ?? '60s')
  const everyChoices: string[] = (GUIDED_EVERY as readonly string[]).includes(every) ? [...GUIDED_EVERY] : [every, ...GUIDED_EVERY]
  const numbers = form === 'value' ? [['value']] : form === 'stats' ? Array.from({ length: Array.isArray(readAt(card, ['stats'])) ? (readAt(card, ['stats']) as unknown[]).length : 0 }, (_, index) => ['stats', index]) : []
  const first = numbers[0] ? readAt(card, numbers[0]) : undefined
  const thresholds = numbers.length ? thresholdsOf(first && typeof first === 'object' ? (first as { rules?: unknown }).rules : undefined) : null
  const setThresholds = (warn: number | null, bad: number | null) => change((doc) => numbers.forEach((path) => writeThresholds(doc, path, warn, bad)), 'field:guided.colour')
  const free = OFFERED_LANGUAGES.filter((code) => code !== language && !others.includes(code))

  return (
    <GuidedFrame id="finish" title={t('editor.guided.finish.title')} lead={t('editor.guided.finish.lead')}>
      <div className="grid gap-3 sm:grid-cols-2 min-w-0">
        <div className="grid gap-1 min-w-0 content-start">
          <label className={LABEL} htmlFor={`${ids}-name`}>
            {t('editor.guided.finish.name')}
          </label>
          <input id={`${ids}-name`} className="input" value={own} maxLength={60} aria-invalid={!own.trim() || undefined} onChange={(event) => setName(language, event.target.value)} />
          {!own.trim() && (
            <span className="text-[12px] text-bad" role="alert">
              {t('editor.guided.finish.nameRequired')}
            </span>
          )}
          {language !== 'en' && (
            <span className="flex flex-wrap items-center gap-1.5 min-w-0">
              <span className="text-[12px] text-faint">{t('editor.guided.finish.inEnglish')}</span>
              <input className="input !w-48 max-w-full !py-1" value={english} maxLength={60} aria-label={t('editor.guided.finish.nameIn', { language: languageName('en', i18n.language) })} onChange={(event) => setName('en', event.target.value)} />
            </span>
          )}
          {others.map((code) => (
            <span key={code} className="flex flex-wrap items-center gap-1.5 min-w-0">
              <span className="text-[12px] text-faint">{languageName(code, i18n.language)}</span>
              <input className="input !w-48 max-w-full !py-1" value={textIn(card, NAME, code)} maxLength={60} aria-label={t('editor.guided.finish.nameIn', { language: languageName(code, i18n.language) })} onChange={(event) => setName(code, event.target.value)} />
            </span>
          ))}
          {adding ? (
            <select
              className="input !w-auto max-w-full"
              aria-label={t('editor.guided.finish.addLanguage')}
              value=""
              onChange={(event) => {
                if (event.target.value) setMore([...more, event.target.value])
                setAdding(false)
              }}
            >
              <option value="">{t('editor.guided.finish.addLanguage')}</option>
              {free.map((code) => (
                <option key={code} value={code}>
                  {languageName(code, i18n.language)}
                </option>
              ))}
            </select>
          ) : (
            <button type="button" className="text-accent font-medium text-[12.5px] justify-self-start" onClick={() => setAdding(true)}>
              {t('editor.guided.finish.addLanguage')}
            </button>
          )}
        </div>
        <div className="grid gap-1 min-w-0 content-start">
          <label className={LABEL} htmlFor={`${ids}-every`}>
            {t('editor.guided.finish.every')}
          </label>
          <select
            id={`${ids}-every`}
            className="input"
            value={every}
            onChange={(event) => {
              const value = event.target.value
              change((doc) => Array.from({ length: count }, (_, index) => setAt(doc, ['requests', index, 'every'], value)))
            }}
          >
            {everyChoices.map((one) => (
              <option key={one} value={one}>
                {(GUIDED_EVERY as readonly string[]).includes(one) ? t(`editor.guided.finish.everyChoice.${one}`) : everyText(t, one)}
              </option>
            ))}
          </select>
        </div>
      </div>

      {numbers.length > 0 && (
        <div className="grid gap-2 min-w-0">
          <p className="text-[12px] uppercase tracking-wide text-faint font-semibold">{t('editor.guided.finish.colour')}</p>
          {thresholds === null ? (
            <p className="text-sm text-muted break-words hyphens-auto">{t('editor.guided.display.expression')}</p>
          ) : (
            (['warn', 'bad'] as const).map((level) => (
              <div key={level} className="flex flex-wrap items-center gap-2 rounded-2xl border border-line px-3.5 py-3 text-sm min-w-0">
                <span>{t(`editor.guided.finish.${level}Before`)}</span>
                <input
                  className="input !w-28"
                  inputMode="decimal"
                  aria-label={t(`editor.guided.finish.${level}Label`)}
                  placeholder={t('editor.guided.finish.never')}
                  value={thresholds[level] ?? ''}
                  onChange={(event) => {
                    const next = thresholdOf(event.target.value)
                    setThresholds(level === 'warn' ? next : thresholds.warn, level === 'bad' ? next : thresholds.bad)
                  }}
                />
                <span>{t(`editor.guided.finish.${level}After`)}</span>
              </div>
            ))
          )}
        </div>
      )}

      {chosen && (
        <div className="grid gap-1 min-w-0">
          <button type="button" className="btn justify-self-start" onClick={() => setDemoOpen(true)}>
            {t('editor.guided.finish.example')}
          </button>
          <span className="text-[12px] text-faint break-words hyphens-auto">{t('editor.guided.finish.exampleHint')}</span>
          {demoOpen && <DemoDialog open onClose={() => setDemoOpen(false)} integrationId={chosen.id} />}
        </div>
      )}

      {created && <PutOnBoard />}

      <StepNav>
        <button type="button" className="btn btn-accent" onClick={onSave} disabled={!canSave || !own.trim()}>
          {busy ? <Spinner /> : null}
          {created ? t('editor.guided.finish.saveAgain') : t('editor.save')}
        </button>
      </StepNav>
    </GuidedFrame>
  )
}
