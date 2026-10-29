import { lazy, StrictMode, Suspense } from 'react'
import { createRoot } from 'react-dom/client'

import './styles/app.css'
import { App } from './App'
import { recallLook } from './lib/appearance'
import { bearTranslatedPages } from './lib/translatedPage'
import { followTheme, keptPlan } from './lib/themeMode'

// The stage of the skin editor is a page without the app: no account, no look of its own, no stream.
// The editor in the window around it hands it everything it shows (pages/skins/SkinStage.tsx).
const STAGE = window.location.pathname.startsWith('/skin-stage')

// ?theme=light forces a mode, useful for screenshots and kiosk links.
const forced = new URLSearchParams(window.location.search).get('theme')
if (forced === 'light' || forced === 'dark') (globalThis as { __NEXDECK_FORCED_THEME__?: string }).__NEXDECK_FORCED_THEME__ = forced
// The plan this browser followed last, so the page starts in the right brightness before the account
// answers, and the sign-in page follows the system or the clock as well.
if (!STAGE) {
  followTheme(keptPlan(), { remember: false })
  // The look this browser saw last, so 1984 does not start as glass and turn into itself a moment later.
  recallLook()
}

// A page the browser translated must not take React down with it (nexbase #job-260).
bearTranslatedPages()
const SkinStage = lazy(() => import('./pages/skins/SkinStage').then((m) => ({ default: m.SkinStage })))
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {STAGE ? (
      <Suspense fallback={null}>
        <SkinStage />
      </Suspense>
    ) : (
      <App />
    )}
  </StrictMode>,
)
