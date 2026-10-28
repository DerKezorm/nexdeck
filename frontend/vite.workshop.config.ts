import { readFileSync } from 'node:fs'

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The page that draws one card with the renderers of nexdeck, for the workshop repository's pictures
// (backend/tools/workshop_kit.py builds it). Its own build, with no service worker, relative paths
// and a single entry.
const version = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8')).version as string

export default defineConfig({
  base: './',
  define: { __NEXDECK_VERSION__: JSON.stringify(version) },
  plugins: [react(), tailwindcss()],
  build: {
    rollupOptions: { input: 'workshop-preview.html' },
  },
})
