/**
 * A health result updates the tile's state and, when the server sends them,
 * its uptime bars; a result without bars leaves the old bars in place.
 */
import { useLive } from './live'

describe('live store health', () => {
  it('keeps the bars that arrive with a result', () => {
    const store = useLive.getState()
    store.applyHealth({ widget_id: 7, ok: true, latency_ms: 12, down_since: null, detail: 'HTTP 200', bars: [null, 1] })
    expect(useLive.getState().health[7]).toMatchObject({ last_ok: true, last_latency_ms: 12, last_error: '', bars: [null, 1] })
    store.applyHealth({ widget_id: 7, ok: false, latency_ms: 0, down_since: '2026-09-05T08:00:00Z', detail: 'ConnectError' })
    expect(useLive.getState().health[7]).toMatchObject({ last_ok: false, last_error: 'ConnectError', bars: [null, 1] })
  })

  it('ignores results without a widget', () => {
    const before = useLive.getState().health
    useLive.getState().applyHealth({ widget_id: null, ok: true, latency_ms: 1, down_since: null, detail: '' })
    expect(useLive.getState().health).toBe(before)
  })
})
