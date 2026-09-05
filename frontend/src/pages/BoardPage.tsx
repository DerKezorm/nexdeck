import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, LayoutGrid, Plus, Settings2 } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router-dom'

import { ApiError, get, post, put } from '../api/client'
import type { BoardSummary, BoardWithLive } from '../api/types'
import { BackgroundLayer } from '../components/BackgroundLayer'
import { BoardGrid } from '../components/BoardGrid'
import { BoardSettingsSheet } from '../components/BoardSettingsSheet'
import { CommandPalette } from '../components/CommandPalette'
import { MobileTabBar } from '../components/MobileTabBar'
import { NoticeDrawer } from '../components/NoticeDrawer'
import { TopBar } from '../components/TopBar'
import { Confirm, Dialog, Spinner, Toast } from '../components/ui'
import { WhatsNewDialog } from '../components/WhatsNewDialog'
import { WidgetLibrary } from '../components/WidgetLibrary'
import { WidgetSettingsSheet, type WidgetDraft } from '../components/WidgetSettingsSheet'
import { useStream } from '../hooks/useStream'
import { tLabel } from '../i18n/texts'
import type { Action, Breakpoint, LayoutItem, WidgetData, WidgetView } from '../lib/types'
import { useAuth } from '../stores/auth'
import { useLive } from '../stores/live'
import { useNotices } from '../stores/notices'

const EDIT_HINT_SEEN = 'nexdeck.editHintSeen'

