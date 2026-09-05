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
import { WidgetSettingsSheet } from '../components/WidgetSettingsSheet'
import { useStream } from '../hooks/useStream'
import type { Action, Breakpoint, LayoutItem, WidgetView } from '../lib/types'
import { applyTheme, currentTheme, useAuth } from '../stores/auth'
import { useLive } from '../stores/live'
import { useNotices } from '../stores/notices'

export function BoardPage() {
  const { t } = useTranslation()
  const { slug = '', page: pageSlug } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { user, update } = useAuth()
  const { unread, setOpen: openNotices } = useNotices()
  const live = useLive()

  const board = useQuery({ queryKey: ['board', slug], queryFn: () => get<BoardWithLive>(`/boards/${slug}`), enabled: Boolean(slug) })
  const boards = useQuery({ queryKey: ['boards'], queryFn: () => get<BoardSummary[]>('/boards') })
  const history = useQuery({ queryKey: ['board-history', slug], queryFn: () => get<Record<string, Record<string, [number, number][]>>>(`/boards/${slug}/history`), enabled: Boolean(board.data), staleTime: 60_000 })

  const [editing, setEditing] = useState(false)
  const [library, setLibrary] = useState(false)
  const [settingsFor, setSettingsFor] = useState<number | null>(null)
  const [boardSettings, setBoardSettings] = useState(false)
  const [palette, setPalette] = useState(false)
  const [pending, setPending] = useState<{ widgetId: number; action: Action } | null>(null)
  const [toast, setToast] = useState<{ text: string; level: 'ok' | 'error' } | null>(null)
  const [removing, setRemoving] = useState<number | null>(null)
  const [newPage, setNewPage] = useState(false)
  const [newPageName, setNewPageName] = useState('')
  const [theme, setTheme] = useState(currentTheme())
  const [previewBackground, setPreviewBackground] = useState<BoardWithLive['background'] | null>(null)
  const [draftWidget, setDraftWidget] = useState<{ id: number; title: string; icon: string; link: string } | null>(null)

  const data = board.data
  const pages = useMemo(() => data?.pages ?? [], [data])
  const activePage = pages.find((p) => p.slug === pageSlug) ?? pages[0]
  const canEdit = data ? ['edit', 'act', 'owner'].includes(data.permission) && !data.provisioned : false
  const canAct = data ? ['act', 'owner'].includes(data.permission) : false

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

  const widgets: WidgetView[] = useMemo(
    () =>
      (activePage?.widgets ?? []).map((w) => {
        const merged = w.health ? { ...w, health: { ...w.health, ...(live.health[w.id] ?? {}) } } : w
        // While the settings sheet is open, the card shows the draft.
        return draftWidget && draftWidget.id === w.id ? { ...merged, title: draftWidget.title, icon: draftWidget.icon, link: draftWidget.link } : merged
      }),
    [activePage, live.health, draftWidget],
  )

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
        theme={theme}
        onTheme={() => {
          const next = theme === 'dark' ? 'light' : 'dark'
          setTheme(next)
          applyTheme(next)
          if (user) void update({ theme: next })
        }}
        userInitial={(user?.display_name || user?.username || '?').charAt(0).toUpperCase()}
        onProfile={() => navigate('/settings')}
        boards={(boards.data ?? []).map((b) => ({ id: b.id, name: b.name, slug: b.slug }))}
        onSwitchBoard={(boardSlug) => navigate(`/b/${boardSlug}`)}
      />
      <main className="max-w-[1480px] mx-auto px-3 sm:px-4 pt-4">
        {widgets.length === 0 && (
          <div className="glass rounded-2xl p-8 text-center max-w-md mx-auto mt-10">
            <LayoutGrid className="mx-auto text-accent" size={28} />
            <h2 className="font-semibold mt-3">{t('board.empty.title')}</h2>
            <p className="text-sm text-muted mt-1">{canEdit ? t('board.empty.body') : t('board.empty.readonly')}</p>
            {canEdit && (
              <button
                className="btn btn-accent mt-4"
                onClick={() => {
                  setEditing(true)
                  setLibrary(true)
                }}
              >
                <Plus size={14} /> {t('board.addWidget')}
              </button>
            )}
          </div>
        )}
        <BoardGrid
          key={activePage.id}
          widgets={widgets}
          layouts={activePage.layouts}
          data={live.data}
          series={live.series}
          editing={editing}
          canAct={canAct}
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
        boards={(boards.data ?? []).map((b) => ({ id: b.id, name: b.name, slug: b.slug }))}
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
        onClose={() => {
          setSettingsFor(null)
          setDraftWidget(null)
        }}
        onSaved={() => {
          setDraftWidget(null)
          void board.refetch()
        }}
        onDeleted={() => {
          setSettingsFor(null)
          setDraftWidget(null)
          void board.refetch()
        }}
      />
      <BoardSettingsSheet
        open={boardSettings}
        board={data}
        boards={boards.data ?? []}
        canEdit={canEdit}
        onPreview={setPreviewBackground}
        onClose={() => {
          setBoardSettings(false)
          setPreviewBackground(null)
        }}
        onChanged={() => void Promise.all([board.refetch(), boards.refetch()])}
      />
      <NoticeDrawer />
      <CommandPalette open={palette} onClose={() => setPalette(false)} boards={boards.data ?? []} widgets={widgets} actions={allActions} onAction={onAction} />
      <WhatsNewDialog />

      <Confirm
        open={pending !== null}
        title={pending ? `${pending.action.label}?` : ''}
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
            void import('../api/client').then(({ del }) => del(`/widgets/${id}`).then(() => board.refetch()))
          }
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
