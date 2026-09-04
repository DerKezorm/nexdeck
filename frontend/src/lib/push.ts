import { del, get, post } from '../api/client'

function urlBase64ToUint8Array(base64: string): Uint8Array {
  const padding = '='.repeat((4 - (base64.length % 4)) % 4)
  const normalised = (base64 + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = window.atob(normalised)
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)))
}

export function pushSupported(): boolean {
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
}

export async function currentSubscription(): Promise<PushSubscription | null> {
  if (!pushSupported()) return null
  const registration = await navigator.serviceWorker.getRegistration()
  return (await registration?.pushManager.getSubscription()) ?? null
}

/** Ask for permission, subscribe at the push service and register with nexdeck. */
export async function subscribePush(): Promise<void> {
  if (!pushSupported()) throw new Error('unsupported')
  const permission = await Notification.requestPermission()
  if (permission !== 'granted') throw new Error('denied')
  const registration = (await navigator.serviceWorker.getRegistration()) ?? (await navigator.serviceWorker.register('/sw.js'))
  await navigator.serviceWorker.ready
  const { key } = await get<{ key: string }>('/push/key')
  const subscription = await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(key) as BufferSource })
  await post('/push/subscribe', { subscription: subscription.toJSON() })
}

export async function unsubscribePush(): Promise<void> {
  const subscription = await currentSubscription()
  if (!subscription) return
  await del('/push/subscribe', { endpoint: subscription.endpoint })
  await subscription.unsubscribe()
}
