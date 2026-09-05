import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { lazy, Suspense, useEffect } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'

import { BackgroundLayer } from './components/BackgroundLayer'
import { NoticeToast } from './components/NoticeDrawer'
import { Spinner } from './components/ui'
import { setLanguage, storedLanguage } from './i18n'
import { BoardPage } from './pages/BoardPage'
import { HomeRedirect } from './pages/HomeRedirect'
import { LoginPage } from './pages/LoginPage'
import { SetupPage } from './pages/SetupPage'
import { useAuth } from './stores/auth'

const KioskPage = lazy(() => import('./pages/KioskPage').then((m) => ({ default: m.KioskPage })))
const SettingsPage = lazy(() => import('./pages/settings/SettingsPage').then((m) => ({ default: m.SettingsPage })))
const SystemPage = lazy(() => import('./pages/settings/SystemPage').then((m) => ({ default: m.SystemPage })))
const NoticesPage = lazy(() => import('./pages/NoticesPage').then((m) => ({ default: m.NoticesPage })))
const PreviewPage = lazy(() => import('./pages/PreviewPage').then((m) => ({ default: m.PreviewPage })))

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

export function App() {
  const refresh = useAuth((s) => s.refresh)
  useEffect(() => {
    void setLanguage(storedLanguage()).then(() => refresh())
  }, [refresh])
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Suspense fallback={<Loading />}>
          <Routes>
            <Route path="/setup" element={<SetupPage />} />
            <Route path="/login" element={<LoginPage />} />
            <Route path="/k/:token" element={<KioskPage />} />
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
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
        <NoticeToast />
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export { BackgroundLayer }
