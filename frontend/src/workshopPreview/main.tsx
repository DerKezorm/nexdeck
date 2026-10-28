import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'

import '../styles/app.css'
import '../i18n'
import { OverflowContext } from '../components/BuilderCard'
import { WidgetCard } from '../components/WidgetCard'
import { useBoardCardStyle, type CardStyle } from '../lib/appearance'
import type { WidgetData, WidgetView } from '../lib/types'

/** What the workshop's action hands the page: the data of a card, worked out from its demo answers, and how to draw it. */
export interface Spec {
  data: WidgetData
  form: 'value' | 'stats' | 'list' | 'posters' | 'builder'
  name: string
  theme: 'light' | 'dark'
  style?: CardStyle
  /** Columns and rows of the card; the size of its form when left out. */
  size?: [number, number]
  /** The name of a service logo or a Lucide icon for the header. */
  icon?: string
}

/** The sizes a card of each form is made at, as the editor's preview has them. */
const FORM_SIZES: Record<Spec['form'], [number, number]> = {
  value: [2, 2],
  stats: [3, 2],
  list: [3, 3],
  posters: [4, 3],
  builder: [3, 3],
}
const COLUMN = 92
const ROW = 68
const GAP = 12

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } } })

function Stage({ spec }: { spec: Spec }) {
  useBoardCardStyle(spec.style ?? 'glass')
  const size = spec.size ?? FORM_SIZES[spec.form]
  const widget: WidgetView = {
    id: 0,
    kind: `custom.${spec.form}`,
    title: spec.name,
    icon: spec.icon || 'lucide:layout-dashboard',
    link: '',
    renderer: spec.form,
    options: {},
    integration_id: null,
    refresh_seconds: null,
    default_size: size,
  }
  return (
    <div id="stage" className="nd-stage inline-block p-3" style={{ background: 'var(--nd-bg)', color: 'var(--nd-text)' }} data-ready="true">
      <div style={{ width: size[0] * COLUMN + (size[0] - 1) * GAP, height: size[1] * ROW + (size[1] - 1) * GAP }}>
        <OverflowContext.Provider value={null}>
          <WidgetCard widget={widget} data={spec.data} />
        </OverflowContext.Provider>
      </div>
    </div>
  )
}

const root = createRoot(document.getElementById('root')!)

/** Draws one card. The promise settles once the picture can be taken. */
function show(spec: Spec): Promise<void> {
  document.documentElement.dataset.theme = spec.theme
  document.documentElement.style.background = 'var(--nd-bg)'
  root.render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <MemoryRouter>
          <Stage spec={spec} />
        </MemoryRouter>
      </QueryClientProvider>
    </StrictMode>,
  )
  return new Promise((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(() => void document.fonts.ready.then(() => resolve())))
  })
}

;(window as unknown as { nexdeckPreview: { show: typeof show } }).nexdeckPreview = { show }
