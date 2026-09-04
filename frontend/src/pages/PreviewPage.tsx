import { useEffect, useState } from 'react'

import { BackgroundLayer } from '../components/BackgroundLayer'
import { BoardGrid } from '../components/BoardGrid'
import { MobileTabBar } from '../components/MobileTabBar'
import { TopBar } from '../components/TopBar'
import { DEMO_DATA, DEMO_LAYOUTS, DEMO_SERIES, DEMO_VIEWS } from '../demo/board'

/** The design preview: the real components, invented data, no backend. */
export function PreviewPage() {
  const [theme, setTheme] = useState<'dark' | 'light'>(() => (document.documentElement.dataset.theme === 'light' ? 'light' : 'dark'))
  const [editing, setEditing] = useState(false)
  const [page, setPage] = useState(1)
  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])
  const noop = () => undefined
  return (
    <div className="min-h-full pb-20 md:pb-8">
      <BackgroundLayer background={{ kind: 'bundled', value: 'aurora' }} />
      <TopBar
        boardName="Home"
        pages={[
          { id: 1, name: 'Overview' },
          { id: 2, name: 'Media' },
          { id: 3, name: 'Network' },
        ]}
        activePage={page}
        onPage={setPage}
        editing={editing}
        onEdit={() => setEditing((v) => !v)}
        canEdit
        unread={2}
        onNotices={noop}
        onSearch={noop}
        onBoards={noop}
        theme={theme}
        onTheme={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
        userInitial="A"
        onProfile={noop}
      />
      <main className="max-w-[1480px] mx-auto px-3 sm:px-4 pt-4">
        <BoardGrid widgets={DEMO_VIEWS} layouts={DEMO_LAYOUTS} data={DEMO_DATA} series={DEMO_SERIES} editing={editing} canAct onAction={noop} onRefresh={noop} onSettings={noop} onRemove={noop} />
      </main>
      <MobileTabBar
        boards={[
          { id: 1, name: 'Home' },
          { id: 2, name: 'Media' },
          { id: 3, name: 'Network' },
        ]}
        active={1}
        onBoard={noop}
        onSearch={noop}
        onNotices={noop}
        onMenu={noop}
        unread={2}
      />
    </div>
  )
}
