import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import './styles/app.css'
import { App } from './App'

const stored = (() => {
  try {
    return localStorage.getItem('nexdeck.theme')
  } catch {
    return null
  }
})()
// ?theme=light forces a mode, useful for screenshots and kiosk links.
const forced = new URLSearchParams(window.location.search).get('theme')
if (forced === 'light' || forced === 'dark') (globalThis as { __NEXDECK_FORCED_THEME__?: string }).__NEXDECK_FORCED_THEME__ = forced
document.documentElement.dataset.theme = forced === 'light' || (forced !== 'dark' && stored === 'light') ? 'light' : 'dark'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
