/**
 * The type of the interface: set on the root, its faces fetched only for the
 * font shown, and the last choice wins over one still loading.
 */
import { FONTS, fontOf, setFont } from './fonts'

const root = () => document.documentElement

afterEach(async () => {
  await setFont('inter')
})

describe('fonts', () => {
  it('ships Inter as it always was, the system, a mono face and every one under a name of its own', () => {
    expect(FONTS[0].key).toBe('inter')
    expect(FONTS.filter((font) => font.mono).map((font) => font.key)).toEqual(['mono'])
    expect(new Set(FONTS.map((font) => font.key)).size).toBe(FONTS.length)
    expect(fontOf('comic').key).toBe('inter')
  })

  it('sets a chosen font on the root and takes it off again for the default', async () => {
    await setFont('mono')
    expect(root().style.getPropertyValue('--nd-font')).toBe("'JetBrains Mono Variable'")
    expect(root().dataset.font).toBe('mono')
    await setFont('inter')
    expect(root().style.getPropertyValue('--nd-font')).toBe('')
    expect(root().dataset.font).toBeUndefined()
  })

  it('fetches the faces of a font only when it is chosen, once', async () => {
    const geist = FONTS.find((font) => font.key === 'geist')!
    const original = geist.load
    const load = vi.fn(async () => undefined)
    geist.load = load
    try {
      await setFont('system')
      expect(load).not.toHaveBeenCalled()
      await setFont('geist')
      await setFont('inter')
      await setFont('geist')
      expect(load).toHaveBeenCalledTimes(1)
      expect(root().style.getPropertyValue('--nd-font')).toBe("'Geist Variable'")
    } finally {
      geist.load = original
    }
  })

  it('lets the last choice win over a font still loading', async () => {
    const plex = FONTS.find((font) => font.key === 'plex')!
    const original = plex.load
    let arrive = () => undefined as void
    plex.load = () => new Promise<void>((resolve) => (arrive = resolve))
    try {
      const slow = setFont('plex')
      await setFont('system')
      arrive()
      await slow
      expect(root().dataset.font).toBe('system')
    } finally {
      plex.load = original
    }
  })
})
