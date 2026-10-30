/**
 * The skin editor (roadmap skins, phase B): a skin built by clicking, sliders and
 * pixels, its own style sheet behind "Advanced", and the stage beside it wearing
 * every change as the server compiles it.
 *
 * Left the file's parts, in the middle the stage (a frame of its own, so a skin
 * on trial never redraws the editor), right the inspector for the part clicked
 * on the stage, below what the server finds wrong. The server checks while one
 * types (`POST /skins/check`) and compiles; the editor checks nothing itself.
 * Administrators only, and the page is guarded (lib/skin/guard.ts).
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Download, Moon, MousePointerClick, PanelTop, Redo2, Save, Sun, Undo2 } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { ApiError, get, post, put } from '../../api/client'
import { Spinner, Switch, Toast } from '../../components/ui'
import type { Appearance } from '../../lib/appearance'
import { useSkinTexts } from '../../lib/skin/texts'
import { keepDraft, keptDraft, useDraft, type SkinDoc } from '../../lib/skin/draft'
import type { Seen } from '../../lib/skin/look'
import type { Parts } from '../../lib/skin/partAt'
import { wear, type CompiledSkin } from '../../lib/skin/wear'
import { FilePanels } from './FilePanels'
import { Inspector } from './Inspector'
import { AiTab, type LookAtStage } from './AiTab'
import { LOOK_MESSAGE, LOOKED_MESSAGE, PICK_MESSAGE, READY_MESSAGE, STAGE_MESSAGE, type StageState } from './SkinStage'

export interface SkinSchema {
  parts: Parts
  fonts: string[]
  motions: string[]
  waves: string[]
  anchors: string[]
  card_styles: string[]
  limits: { css: number; sprites: number; side: number; colours: number; animation_ms: number[] }
  /** Whether the assistant is set up (the tab AI) and whether it is shown the stage as a picture. */
  ai: { ready: boolean; vision: boolean }
}

export interface Starter {
  key: string
  kind: 'empty' | 'look' | 'example'
  name: string
  text: string
}

interface Checked {
  ok: boolean
  compiled?: CompiledSkin & { weak?: { mode: string; token: string; ratio: number }[] }
  message?: string
  problems: { path?: string; message: string; line?: number; column?: number }[]
}

const WIDTHS = { phone: 390, tablet: 820, desktop: 0 } as const

/** The page: what to open, then the editor once the file and what it needs are here. */
export function SkinEditorPage() {
  const ready = useSkinTexts()
  const { key } = useParams()
  const [search] = useSearchParams()
  const from = search.get('from') ?? 'empty'
  const schema = useQuery({ queryKey: ['skin-schema'], queryFn: () => get<SkinSchema>('/skins/schema') })
  const base = useQuery({ queryKey: ['appearance'], queryFn: () => get<Appearance>('/settings/appearance') })
  const initial = useQuery({
    queryKey: ['skin-open', key ?? from],
    queryFn: async (): Promise<SkinDoc> => {
      if (key) return await get<SkinDoc>(`/skins/${encodeURIComponent(key)}/file`)
      if (from.startsWith('skin:')) {
        const copy = await get<SkinDoc>(`/skins/${encodeURIComponent(from.slice(5))}/file`)
        return { ...copy, key: `${copy.key}-copy`.slice(0, 32), name: `${copy.name} (2)`.slice(0, 60) }
      }
      const { starters } = await get<{ starters: Starter[] }>('/skins/starters')
      return JSON.parse((starters.find((starter) => starter.key === from) ?? starters[0]).text) as SkinDoc
    },
    staleTime: Infinity,
  })
  if (!ready || schema.isLoading || base.isLoading || initial.isLoading) return <Spinner />
  if (!schema.data || !base.data || !initial.data) return <p className="p-6 text-sm text-bad" role="alert">{(initial.error as Error | null)?.message ?? 'nexdeck could not open the skin.'}</p>
  return <Editor key={key ?? from} initial={initial.data} saved={key ?? null} schema={schema.data} base={base.data} />
}

