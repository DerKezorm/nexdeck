/// <reference lib="webworker" />
/**
 * The service worker: precaches the app shell, serves it offline, and shows
 * Web Push notifications. No workbox runtime, on purpose: the whole thing is
 * eighty lines.
 */
declare const self: ServiceWorkerGlobalScope & { __WB_MANIFEST: { url: string; revision: string | null }[] }

const MANIFEST = self.__WB_MANIFEST || []
const CACHE = 'nexdeck-shell-v1'

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(MANIFEST.map((entry) => entry.url))).then(() => self.skipWaiting()),
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  )
})

self.addEventListener('fetch', (event) => {
  const request = event.request
  if (request.method !== 'GET') return
  const url = new URL(request.url)
  if (url.pathname.startsWith('/api/')) return
  if (request.mode === 'navigate') {
    event.respondWith(fetch(request).catch(() => caches.match('/index.html').then((r) => r ?? Response.error())))
    return
  }
  event.respondWith(
    caches.match(request).then((cached) => cached ?? fetch(request).then((response) => {
      if (response.ok && url.origin === self.location.origin) {
        const copy = response.clone()
        caches.open(CACHE).then((cache) => cache.put(request, copy))
      }
      return response
    })),
  )
})

self.addEventListener('push', (event) => {
  let payload: { title?: string; body?: string; url?: string; tag?: string } = {}
  try {
    payload = event.data?.json() ?? {}
  } catch {
    payload = { title: 'nexdeck', body: event.data?.text() }
  }
  event.waitUntil(
    self.registration.showNotification(payload.title || 'nexdeck', {
      body: payload.body || '',
      tag: payload.tag,
      icon: '/icon-192.png',
      badge: '/icon-192.png',
      data: { url: payload.url || '/' },
    }),
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const target = (event.notification.data?.url as string) || '/'
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if ('focus' in client) {
          client.navigate(target)
          return client.focus()
        }
      }
      return self.clients.openWindow(target)
    }),
  )
})
