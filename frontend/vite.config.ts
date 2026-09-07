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
        // The careful split into lazy chunks was collected back up here: the
        // service worker precached everything on the first visit, 1.45 MB of
        // it. mpegts.js is 277 kB and only a camera card needs it, and nine of
        // the twelve font files are alphabets this interface has no words in.
        // They still load when something asks for them; they are just not
        // fetched before anybody has.
        globIgnores: [
          '**/mpegts-*.js',
          '**/*-cyrillic-*.woff2',
          '**/*-cyrillic-ext-*.woff2',
          '**/*-greek-*.woff2',
          '**/*-greek-ext-*.woff2',
          '**/*-vietnamese-*.woff2',
        ],
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
          // The video demuxer loads only when a live camera card is on the board; it must not ride in the vendor chunk.
          if (id.includes('mpegts.js')) return undefined
          // ⚠️ Same for the markdown pair. They are needed by exactly one of
          // the 196 cards, and the rule below would have swept them into the
          // vendor chunk however carefully the import was written: a dynamic
          // import only splits a chunk if nothing else pulls the module in.
          if (id.includes('node_modules/marked') || id.includes('node_modules/dompurify')) return undefined
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
    coverage: {
      provider: 'v8',
      reporter: ['text-summary', 'json-summary', 'html'],
      reportsDirectory: './coverage',
      // ⚠️ `include` on purpose, and wide. Without it only the files some
      // test imported are counted, so a file nobody tests at all raises the
      // number by not appearing. That is the opposite of a measurement.
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        'src/**/*.test.{ts,tsx}',
        'src/test/**',
        'src/main.tsx',
        // The service worker runs in a worker, not in jsdom; the built
        // project tests it in a real browser instead.
        'src/sw.ts',
        'src/vite-env.d.ts',
      ],
      // The floor, not a target. When it trips the tests come up; the
      // number here goes down only with a reason in the commit message.
      thresholds: { statements: 32, branches: 35, functions: 21, lines: 34 },
    },
  },
  server: {
    port: 5176,
    proxy: {
      '/api': { target: apiTarget, changeOrigin: true },
      '/k/': { target: apiTarget, changeOrigin: true, bypass: (req) => (req.headers.accept?.includes('text/html') ? '/index.html' : undefined) },
    },
  },
})
