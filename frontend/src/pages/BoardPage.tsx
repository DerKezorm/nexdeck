import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, LayoutGrid, Plus, Settings2 } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useParams } from 'react-router-dom'

import { ApiError, get, post, put } from '../api/client'
import type { BoardSummary, BoardWithLive } from '../api/types'
import { ActionSheet, type PendingAction } from '../components/ActionSheet'
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
import { nextPreview, type HeldPreview } from '../lib/previewHold'
import { startingValue, unanswered } from '../lib/unanswered'
import { sameSettings } from '../lib/savedYet'
import type { Action, Breakpoint, LayoutItem, WidgetView } from '../lib/types'
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
  // ⚠️ Subscribed piece by piece on purpose. `useLive()` without a selector
  // re-renders this page, and with it every card, whenever anything in the
  // store changes: a health result used to rebuild the widget list, and a
  // widget tick used to rebuild the actions for the palette.
  const liveData = useLive((state) => state.data)
  const liveSeries = useLive((state) => state.series)
  const liveHealth = useLive((state) => state.health)
  const setSnapshot = useLive((state) => state.setSnapshot)
  const setSeriesFor = useLive((state) => state.setSeries)

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
  // `values` holds what the sheet has had picked or typed for the blanks the
  // action left; the action itself stays as the card offered it.
  const [pending, setPending] = useState<PendingAction | null>(null)
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
  const [previewData, setPreviewData] = useState<HeldPreview | null>(null)

  const data = board.data
  const pages = useMemo(() => data?.pages ?? [], [data])
  const activePage = pages.find((p) => p.slug === pageSlug) ?? pages[0]
  const canEdit = data ? ['edit', 'act', 'owner'].includes(data.permission) && !data.provisioned : false
  const canAct = data ? ['act', 'owner'].includes(data.permission) : false
  const settings = previewSettings ?? data?.settings ?? {}

  // Snapshot and history into the live store.
  useEffect(() => {
    if (data?.live) setSnapshot(data.live)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data])
  useEffect(() => {
    if (!history.data) return
    for (const [id, series] of Object.entries(history.data)) setSeriesFor(Number(id), series)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [history.data])

  // What the server last told us each page stands at. Sent with every save,
  // so a browser that was arranging an older version is refused instead of
  // quietly putting the other person's work back.
  const versions = useRef<Record<number, number>>({})
  useEffect(() => {
    for (const page of pages) {
      if (typeof page.layout_version === 'number') versions.current[page.id] = page.layout_version
    }
  }, [pages])

  useStream({
    board: slug,
    enabled: Boolean(data),
    onBoardChanged: () => void board.refetch(),
    onConnected: () => void board.refetch(),
    onLayout: (payload) => {
      // Somebody else saved this page. Take their version along, so the next
      // save from this browser starts from where the page really is.
      const moved = payload as { page_id: number; layouts: unknown; version?: number }
      if (typeof moved.version === 'number') versions.current[moved.page_id] = moved.version
      queryClient.setQueryData<BoardWithLive>(['board', slug], (old) =>
        old ? { ...old, pages: old.pages.map((p) => (p.id === payload.page_id ? { ...p, layouts: payload.layouts as typeof p.layouts } : p)) } : old,
      )
    },
  })

  // Layout saving, debounced per page.
  //
  // ⚠️ One timer for all pages meant that moving a card and then switching
  // page inside 700 ms cancelled the save and never made another: the change
  // was on screen, gone after a reload, and nothing said so. A timer per page
  // is the fix, and switching away flushes what is pending rather than
  // dropping it.
  const timers = useRef<Record<number, number>>({})
  const draft = useRef<Record<number, Partial<Record<Breakpoint, LayoutItem[]>>>>({})
  const save = useCallback(
    (pageId: number) => {
      const body = draft.current[pageId]
      if (!body) return
      delete draft.current[pageId]
      void put<{ version?: number }>(`/pages/${pageId}/layouts`, { ...body, version: versions.current[pageId] })
        .then((answer) => {
          if (typeof answer?.version === 'number') versions.current[pageId] = answer.version
        })
        .catch((failure) => {
          if (failure instanceof ApiError && failure.code === 'layout_moved_on') {
            setToast({ text: failure.message, level: 'info' })
            return
          }
          setToast({ text: t('board.saveFailed'), level: 'error' })
        })
    },
    [t],
  )
  const onLayoutChange = useCallback(
    (breakpoint: Breakpoint, layout: LayoutItem[]) => {
      if (!activePage) return
      const pageId = activePage.id
      draft.current[pageId] = { ...(draft.current[pageId] ?? {}), [breakpoint]: layout }
      window.clearTimeout(timers.current[pageId])
      timers.current[pageId] = window.setTimeout(() => save(pageId), 700)
    },
    [activePage, save],
  )
  // Leaving a page, or the board, writes what is still waiting.
  const flush = useCallback(() => {
    for (const [pageId, timer] of Object.entries(timers.current)) {
      window.clearTimeout(timer)
      save(Number(pageId))
    }
    timers.current = {}
  }, [save])
  useEffect(() => flush, [flush, activePage?.id])

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
        const merged = w.health ? { ...w, health: { ...w.health, ...(liveHealth[w.id] ?? {}) } } : w
        // While the settings sheet is open, the card shows the draft.
        return draftWidget && draftWidget.id === w.id ? { ...merged, title: draftWidget.title, icon: draftWidget.icon, link: draftWidget.link, options: draftWidget.options } : merged
      }),
    [activePage, liveHealth, draftWidget],
  )
  /**
   * True between a save and the moment the board really carries the new
   * options.
   *
   * ⚠️ The draft is what the card shows while the sheet is open, and closing
   * the sheet dropped it at once. For a card the server refreshes, the held
   * preview covered the gap; for one that draws itself from its own options,
   * a clock or a note, there is no preview to hold, so the card fell back to
   * the copy the board query still had, which is the one from before the
   * save. That is the fault this page keeps being reported for, and this is
   * the last corner of it.
   *
   * ⚠️ Released by comparing, not by waiting for a refetch to resolve. A
   * board fetch already in flight when Save is pressed answers with what the
   * server had **before** the save, and `refetch()` hands that in-flight
   * promise back rather than starting a new request. Waiting on it therefore
   * cleared the draft against stale data, which is exactly the moment the
   * card blinked back to its old self. The stream makes it likely: saving a
   * widget makes the server send a board event, so two fetches are in the air
   * at once anyway.
   */
  const [awaitingSave, setAwaitingSave] = useState(false)

  // The draft a save left on the card goes when the board really carries it,
  // and after twenty seconds whatever happened, so a card cannot be left
  // showing something the server never took.
  useEffect(() => {
    if (!awaitingSave || !draftWidget) return
    // ⚠️ Against what the server sent, not against `widgets`: that list has
    // the draft merged into it already, so comparing there is comparing the
    // draft with itself and always says yes.
    const carried = (activePage?.widgets ?? []).find((one) => one.id === draftWidget.id)
    if (carried && sameSettings(carried, draftWidget)) {
      setAwaitingSave(false)
      setDraftWidget(null)
      return
    }
    const id = window.setTimeout(() => {
      setAwaitingSave(false)
      setDraftWidget(null)
    }, 20_000)
    return () => window.clearTimeout(id)
  }, [activePage, draftWidget, awaitingSave])

  // Data fetched with draft options replaces the live data of that one card.
  const gridData = useMemo(() => (previewData ? { ...liveData, [previewData.id]: previewData.data } : liveData), [liveData, previewData])
  useEffect(() => {
    if (previewData?.holdUntilChange === undefined) return
    const current = liveData[previewData.id]?.updated_at ?? 0
    if (current !== previewData.holdUntilChange) setPreviewData(null)
  }, [liveData, previewData])
  useEffect(() => {
    if (previewData?.holdUntilChange === undefined) return
    const id = window.setTimeout(() => setPreviewData(null), 20_000)
    return () => window.clearTimeout(id)
  }, [previewData])

  const runAction = async (widgetId: number, action: Action) => {
    try {
      const result = await post<{ message: string }>(`/widgets/${widgetId}/actions/${action.id}`, { params: action.params ?? {} })
      // ⚠️ Adapters answer in English, the way they write every label, and the
      // card translates those by wording. The one sentence a button produces
      // was the exception: "Removed." stood in English on a German board, in
      // the one place the eye goes right after a press. A sentence the service
      // itself wrote back has no entry and stays as it came, which is right:
      // it is MeTube speaking, not nexdeck.
      setToast({ text: tLabel(result.message), level: 'ok' })
    } catch (failure) {
      setToast({ text: failure instanceof ApiError ? failure.message : t('errors.network'), level: 'error' })
    }
  }
  // ⚠️ Stable, all four of them. A new function on every render makes every
  // card's props new, and then no amount of memoising below helps: one card's
  // data arriving redrew all thirty.
  const runActionRef = useRef(runAction)
  useEffect(() => {
    runActionRef.current = runAction
  })
  const onAction = useCallback((widgetId: number, action: Action) => {
    // ⚠️ A blank nobody filled in opens the sheet, whether or not the action
    // asked for a confirmation. Sent as it is, the server refuses it, and the
    // toast would be the first anybody heard that there was a choice to make.
    const open = unanswered(action)
    if (action.confirm || open.length) {
      setPending({ widgetId, action, values: Object.fromEntries(open.map((blank) => [blank.name, startingValue(blank)])) })
    } else void runActionRef.current(widgetId, action)
  }, [])
  const onRefresh = useCallback((id: number) => void post(`/widgets/${id}/refresh`), [])
  const onSettings = useCallback((id: number) => setSettingsFor(id), [])
  const onRemove = useCallback((id: number) => setRemoving(id), [])

  const allActions = useMemo(() => {
    const list: { widget: WidgetView; action: Action }[] = []
    if (!canAct) return list
    for (const widget of widgets) {
      for (const action of liveData[widget.id]?.actions ?? []) list.push({ widget, action })
    }
    return list
  }, [widgets, liveData, canAct])


  const closeWidgetSettings = () => {
    setSettingsFor(null)
    if (!awaitingSave) setDraftWidget(null)
    // ⚠️ A held preview outlives the sheet. Saving closes the sheet, and this
    // ran a tick after `onSaved` had set the hold and wiped it again: the card
    // dropped straight back to the collector's last answer, which still had
    // the old options. On screen that is "I change something, it shows, it
    // jumps back, and only F5 gives me the result."
    setPreviewData((current) => nextPreview(current, current?.id ?? 0, null))
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
          series={liveSeries}
          editing={editing}
          canAct={canAct}
          autoCompact={Boolean(settings.compact)}
          onLayoutChange={onLayoutChange}
          onAction={onAction}
          onRefresh={onRefresh}
          onSettings={onSettings}
          onRemove={onRemove}
        />
      </main>

      {/* ⚠️ Four buttons with their words in a row that cannot wrap: on a
          phone the bar was wider than the screen, so the Done button sat off
          the edge and there was no way out of edit mode. Below `sm` the words
          step aside and the icons carry the meaning, with the name on the
          button for anything that reads it out. */}
      {editing && (
        <div className="fixed bottom-20 md:bottom-6 left-1/2 -translate-x-1/2 z-40 max-w-[calc(100vw-1rem)] glass-strong rounded-full px-2 py-1.5 flex items-center gap-1 shadow-2xl">
          <button className="btn border-0 bg-transparent" onClick={() => setLibrary(true)} aria-label={t('board.addWidget')}>
            <Plus size={15} /> <span className="hidden sm:inline">{t('board.addWidget')}</span>
          </button>
          <button className="btn border-0 bg-transparent" onClick={() => setNewPage(true)} aria-label={t('board.addPage')}>
            <Plus size={15} /> <span className="hidden sm:inline">{t('board.addPage')}</span>
          </button>
          <button className="btn border-0 bg-transparent" onClick={() => setBoardSettings(true)} aria-label={t('board.settings')}>
            <Settings2 size={15} /> <span className="hidden sm:inline">{t('board.settings')}</span>
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
        pages={pages.map((page) => ({ id: page.id, name: page.name, slug: page.slug }))}
        activePage={activePage.slug}
        onPage={(slug) => navigate(`/b/${data.slug}/${slug}`)}
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
        onPreviewData={(id, preview) => setPreviewData((current) => nextPreview(current, id, preview))}
        onClose={closeWidgetSettings}
        onSaved={() => {
          setAwaitingSave(true)
          setPreviewData((current) => (current ? { ...current, holdUntilChange: liveData[current.id]?.updated_at ?? 0 } : null))
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

      <ActionSheet
        pending={pending}
        onChange={setPending}
        onCancel={() => setPending(null)}
        onRun={(widgetId, action) => {
          void runAction(widgetId, action)
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
