/**
 * The sounds a skin gives its parts: a short synth tone when one is pressed.
 *
 * Off unless the account switched them on, never on a guarded page or inside
 * a guarded dialog, and no audio files: a tone is a wave, two pitches, a length
 * and a volume of at most 0.2 (backend/app/skins/schema.py), played the way the
 * timer card beeps (components/TimeCards.tsx).
 */
import { GUARD } from './guard'
import type { CompiledSkin, SkinSound } from './wear'

let listening: ((event: PointerEvent) => void) | null = null
let context: AudioContext | null = null

export function play(sound: SkinSound): void {
  try {
    context ??= new AudioContext()
    const now = context.currentTime
    const oscillator = context.createOscillator()
    const gain = context.createGain()
    oscillator.type = sound.wave
    oscillator.frequency.setValueAtTime(sound.from, now)
    oscillator.frequency.exponentialRampToValueAtTime(sound.to, now + sound.ms / 1000)
    gain.gain.setValueAtTime(Math.min(sound.volume, 0.2), now)
    gain.gain.exponentialRampToValueAtTime(0.001, now + sound.ms / 1000)
    oscillator.connect(gain).connect(context.destination)
    oscillator.start(now)
    oscillator.stop(now + sound.ms / 1000)
  } catch {
    // No audio in this browser: a skin is still a skin without its sounds.
  }
}

/** Listen for presses on the parts that have a sound; null stops listening. */
export function listenForPresses(compiled: CompiledSkin | null): void {
  if (listening) document.removeEventListener('pointerdown', listening, true)
  listening = null
  if (!compiled?.presses.length) return
  listening = (event: PointerEvent) => {
    const target = event.target instanceof Element ? event.target : null
    if (!target || document.documentElement.hasAttribute(GUARD) || target.closest(`[${GUARD}]`)) return
    for (const press of compiled.presses) {
      if (target.closest(press.selectors.join(', ')) && compiled.sounds[press.sound]) {
        play(compiled.sounds[press.sound])
        return
      }
    }
  }
  document.addEventListener('pointerdown', listening, true)
}
