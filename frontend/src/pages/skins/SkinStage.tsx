/**
 * The stage of the skin editor: nexdeck's own parts with invented data, in a
 * frame of its own, so a skin on trial can never redraw the editor around it.
 *
 * It is a page of the app (`/skin-stage`) started without the app: no account,
 * no look of its own, no stream (main.tsx). The editor hands it the look to
 * wear by message; with the inspector on, a click names the part under the
 * pointer back to the editor instead of doing anything.
 */
import { useEffect, useState } from 'react'
import { Router, type Navigator } from 'react-router-dom'

import { BackgroundLayer } from '../../components/BackgroundLayer'
import { BoardGrid } from '../../components/BoardGrid'
import { TopBar } from '../../components/TopBar'
import { Dialog, Select, Switch } from '../../components/ui'
import { DEMO_DATA, DEMO_LAYOUTS, DEMO_SERIES, DEMO_VIEWS } from '../../demo/board'
import { setLanguage, storedLanguage } from '../../i18n'
import { applyAppearance, type Appearance } from '../../lib/appearance'
import { audit, capture } from '../../lib/skin/look'
import { elementsOf, partAt, type Parts } from '../../lib/skin/partAt'

export const STAGE_MESSAGE = 'nexdeck-skin-stage'
export const PICK_MESSAGE = 'nexdeck-skin-pick'
export const READY_MESSAGE = 'nexdeck-skin-stage-ready'
/** The editor asks the stage to look at itself; the answer carries the same id. */
export const LOOK_MESSAGE = 'nexdeck-skin-look'
export const LOOKED_MESSAGE = 'nexdeck-skin-looked'

export interface StageState {
  type: typeof STAGE_MESSAGE
  look: Appearance
  mode: 'dark' | 'light'
  parts: Parts
  inspect: boolean
  selected: string | null
  dialog: boolean
  still: boolean
}

/** Links on the stage lead nowhere: it shows parts, it is not a place to go. */
const STAY: Navigator = { createHref: (to) => (typeof to === 'string' ? to : (to.pathname ?? '/')), go: () => undefined, push: () => undefined, replace: () => undefined }

const OWN_STYLE = `
[data-stage-pick] { outline: 2px dashed #ff2d95 !important; outline-offset: 2px !important; }
[data-stage-hover] { outline: 2px solid #ff2d95 !important; outline-offset: 1px !important; cursor: crosshair !important; }
html[data-stage-still] *, html[data-stage-still] *::before, html[data-stage-still] *::after { animation: none !important; transition: none !important; }
`

function mark(attribute: string, elements: Element[]): void {
  for (const element of document.querySelectorAll(`[${attribute}]`)) element.removeAttribute(attribute)
  for (const element of elements) element.setAttribute(attribute, '')
}