function Editor({ initial, saved, schema, base }: { initial: SkinDoc; saved: string | null; schema: SkinSchema; base: Appearance }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const client = useQueryClient()
  const draft = useDraft(initial)
  const doc = draft.doc
  const draftKey = saved ?? 'new'
  const [offer, setOffer] = useState<SkinDoc | null>(() => {
    const kept = keptDraft(draftKey)
    return kept && JSON.stringify(kept) !== JSON.stringify(initial) ? kept : null
  })
  const [checked, setChecked] = useState<Checked | null>(null)
  const [good, setGood] = useState<CompiledSkin | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [inspect, setInspect] = useState(true)
  const [advanced, setAdvanced] = useState(false)
  const [mode, setMode] = useState<'dark' | 'light'>('dark')
  const [width, setWidth] = useState<keyof typeof WIDTHS>('desktop')
  const [dialog, setDialog] = useState(false)
  const [still, setStill] = useState(false)
  const [options, setOptions] = useState<Record<string, string>>({})
  // A first save moves to the address of the skin; what it said comes along.
  const arrived = (useLocation().state as { saved?: boolean } | null)?.saved
  const [toast, setToast] = useState<{ text: string; level: 'ok' | 'error' } | null>(arrived ? { text: t('skinEditor.saved'), level: 'ok' } : null)
  const [saving, setSaving] = useState(false)
  const [tab, setTab] = useState<'file' | 'ai'>('file')
  const [locked, setLocked] = useState<string[]>([])
  const frame = useRef<HTMLIFrameElement>(null)
  const [stageReady, setStageReady] = useState(false)
  const text = useMemo(() => JSON.stringify(doc, null, 2), [doc])

  // Kept in this browser on every change, and given up once saved.
  useEffect(() => {
    if (offer) return
    keepDraft(draftKey, JSON.stringify(doc) === JSON.stringify(initial) ? null : doc)
  }, [doc, draftKey, initial, offer])

  // The server checks and compiles a moment after the last change.
  useEffect(() => {
    let gone = false
    const timer = window.setTimeout(() => {
      void post<Checked>('/skins/check', { text })
        .then((answer) => {
          if (gone) return
          setChecked(answer)
          if (answer.ok && answer.compiled) setGood(answer.compiled)
        })
        .catch(() => undefined)
    }, 350)
    return () => {
      gone = true
      window.clearTimeout(timer)
    }
  }, [text])

  // The stage: told when it is there, and picks come back from it.
  const looks = useRef(new Map<number, (seen: Seen) => void>())
  const lookAtStage: LookAtStage = (picture) =>
    new Promise((resolve) => {
      const id = Date.now() + Math.random()
      looks.current.set(id, resolve)
      frame.current?.contentWindow?.postMessage({ type: LOOK_MESSAGE, id, picture, parts: schema.parts }, window.location.origin)
      // A stage that does not answer in time is not waited for: the first answer stands.
      window.setTimeout(() => {
        if (looks.current.delete(id)) resolve({ findings: [], pictures: [] })
      }, 20_000)
    })
  useEffect(() => {
    const waiting = looks.current
    const listen = (event: MessageEvent) => {
      if (event.origin !== window.location.origin || event.source !== frame.current?.contentWindow) return
      if (event.data?.type === READY_MESSAGE) setStageReady(true)
      if (event.data?.type === PICK_MESSAGE && typeof event.data.part === 'string') setSelected(event.data.part)
      if (event.data?.type === LOOKED_MESSAGE) {
        const resolve = waiting.get(event.data.id)
        if (resolve && waiting.delete(event.data.id)) resolve({ findings: event.data.findings ?? [], pictures: event.data.pictures ?? [] })
      }
    }
    window.addEventListener('message', listen)
    return () => window.removeEventListener('message', listen)
  }, [])

  useEffect(() => {
    if (!stageReady || !frame.current?.contentWindow) return
    const look = wear(base, { key: good?.key, options }, good)
    const state: StageState = { type: STAGE_MESSAGE, look, mode, parts: schema.parts, inspect, selected, dialog, still }
    frame.current.contentWindow.postMessage(state, window.location.origin)
  }, [stageReady, good, base, options, mode, inspect, selected, dialog, still, schema.parts])

  // Ctrl+Z and Ctrl+Y (or Ctrl+Shift+Z), unless a text field takes them for itself.
  useEffect(() => {
    const press = (event: KeyboardEvent) => {
      const typing = event.target instanceof HTMLElement && /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName)
      if (typing || !(event.ctrlKey || event.metaKey)) return
      if (event.key.toLowerCase() === 'z' && !event.shiftKey) {
        event.preventDefault()
        draft.undo()
      } else if (event.key.toLowerCase() === 'y' || (event.key.toLowerCase() === 'z' && event.shiftKey)) {
        event.preventDefault()
        draft.redo()
      }
    }
    window.addEventListener('keydown', press)
    return () => window.removeEventListener('keydown', press)
  }, [draft])

  const store = async () => {
    setSaving(true)
    try {
      const answer = saved ? await put<{ key: string }>(`/skins/${encodeURIComponent(saved)}`, { text }) : await post<{ key: string }>('/skins', { text })
      keepDraft(draftKey, null)
      await client.invalidateQueries({ queryKey: ['skins'] })
      if (answer.key !== saved) navigate(`/system/skins/${encodeURIComponent(answer.key)}/edit`, { replace: true, state: { saved: true } })
      else setToast({ text: t('skinEditor.saved'), level: 'ok' })
    } catch (failure) {
      setToast({ text: failure instanceof ApiError ? failure.message : t('errors.network'), level: 'error' })
    } finally {
      setSaving(false)
    }
  }
  const download = () => {
    const link = document.createElement('a')
    link.href = URL.createObjectURL(new Blob([text], { type: 'application/json' }))
    link.download = `${doc.key}.nexdeck-skin.json`
    link.click()
    URL.revokeObjectURL(link.href)
  }
  const optionList = (good?.options ?? []) as CompiledSkin['options']

  return (
    <div className="flex flex-col h-[100dvh]" data-testid="skin-editor">
      <header className="glass-strong app-bar flex items-center gap-2 px-3 h-12 border-x-0 border-t-0 rounded-none shrink-0">
        <Link to="/system/skins" className="btn btn-flat btn-icon" aria-label={t('skinEditor.back')}>
          <ArrowLeft size={16} />
        </Link>
        <h1 className="font-semibold truncate">{doc.name || t('skinEditor.untitled')}</h1>
        <span className="text-xs text-faint truncate">{saved ? t('skinEditor.editing') : t('skinEditor.new')}</span>
        <div className="flex-1" />
        <button type="button" className="btn btn-flat btn-icon" onClick={draft.undo} disabled={!draft.canUndo} aria-label={t('skinEditor.undo')} title={t('skinEditor.undo')}>
          <Undo2 size={16} />
        </button>
        <button type="button" className="btn btn-flat btn-icon" onClick={draft.redo} disabled={!draft.canRedo} aria-label={t('skinEditor.redo')} title={t('skinEditor.redo')}>
          <Redo2 size={16} />
        </button>
        <button type="button" className="btn btn-flat btn-icon" onClick={download} aria-label={t('skinEditor.download')} title={t('skinEditor.download')}>
          <Download size={16} />
        </button>
        <button type="button" className="btn btn-accent" onClick={() => void store()} disabled={saving || checked?.ok === false}>
          <Save size={14} /> {t('common.save')}
        </button>
      </header>
      {offer && (
        <div className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm bg-warn/10 border-b border-line" role="status">
          <span className="flex-1">{t('skinEditor.draftFound')}</span>
          <button type="button" className="btn" onClick={() => (draft.set(offer), setOffer(null))}>
            {t('skinEditor.draftRestore')}
          </button>
          <button type="button" className="btn btn-flat" onClick={() => (keepDraft(draftKey, null), setOffer(null))}>
            {t('skinEditor.draftDiscard')}
          </button>
        </div>
      )}
      <div className="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-[320px_minmax(0,1fr)_300px]">
        <aside className="min-h-0 overflow-y-auto border-r border-line p-3 flex flex-col gap-2" aria-label={t('skinEditor.file')}>
          {schema.ai.ready && (
            <div className="flex gap-1" role="tablist">
              {(['file', 'ai'] as const).map((name) => (
                <button key={name} type="button" role="tab" aria-selected={tab === name} className="btn btn-flat flex-1" onClick={() => setTab(name)}>
                  {t(`skinEditor.ai.tab.${name}`)}
                </button>
              ))}
            </div>
          )}
          {tab === 'ai' && schema.ai.ready ? (
            <AiTab doc={doc} draft={draft} locked={locked} onLocked={setLocked} sees={schema.ai.vision} look={lookAtStage} />
          ) : (
            <>
              <Switch checked={advanced} onChange={setAdvanced} label={t('skinEditor.advanced')} description={t('skinEditor.advancedHelp')} />
              <FilePanels doc={doc} draft={draft} schema={schema} base={base} advanced={advanced} weak={checked?.compiled?.weak ?? []} keyLocked={saved !== null} locked={locked} />
            </>
          )}
        </aside>
        <section className="min-h-0 flex flex-col" aria-label={t('skinEditor.stage')}>
          <div className="flex flex-wrap items-center gap-1 px-2 py-1.5 border-b border-line text-xs">
            <button type="button" className="btn btn-flat" aria-pressed={inspect} onClick={() => setInspect((value) => !value)} title={t('skinEditor.inspectHelp')}>
              <MousePointerClick size={14} /> {t('skinEditor.inspect')}
            </button>
            <button type="button" className="btn btn-flat btn-icon" aria-pressed={mode === 'light'} onClick={() => setMode((value) => (value === 'dark' ? 'light' : 'dark'))} aria-label={t('skinEditor.brightness')}>
              {mode === 'dark' ? <Moon size={14} /> : <Sun size={14} />}
            </button>
            {(Object.keys(WIDTHS) as (keyof typeof WIDTHS)[]).map((name) => (
              <button key={name} type="button" className="btn btn-flat" aria-pressed={width === name} onClick={() => setWidth(name)}>
                {t(`skinEditor.width.${name}`)}
              </button>
            ))}
            <button type="button" className="btn btn-flat" aria-pressed={dialog} onClick={() => setDialog((value) => !value)}>
              <PanelTop size={14} /> {t('skinEditor.dialog')}
            </button>
            <button type="button" className="btn btn-flat" aria-pressed={still} onClick={() => setStill((value) => !value)}>
              {t('skinEditor.still')}
            </button>
            {optionList.map((option) => (
              <select key={option.key} className="input h-7 text-xs w-auto" aria-label={option.label} value={options[option.key] ?? option.default} onChange={(event) => setOptions((current) => ({ ...current, [option.key]: event.target.value }))}>
                {option.choices.map((choice) => (
                  <option key={choice.key} value={choice.key}>
                    {option.label}: {choice.label}
                  </option>
                ))}
              </select>
            ))}
          </div>
          <div className="flex-1 min-h-0 overflow-auto flex justify-center bg-black/20">
            <iframe ref={frame} src="/skin-stage" title={t('skinEditor.stage')} className="h-full border-0 bg-transparent" style={{ width: WIDTHS[width] || '100%' }} data-testid="skin-stage" />
          </div>
          <Problems checked={checked} onCss={() => setAdvanced(true)} />
        </section>
        <aside className="min-h-0 overflow-y-auto border-l border-line p-3" aria-label={t('skinEditor.inspector')}>
          <Inspector part={selected} doc={doc} draft={draft} schema={schema} advanced={advanced} onAdvanced={() => setAdvanced(true)} />
        </aside>
      </div>
      {toast && (
        <Toast level={toast.level} onClose={() => setToast(null)}>
          {toast.text}
        </Toast>
      )}
    </div>
  )
}

function Problems({ checked, onCss }: { checked: Checked | null; onCss: () => void }) {
  const { t } = useTranslation()
  if (!checked) return null
  if (checked.ok) {
    return (
      <p className="px-3 py-2 text-xs text-ok border-t border-line" role="status">
        {t('skinEditor.allGood')}
      </p>
    )
  }
  return (
    <div className="px-3 py-2 text-xs border-t border-line max-h-40 overflow-y-auto" role="alert" data-testid="skin-problems">
      <p className="font-medium text-bad mb-1">{checked.message}</p>
      <ul className="flex flex-col gap-0.5">
        {checked.problems.map((problem, index) => (
          <li key={index}>
            {problem.line ? (
              <button type="button" className="underline decoration-dotted" onClick={onCss}>
                {t('skinEditor.line', { line: problem.line })}
              </button>
            ) : (
              problem.path && <span className="text-faint">{problem.path}: </span>
            )}{' '}
            {problem.message}
          </li>
        ))}
      </ul>
    </div>
  )
}
