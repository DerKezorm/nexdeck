/**
 * The camera card: a snapshot that renews itself through the server, and live
 * video that hands back to snapshots when the browser cannot play it.
 */
import { act, render, screen } from '@testing-library/react'
import { vi } from 'vitest'

import type { WidgetView } from '../lib/types'
import { CameraCard } from './CameraCard'

const player = vi.hoisted(() => ({ supported: false, handlers: {} as Record<string, () => void>, sources: [] as Record<string, unknown>[] }))
vi.mock('mpegts.js', () => ({
  default: {
    isSupported: () => player.supported,
    Events: { ERROR: 'error' },
    createPlayer: (source: Record<string, unknown>) => {
      player.sources.push(source)
      return {
        on: (event: string, handler: () => void) => {
          player.handlers[event] = handler
        },
        attachMediaElement: () => undefined,
        load: () => player.handlers.error?.(),
        play: () => Promise.resolve(),
        destroy: () => undefined,
      }
    },
  },
}))

const widget: WidgetView = { id: 9, kind: 'reolink.camera', title: 'Front door', icon: 'reolink', link: '', renderer: 'camera', options: {}, integration_id: 1, refresh_seconds: null }
const item = { title: 'Front door', subtitle: '', status: 'ok', art: 'proxy:/snap/1' }

describe('CameraCard', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('shows the snapshot through the server and renews it', () => {
    vi.useFakeTimers()
    render(<CameraCard widget={widget} data={{ status: 'ok', items: [item], meta: { mode: 'snapshot', live: false, interval: 10 } }} />)
    const image = screen.getByTestId('snapshot')
    const before = image.getAttribute('src') ?? ''
    expect(before).toMatch(/^\/api\/v1\/widgets\/9\/image\?path=%2Fsnap%2F1&t=\d+$/)
    act(() => {
      vi.advanceTimersByTime(10_000)
    })
    expect(image.getAttribute('src')).not.toBe(before)
    expect(screen.getByText('Front door')).toBeInTheDocument()
  })

  it('falls back to snapshots when the browser cannot play live video', async () => {
    render(<CameraCard widget={widget} data={{ status: 'ok', items: [item], meta: { mode: 'live', live: true, interval: 30 } }} />)
    expect(screen.getByTestId('live')).toBeInTheDocument()
    expect(await screen.findByTestId('snapshot', {}, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.getByText('Live video needs a newer browser; showing snapshots.')).toBeInTheDocument()
  })

  it('hands back to snapshots when the stream breaks, without audio, and retries later', async () => {
    player.supported = true
    vi.useFakeTimers({ shouldAdvanceTime: true })
    render(<CameraCard widget={widget} data={{ status: 'ok', items: [item], meta: { mode: 'live', live: true, interval: 30 } }} />)
    expect(await screen.findByTestId('snapshot', {}, { timeout: 3000 })).toBeInTheDocument()
    expect(screen.getByText('Live video stopped; showing snapshots and retrying.')).toBeInTheDocument()
    expect(player.sources.at(-1)).toMatchObject({ type: 'flv', isLive: true, hasAudio: false, url: '/api/v1/widgets/9/stream' })
    act(() => {
      vi.advanceTimersByTime(30_000)
    })
    expect(screen.getByTestId('live')).toBeInTheDocument()
    player.supported = false
  })

  it('says when there is no camera', () => {
    render(<CameraCard widget={widget} data={{ status: 'ok', items: [], meta: { empty: 'No cameras' } }} />)
    expect(screen.getByText('No cameras')).toBeInTheDocument()
  })
})
