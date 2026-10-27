import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { lazy, Suspense, useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'

import { AppBarFrame } from './components/AppBar'
import { AssistantHost } from './components/assistant/AssistantHost'
import { BackgroundLayer } from './components/BackgroundLayer'
import { ErrorBoundary } from './components/ErrorBoundary'
import { NoticeToast } from './components/NoticeDrawer'
import { PlayerHost } from './components/player/PlayerHost'
import { Spinner } from './components/ui'
import { setLanguage, storedLanguage } from './i18n'
import { applyAppearance, type Appearance } from './lib/appearance'
import { loadBrand, useBrand } from './lib/brand'
import { BoardPage } from './pages/BoardPage'
import { HomeRedirect } from './pages/HomeRedirect'
import { LoginPage } from './pages/LoginPage'
import { ResetPage } from './pages/ResetPage'
import { SetupPage } from './pages/SetupPage'
import { get } from './api/client'
import { useAuth } from './stores/auth'

const KioskPage = lazy(() => import('./pages/KioskPage').then((m) => ({ default: m.KioskPage })))
const SettingsPage = lazy(() => import('./pages/settings/SettingsPage').then((m) => ({ default: m.SettingsPage })))
const SystemPage = lazy(() => import('./pages/settings/SystemPage').then((m) => ({ default: m.SystemPage })))
const NoticesPage = lazy(() => import('./pages/NoticesPage').then((m) => ({ default: m.NoticesPage })))
const ChroniclePage = lazy(() => import('./pages/ChroniclePage').then((m) => ({ default: m.ChroniclePage })))
const DiagnosisPage = lazy(() => import('./pages/DiagnosisPage').then((m) => ({ default: m.DiagnosisPage })))
const PreviewPage = lazy(() => import('./pages/PreviewPage').then((m) => ({ default: m.PreviewPage })))
const CardEditorPage = lazy(() => import('./pages/cardEditor/CardEditorPage').then((m) => ({ default: m.CardEditorPage })))
const IntegrationEditorPage = lazy(() => import('./pages/integrationEditor/IntegrationEditorPage').then((m) => ({ default: m.IntegrationEditorPage })))

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 5000 } } })

function Loading() {
  return (
    <div className="min-h-full flex items-center justify-center">
      <Spinner />
    </div>
  )
}

/** Routes that need a signed-in user; the wizard and sign-in take over otherwise. */
function Guard({ children }: { children: React.ReactNode }) {
  const { user, status, loading } = useAuth()
  const location = useLocation()
  if (loading) return <Loading />
  if (status?.needs_setup) return <Navigate to="/setup" replace />
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return <>{children}</>
}

/**
 * The look the operator chose, painted on once the browser is signed in.
 *
 * Signed out, the sign-in page and the first start are drawn in the part of
 * the look the brand carries (theme, cards, type, no style sheet), so an
 * installation in 1984 greets in 1984. A wall display paints its own.
 */
function Look() {
  const user = useAuth((s) => s.user)
  const open = useBrand((s) => s.look)
  useEffect(() => {
    if (user || !open || window.location.pathname.startsWith('/k/')) return
    applyAppearance(open)
  }, [user, open])
  useEffect(() => {
    if (!user) return
    let dropped = false
    void get<Appearance>('/settings/appearance')
      .then((look) => {
        if (!dropped) applyAppearance(look)
      })
      .catch(() => undefined)
    return () => {
      dropped = true
    }
  }, [user])
  return null
}

export function App() {
  const refresh = useAuth((s) => s.refresh)
  useEffect(() => {
    void setLanguage(storedLanguage()).then(() => refresh())
    // Signed in or not: the sign-in page and the tab carry the installation's name.
    void loadBrand()
  }, [refresh])
  return (
    <QueryClientProvider client={queryClient}>
      <Look />
      {/* ⚠️ Around everything and outside Suspense, so it also catches a lazy
          chunk that is no longer on the server after a deploy: without it that
          unmounts the whole tree and leaves a white page with nothing on it,
          no message and no button, on a wall display nobody is standing at. */}
      <ErrorBoundary>
      <BrowserRouter>
        {/* Outside Suspense and the routes: the bar stands while a page loads
            and when one page gives way to the next (issues #27, #40). */}
        <AppBarFrame>
        <Suspense fallback={<Loading />}>
          <Routes>
            <Route path="/setup" element={<SetupPage />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/reset/:token" element={<ResetPage />} />
            {/* ⚠️ The token is optional: the page takes it out of the address,
                and a reloaded display comes back in on /k alone. */}
            <Route path="/k/:token?" element={<KioskPage />} />
            <Route path="/preview" element={<PreviewPage />} />
            <Route
              path="/"
              element={
                <Guard>
                  <HomeRedirect />
                </Guard>
              }
            />
            <Route
              path="/b/:slug/:page?"
              element={
                <Guard>
                  <BoardPage />
                </Guard>
              }
            />
            <Route
              path="/settings/*"
              element={
                <Guard>
                  <SettingsPage />
                </Guard>
              }
            />
            {/* The card editor is a page of its own, not one inside System (KARTEN-9). */}
            <Route
              path="/system/custom-cards/new"
              element={
                <Guard>
                  <CardEditorPage />
                </Guard>
              }
            />
            <Route
              path="/system/custom-cards/:slug/edit"
              element={
                <Guard>
                  <CardEditorPage />
                </Guard>
              }
            />
            <Route
              path="/system/custom-cards/integrations/new"
              element={
                <Guard>
                  <IntegrationEditorPage />
                </Guard>
              }
            />
            <Route
              path="/system/custom-cards/integrations/:short/edit"
              element={
                <Guard>
                  <IntegrationEditorPage />
                </Guard>
              }
            />
            <Route
              path="/system/*"
              element={
                <Guard>
                  <SystemPage />
                </Guard>
              }
            />
            <Route
              path="/notices"
              element={
                <Guard>
                  <NoticesPage />
                </Guard>
              }
            />
            <Route
              path="/chronicle"
              element={
                <Guard>
                  <ChroniclePage />
                </Guard>
              }
            />
            <Route
              path="/diagnosis"
              element={
                <Guard>
                  <DiagnosisPage />
                </Guard>
              }
            />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
        </AppBarFrame>
        <NoticeToast />
        {/* Beside the routes, not inside a page: music carries on when the board changes. */}
        <PlayerHost />
        {/* Beside the routes as well: a conversation carries on from board to board. */}
        <AssistantHost />
      </BrowserRouter>
      </ErrorBoundary>
    </QueryClientProvider>
  )
}

export { BackgroundLayer }
