/**
 * What this browser plays, asked of the browser rather than guessed from its name.
 *
 * The server passes the list on to the media server, which hands out the file
 * as it is when its codec is on the list and converts it otherwise. A codec
 * that is left off costs a conversion; one that is claimed wrongly costs a
 * track that does not play, so only a clear yes counts.
 */

/** The names the server knows, with what the browser is asked about each. */
const PROBES: [string, string][] = [
  ['flac', 'audio/flac'],
  ['mp3', 'audio/mpeg'],
  ['aac', 'audio/mp4; codecs="mp4a.40.2"'],
  ['alac', 'audio/mp4; codecs="alac"'],
  ['opus', 'audio/ogg; codecs="opus"'],
  ['vorbis', 'audio/ogg; codecs="vorbis"'],
  ['wav', 'audio/wav'],
]

type Probe = Pick<HTMLMediaElement, 'canPlayType'>

let remembered: string[] | null = null

export function playableFormats(probe?: Probe): string[] {
  if (!probe && remembered) return remembered
  const element: Probe | null = probe ?? (typeof document !== 'undefined' ? document.createElement('audio') : null)
  if (!element) return ['mp3']
  const found = PROBES.filter(([, type]) => {
    const answer = element.canPlayType(type)
    // "maybe" is what every browser says about a container it knows without
    // being sure of the codec; for MP3 and FLAC that is the whole answer.
    return answer === 'probably' || answer === 'maybe'
  }).map(([name]) => name)
  const result = found.length ? found : ['mp3']
  if (!probe) remembered = result
  return result
}

/**
 * Whether the browser plays HLS by itself, which is Safari.
 *
 * ⚠️ Only then is converted sound asked for as HLS. Measured on 11.09.2026:
 * converted sound comes as MP3 without a length and without Range from both
 * Jellyfin and Plex, and Safari will not play a stream it cannot ask for a
 * range of. Chrome and Firefox play that stream fine and do not need HLS.
 */
export function playsHlsNatively(probe?: Probe): boolean {
  const element: Probe | null = probe ?? (typeof document !== 'undefined' ? document.createElement('audio') : null)
  return Boolean(element && element.canPlayType('application/vnd.apple.mpegurl'))
}

let volumeSettable: boolean | null = null

/**
 * Whether a page may set the volume at all.
 *
 * ⚠️ Not on an iPhone or an iPad: Safari there keeps `volume` at 1 whatever
 * is written to it, and the buttons on the side decide. A slider that moves
 * and changes nothing is worse than none, so the player shows none there.
 */
export function canSetVolume(): boolean {
  if (volumeSettable !== null) return volumeSettable
  try {
    const probe = document.createElement('audio')
    probe.volume = 0.5
    volumeSettable = Math.abs(probe.volume - 0.5) < 0.01
  } catch {
    volumeSettable = false
  }
  return volumeSettable
}

/** For the tests: forget what this browser said. */
export function forgetFormats(): void {
  remembered = null
  volumeSettable = null
}