export function BoardPage() {
  const { t } = useTranslation()
  const { slug = '', page: pageSlug } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const user = useAuth((state) => state.user)
  const { unread, setOpen: openNotices } = useNotices()
  const live = useLive()

  const board = useQuery({ queryKey: ['board', slug], queryFn: () => get<BoardWithLive>(`/boards/${slug}`), enabled: Boolean(slug) })
  const boards = useQuery({ queryKey: ['boards'], queryFn: () => get<BoardSummary[]>('/boards') })
  /** What the menu shows: boards with the flag, plus the one being looked at,
      because a board that hid itself must still say where you are. */
  const menuBoards = useMemo(() => (boards.data ?? []).filter((entry) => entry.in_menu || entry.slug === slug), [boards.data, slug])
  const history = useQuery({ queryKey: ['board-history', slug], queryFn: () => get<Record<string, Record<string, [number, number][]>>>(`/boards/${slug}/history`), enabled: Boolean(board.data), staleTime: 60_000 })

  const [editing, setEditing] = useState(false)
  const [library, setLibrary] = useState(false)
  const [settingsFor, setSettingsFor] = useState<number | null>(null)
  const [boardSettings, setBoardSettings] = useState(false)
  const [palette, setPalette] = useState(false)
  const [pending, setPending] = useState<{ widgetId: number; action: Action } | null>(null)
  const [toast, setToast] = useState<{ text: string; level: 'ok' | 'error' | 'info' } | null>(null)
  const [removing, setRemoving] = useState<number | null>(null)
  const [newPage, setNewPage] = useState(false)
  const [newPageName, setNewPageName] = useState('')
  const [deletingPage, setDeletingPage] = useState(false)
  const [previewBackground, setPreviewBackground] = useState<BoardWithLive['background'] | null>(null)
  const [previewSettings, setPreviewSettings] = useState<Record<string, unknown> | null>(null)
  const [draftWidget, setDraftWidget] = useState<WidgetDraft | null>(null)
  // holdUntilChange: after a save the preview stays until the server has fetched with the new options,
  // so the card does not flash its old numbers in between.
  const [previewData, setPreviewData] = useState<{ id: number; data: WidgetData; holdUntilChange?: number } | null>(null)

  const data = board.data
  const pages = useMemo(() => data?.pages ?? [], [data])
  const activePage = pages.find((p) => p.slug === pageSlug) ?? pages[0]
  const canEdit = data ? ['edit', 'act', 'owner'].includes(data.permission) && !data.provisioned : false
  const canAct = data ? ['act', 'owner'].includes(data.permission) : false
  const settings = previewSettings ?? data?.settings ?? {}

  // Snapshot and history into the live store.
  useEffect(() => {
    if (data?.live) live.setSnapshot(data.live)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data])
  useEffect(() => {
    if (!history.data) return
    for (const [id, series] of Object.entries(history.data)) live.setSeries(Number(id), series)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [history.data])

  useStream({
    board: slug,
    enabled: Boolean(data),
    onBoardChanged: () => void board.refetch(),
    onConnected: () => void board.refetch(),
    onLayout: (payload) => {
      queryClient.setQueryData<BoardWithLive>(['board', slug], (old) =>
        old ? { ...old, pages: old.pages.map((p) => (p.id === payload.page_id ? { ...p, layouts: payload.layouts as typeof p.layouts } : p)) } : old,
      )
    },
  })

  // Layout saving, debounced per page.
  const saveTimer = useRef<number>(0)
  const draft = useRef<Record<number, Partial<Record<Breakpoint, LayoutItem[]>>>>({})
  const onLayoutChange = useCallback(
    (breakpoint: Breakpoint, layout: LayoutItem[]) => {
      if (!activePage) return
      draft.current[activePage.id] = { ...(draft.current[activePage.id] ?? {}), [breakpoint]: layout }
      window.clearTimeout(saveTimer.current)
      saveTimer.current = window.setTimeout(() => {
        const body = draft.current[activePage.id]
        if (!body) return
        void put(`/pages/${activePage.id}/layouts`, body).catch(() => setToast({ text: t('board.saveFailed'), level: 'error' }))
      }, 700)
    },
    [activePage, t],
  )

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setPalette((v) => !v)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // The first time edit mode opens, say how moving and resizing work.
  useEffect(() => {
    if (!editing) return
    try {
      if (localStorage.getItem(EDIT_HINT_SEEN)) return
      localStorage.setItem(EDIT_HINT_SEEN, '1')
    } catch {
      // storage may be unavailable; the hint then shows every time, which is fine
    }
    setToast({ text: t('board.editHint'), level: 'info' })
  }, [editing, t])

  const widgets: WidgetView[] = useMemo(
    () =>
      (activePage?.widgets ?? []).map((w) => {
        const merged = w.health ? { ...w, health: { ...w.health, ...(live.health[w.id] ?? {}) } } : w
        // While the settings sheet is open, the card shows the draft.
        return draftWidget && draftWidget.id === w.id ? { ...merged, title: draftWidget.title, icon: draftWidget.icon, link: draftWidget.link, options: draftWidget.options } : merged
      }),
    [activePage, live.health, draftWidget],
  )
  // Data fetched with draft options replaces the live data of that one card.
  const gridData = useMemo(() => (previewData ? { ...live.data, [previewData.id]: previewData.data } : live.data), [live.data, previewData])
  useEffect(() => {
    if (previewData?.holdUntilChange === undefined) return
    const current = live.data[previewData.id]?.updated_at ?? 0
    if (current !== previewData.holdUntilChange) setPreviewData(null)
  }, [live.data, previewData])
  useEffect(() => {
    if (previewData?.holdUntilChange === undefined) return
    const id = window.setTimeout(() => setPreviewData(null), 20_000)
    return () => window.clearTimeout(id)
  }, [previewData])

  const runAction = async (widgetId: number, action: Action) => {
    try {
      const result = await post<{ message: string }>(`/widgets/${widgetId}/actions/${action.id}`, { params: action.params ?? {} })
      setToast({ text: result.message, level: 'ok' })
    } catch (failure) {
      setToast({ text: failure instanceof ApiError ? failure.message : t('errors.network'), level: 'error' })
    }
  }
  const onAction = (widgetId: number, action: Action) => {
    if (action.confirm) setPending({ widgetId, action })
    else void runAction(widgetId, action)
  }

  const allActions = useMemo(() => {
    const list: { widget: WidgetView; action: Action }[] = []
    if (!canAct) return list
    for (const widget of widgets) {
      for (const action of live.data[widget.id]?.actions ?? []) list.push({ widget, action })
    }
    return list
  }, [widgets, live.data, canAct])

  const closeWidgetSettings = () => {
    setSettingsFor(null)
    setDraftWidget(null)
    setPreviewData(null)
  }

  if (board.isLoading) {
    return (
      <div className="min-h-full flex items-center justify-center">
        <BackgroundLayer />
        <Spinner />
      </div>
    )
  }
  if (board.isError || !data || !activePage) {
    const failure = board.error
    return (
      <div className="min-h-full flex items-center justify-center p-6">
        <BackgroundLayer />
        <div className="glass rounded-2xl p-6 text-center">
          <p className="font-medium">{failure instanceof ApiError && failure.status === 404 ? t('board.notFound') : t('board.loadFailed')}</p>
          <button className="btn mt-4" onClick={() => navigate('/')}>
            {t('common.back')}
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-full pb-24 md:pb-10">
      <BackgroundLayer background={previewBackground ?? data.background} />
      <TopBar
        boardName={data.name}
        pages={pages.map((p) => ({ id: p.id, name: p.name }))}
        activePage={activePage.id}
        onPage={(id) => {
          const page = pages.find((p) => p.id === id)
          if (page) navigate(`/b/${slug}/${page.slug}`)
        }}
        editing={editing}
        onEdit={() => setEditing((v) => !v)}
        canEdit={canEdit}
        unread={unread}
        onNotices={() => openNotices(true)}
        onSearch={() => setPalette(true)}
        onBoards={() => setBoardSettings(true)}
        user={user}
        boards={menuBoards.map((b) => ({ id: b.id, name: b.name, slug: b.slug }))}
        onSwitchBoard={(boardSlug) => navigate(`/b/${boardSlug}`)}
      />
      <main className="max-w-[1480px] mx-auto px-3 sm:px-4 pt-4">
        {widgets.length === 0 && (
          <div className="glass rounded-2xl p-8 text-center max-w-md mx-auto mt-10">
            <LayoutGrid className="mx-auto text-accent" size={28} />
            <h2 className="font-semibold mt-3">{t('board.empty.title')}</h2>
            <p className="text-sm text-muted mt-1">{canEdit ? t('board.empty.body') : t('board.empty.readonly')}</p>
            {canEdit && (
              <div className="mt-4 flex justify-center gap-2">
                <button
                  className="btn btn-accent"
                  onClick={() => {
                    setEditing(true)
                    setLibrary(true)
                  }}
                >
                  <Plus size={14} /> {t('board.addWidget')}
                </button>
                {/* An empty page is where one wonders how to get rid of it; the last page stays. */}
                {pages.length > 1 && (
                  <button className="btn" onClick={() => setDeletingPage(true)}>
                    {t('board.deletePage')}
                  </button>
                )}
              </div>
            )}
          </div>
        )}
        <BoardGrid
          key={activePage.id}
          widgets={widgets}
          layouts={activePage.layouts}
          data={gridData}
          series={live.series}
          editing={editing}
          canAct={canAct}
          autoCompact={Boolean(settings.compact)}
          onLayoutChange={onLayoutChange}
          onAction={onAction}
          onRefresh={(id) => void post(`/widgets/${id}/refresh`)}
          onSettings={(id) => setSettingsFor(id)}
          onRemove={(id) => setRemoving(id)}
        />
      </main>

      {editing && (
        <div className="fixed bottom-20 md:bottom-6 left-1/2 -translate-x-1/2 z-40 glass-strong rounded-full px-2 py-1.5 flex items-center gap-1 shadow-2xl">
          <button className="btn border-0 bg-transparent" onClick={() => setLibrary(true)}>
            <Plus size={15} /> {t('board.addWidget')}
          </button>
          <button className="btn border-0 bg-transparent" onClick={() => setNewPage(true)}>
            <Plus size={15} /> {t('board.addPage')}
          </button>
          <button className="btn border-0 bg-transparent" onClick={() => setBoardSettings(true)}>
            <Settings2 size={15} /> {t('board.settings')}
          </button>
          <button className="btn btn-accent rounded-full" onClick={() => setEditing(false)}>
            <Check size={15} /> {t('common.done')}
          </button>
        </div>
      )}

      <MobileTabBar
        boards={menuBoards.map((b) => ({ id: b.id, name: b.name, slug: b.slug }))}
        active={data.id}
        onBoard={(id) => {
          const target = boards.data?.find((b) => b.id === id)
          if (target) navigate(`/b/${target.slug}`)
        }}
        onSearch={() => setPalette(true)}
        onNotices={() => openNotices(true)}
        onMenu={() => navigate('/settings')}
        unread={unread}
      />

      <WidgetLibrary
        open={library}
        onClose={() => setLibrary(false)}
        pageId={activePage.id}
        onCreated={(widgetId) => {
          setLibrary(false)
          void board.refetch()
          setSettingsFor(widgetId)
        }}
      />
      <WidgetSettingsSheet
        widget={activePage.widgets.find((w) => w.id === settingsFor) ?? null}
        pages={pages.map((p) => ({ id: p.id, name: p.name }))}
        onPreview={setDraftWidget}
        onPreviewData={(id, preview) => setPreviewData(preview ? { id, data: preview } : null)}
        onClose={closeWidgetSettings}
        onSaved={() => {
          setDraftWidget(null)
          setPreviewData((current) => (current ? { ...current, holdUntilChange: live.data[current.id]?.updated_at ?? 0 } : null))
          void board.refetch()
        }}
        onDeleted={() => {
          closeWidgetSettings()
          void board.refetch()
        }}
      />
      <BoardSettingsSheet
        open={boardSettings}
        board={data}
        boards={boards.data ?? []}
        canEdit={canEdit}
        onPreview={(background, draftSettings) => {
          setPreviewBackground(background)
          setPreviewSettings(draftSettings)
        }}
        onClose={() => {
          setBoardSettings(false)
          setPreviewBackground(null)
          setPreviewSettings(null)
        }}
        onChanged={() => void Promise.all([board.refetch(), boards.refetch()])}
      />
      <NoticeDrawer />
      <CommandPalette open={palette} onClose={() => setPalette(false)} boards={boards.data ?? []} widgets={widgets} actions={allActions} onAction={onAction} />
      <WhatsNewDialog />

      <Confirm
        open={pending !== null}
        title={pending ? `${tLabel(pending.action.label)}?` : ''}
        body={t('board.confirmAction')}
        danger={pending?.action.danger}
        onCancel={() => setPending(null)}
        onConfirm={() => {
          if (pending) void runAction(pending.widgetId, pending.action)
          setPending(null)
        }}
      />
      <Confirm
        open={removing !== null}
        title={t('widget.remove.title')}
        body={t('widget.remove.body')}
        danger
        onCancel={() => setRemoving(null)}
        onConfirm={() => {
          const id = removing
          setRemoving(null)
          if (id !== null) {
            void import('../api/client').then(({ del }) =>
              del(`/widgets/${id}`)
                .then(() => board.refetch())
                .catch((failure) => setToast({ text: failure instanceof ApiError ? failure.message : t('widget.remove.failed'), level: 'error' })),
            )
          }
        }}
      />
      <Confirm
        open={deletingPage}
        title={t('board.deletePageTitle', { name: activePage.name })}
        body={t('board.deletePageEmpty')}
        danger
        onCancel={() => setDeletingPage(false)}
        onConfirm={() => {
          setDeletingPage(false)
          void import('../api/client').then(({ del }) =>
            del(`/pages/${activePage.id}`)
              .then(() => {
                navigate(`/b/${slug}`)
                void board.refetch()
              })
              .catch((failure) => setToast({ text: failure instanceof ApiError ? failure.message : t('errors.network'), level: 'error' })),
          )
        }}
      />
      <Dialog
        open={newPage}
        onClose={() => setNewPage(false)}
        title={t('board.addPage')}
        size="sm"
        footer={
          <button
            className="btn btn-accent"
            disabled={!newPageName.trim()}
            onClick={() => {
              void post(`/boards/${slug}/pages`, { name: newPageName.trim() }).then(() => {
                setNewPage(false)
                setNewPageName('')
                void board.refetch()
              })
            }}
          >
            {t('common.create')}
          </button>
        }
      >
        <input className="input" autoFocus value={newPageName} placeholder={t('board.pageName')} onChange={(e) => setNewPageName(e.target.value)} />
      </Dialog>
      {toast && (
        <Toast level={toast.level} onClose={() => setToast(null)}>
          {toast.text}
        </Toast>
      )}
    </div>
  )
}
