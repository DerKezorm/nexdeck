import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import './styles/app.css'
import { App } from './App'
import { bearTranslatedPages } from './lib/translatedPage'
import { followTheme, keptPlan } from './lib/themeMode'

// ?theme=light forces a mode, useful for screenshots and kiosk links.
const forced = new URLSearchParams(window.location.search).get('theme')
if (forced === 'light' || forced === 'dark') (globalThis as { __NEXDECK_FORCED_THEME__?: string }).__NEXDECK_FORCED_THEME__ = forced
// The plan this browser followed last, so the page starts in the right brightness before the account
// answers, and the sign-in page follows the system or the clock as well.
followTheme(keptPlan(), { remember: false })

// A page the browser translated must not take React down with it (nexbase #job-260).
bearTranslatedPages()
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