export function SkinStage() {
  const [state, setState] = useState<StageState | null>(null)
  const [tab, setTab] = useState(0)
  const [on, setOn] = useState(true)
  const [choice, setChoice] = useState('one')

  useEffect(() => {
    void setLanguage(storedLanguage())
    const style = document.createElement('style')
    style.textContent = OWN_STYLE
    document.head.append(style)
    const listen = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return
      if (event.data?.type === STAGE_MESSAGE) setState(event.data as StageState)
      if (event.data?.type === LOOK_MESSAGE) {
        const { id, picture, parts } = event.data as { id: number; picture: boolean; parts: Parts }
        // Without the marks of the inspector: they are the editor's, not the skin's.
        const marked = [...document.querySelectorAll('[data-stage-pick]')]
        marked.forEach((element) => element.removeAttribute('data-stage-pick'))
        mark('data-stage-hover', [])
        void (picture ? capture(document) : Promise.resolve('')).then((image) => {
          marked.forEach((element) => element.setAttribute('data-stage-pick', ''))
          window.parent.postMessage({ type: LOOKED_MESSAGE, id, findings: audit(document, parts), image }, window.location.origin)
        })
      }
    }
    window.addEventListener('message', listen)
    window.parent.postMessage({ type: READY_MESSAGE }, window.location.origin)
    return () => {
      window.removeEventListener('message', listen)
      style.remove()
    }
  }, [])

  useEffect(() => {
    if (!state) return
    applyAppearance(state.look)
    const root = document.documentElement
    root.dataset.theme = state.mode
    if (state.still) root.setAttribute('data-stage-still', '')
    else root.removeAttribute('data-stage-still')
    const part = state.selected ? state.parts[state.selected] : null
    mark('data-stage-pick', part ? elementsOf(document, part) : [])
  }, [state])

  useEffect(() => {
    if (!state?.inspect) {
      mark('data-stage-hover', [])
      return
    }
    const parts = state.parts
    const over = (event: PointerEvent) => {
      const found = partAt(event.target as Element, parts)
      mark('data-stage-hover', found ? [found.element] : [])
    }
    const click = (event: MouseEvent) => {
      event.preventDefault()
      event.stopPropagation()
      const found = partAt(event.target as Element, parts)
      if (found) window.parent.postMessage({ type: PICK_MESSAGE, part: found.part }, window.location.origin)
    }
    document.addEventListener('pointerover', over, true)
    document.addEventListener('click', click, true)
    return () => {
      document.removeEventListener('pointerover', over, true)
      document.removeEventListener('click', click, true)
      mark('data-stage-hover', [])
    }
  }, [state?.inspect, state?.parts])

  const noop = () => undefined
  return (
    <Router location="/" navigator={STAY}>
      <div className="min-h-full pb-8">
        <BackgroundLayer background={{ kind: 'bundled', value: 'aurora' }} />
        <TopBar
          boardName="Home"
          pages={[
            { id: 1, name: 'Overview' },
            { id: 2, name: 'Media' },
          ]}
          activePage={1}
          onPage={noop}
          editing={false}
          onEdit={noop}
          canEdit
          unread={2}
          onNotices={noop}
          onSearch={noop}
          onBoards={noop}
          user={{ display_name: 'Demo', username: 'demo', role: 'admin', avatar_url: null }}
        />
        <div className="max-w-[1480px] mx-auto px-3 sm:px-4 pt-4">
          <BoardGrid widgets={DEMO_VIEWS} layouts={DEMO_LAYOUTS} data={DEMO_DATA} series={DEMO_SERIES} editing={false} canAct onAction={noop} onRefresh={noop} onSettings={noop} onRemove={noop} />
        </div>
        {/* A settings page in small: the frame, its list of sections, a box, and every control there is. */}
        <main data-shell className="max-w-[1480px] mx-auto px-3 sm:px-4 pt-6 grid gap-4 sm:grid-cols-[180px_1fr]">
          <nav className="flex flex-col gap-1 text-sm">
            <a href="#look" aria-current="page" onClick={(event) => event.preventDefault()}>
              Look
            </a>
            <a href="#users" onClick={(event) => event.preventDefault()}>
              Users
            </a>
          </nav>
          <div className="glass p-5 rounded-2xl flex flex-col gap-4">
            <h2 className="font-semibold">Controls</h2>
            <div className="flex flex-wrap gap-2">
              <button type="button" className="btn btn-accent">Save</button>
              <button type="button" className="btn">Cancel</button>
              <button type="button" className="btn btn-danger">Delete</button>
              <button type="button" className="btn btn-flat">Flat</button>
            </div>
            <div className="grid sm:grid-cols-2 gap-3">
              <input className="input" defaultValue="Plex" aria-label="Name" />
              <Select value={choice} onChange={setChoice} options={[{ value: 'one', label: 'One' }, { value: 'two', label: 'Two' }]} />
            </div>
            <div className="flex flex-wrap items-center gap-4 text-sm">
              <label className="flex items-center gap-2">
                <input type="checkbox" defaultChecked /> Remember
              </label>
              <Switch checked={on} onChange={setOn} label="Switched on" />
            </div>
            <div className="flex gap-1" role="tablist">
              {['First', 'Second', 'Third'].map((name, index) => (
                <button key={name} type="button" role="tab" aria-selected={tab === index} className="btn btn-flat" onClick={() => setTab(index)}>
                  {name}
                </button>
              ))}
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <span className="chip">Beta</span>
              <span className="chip">3 running</span>
              <span className="dot" data-status="ok" />
              <span className="dot" data-status="warn" />
              <span className="dot" data-status="bad" />
              <span className="dot" data-status="unknown" />
            </div>
            <div className="bar" data-status="warn">
              <i style={{ width: '72%' }} />
            </div>
            <input type="range" defaultValue={40} aria-label="Volume" />
          </div>
        </main>
        <Dialog open={state?.dialog === true} onClose={noop} title="A dialog" footer={<button type="button" className="btn btn-accent">Done</button>}>
          <p className="text-sm">How a dialog looks in this skin: its frame, its head and its buttons.</p>
        </Dialog>
      </div>
    </Router>
  )
}
