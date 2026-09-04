import { PreviewPage } from './pages/PreviewPage'

// During the design preview the app renders the demo board straight away.
// Service logos come from the CDN here; the real app proxies them.
;(globalThis as { __NEXDECK_ICON_BASE__?: string }).__NEXDECK_ICON_BASE__ = 'https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/svg/'

export function App() {
  return <PreviewPage />
}
