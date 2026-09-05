import { defineConfig } from 'vitest/config'
import { loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { VitePWA } from 'vite-plugin-pwa'

// Where the API lives during development. NEXDECK_API overrides it, from the
// environment or from a gitignored .env.local next to this file, when the
// backend runs on another port than 8000.
const fileEnv = loadEnv(process.env.NODE_ENV ?? 'development', process.cwd(), 'NEXDECK_')
const apiTarget = process.env.NEXDECK_API || fileEnv.NEXDECK_API || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: 'autoUpdate',
      strategies: 'injectManifest',
      srcDir: 'src',
      filename: 'sw.ts',
      injectRegister: 'auto',
      manifest: {
        name: 'nexdeck',
        short_name: 'nexdeck',
        description: 'The live homelab dashboard.',
        theme_color: '#0a0d12',
        background_color: '#0a0d12',
        display: 'standalone',
        start_url: '/',
        icons: [
          { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icon-512.png', sizes: '512x512', type: 'image/png' },
          { src: '/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      injectManifest: {
        globPatterns: ['**/*.{js,css,html,svg,woff2}'],
        maximumFileSizeToCacheInBytes: 4 * 1024 * 1024,
      },
      devOptions: { enabled: false },
    }),
  ],
  build: {
    manifest: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules')) return 'vendor'
          return undefined
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    exclude: ['node_modules/**', 'e2e/**', 'dist/**'],
  },
  server: {
    port: 5176,
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true },
      '/k/': { target: apiTarget, changeOrigin: true, bypass: (req) => (req.headers.accept?.includes('text/html') ? '/index.html' : undefined) },
    },
  },
})
