/**
 * A guide that names a step without a text would print the key on screen, and
 * a service without a logo would stand there as a grey box. Both are the kind
 * of thing nobody notices until a user does.
 */
import en from '../../i18n/en.json'
import { GUIDES, KIND_ICONS } from './channelGuides'

const guides = en.channels.guide as Record<string, Record<string, string>>

describe('channel guides', () => {
  it('cover a few services at all', () => {
    expect(Object.keys(GUIDES).length).toBeGreaterThan(4)
  })

  it('have a text for every step', () => {
    const missing: string[] = []
    let checked = 0
    for (const [kind, steps] of Object.entries(GUIDES)) {
      for (const step of steps) {
        checked += 1
        if (!guides[kind]?.[step.key]) missing.push(`${kind}.${step.key}`)
      }
    }
    expect(checked).toBeGreaterThan(15)
    expect(missing, 'guide steps without a text in en.json').toEqual([])
  })

  it('have no text without a step', () => {
    const extra: string[] = []
    for (const [kind, steps] of Object.entries(guides)) {
      for (const key of Object.keys(steps)) {
        if (!GUIDES[kind]?.some((step) => step.key === key)) extra.push(`${kind}.${key}`)
      }
    }
    expect(extra, 'texts that no step shows').toEqual([])
  })

  it('give every service with a guide a logo', () => {
    const without = Object.keys(GUIDES).filter((kind) => !KIND_ICONS[kind])
    expect(without, 'services without a logo').toEqual([])
  })

  it('point their links somewhere', () => {
    for (const steps of Object.values(GUIDES)) {
      for (const step of steps) {
        for (const link of step.links ?? []) {
          expect(link.href).toMatch(/^https:\/\//)
          expect(link.label.length).toBeGreaterThan(2)
        }
      }
    }
  })
})
