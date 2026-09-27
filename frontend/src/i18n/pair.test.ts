/**
 * Which two languages the top bar offers. An account chooses its own pair;
 * where nobody is signed in the pair is English plus the language on screen,
 * else the browser's, else German.
 */
import { accountPair, browserLanguage, guestPair, LANGUAGES, storedLanguage } from './index'

function browserAsks(...tags: string[]) {
  vi.spyOn(navigator, 'languages', 'get').mockReturnValue(tags)
  vi.spyOn(navigator, 'language', 'get').mockReturnValue(tags[0] ?? '')
}

/** Node's own half-made localStorage hides jsdom's in this runner; a plain map stands in. */
function memoryStorage(): Storage {
  const items = new Map<string, string>()
  return {
    get length() {
      return items.size
    },
    clear: () => items.clear(),
    getItem: (key) => items.get(key) ?? null,
    key: (index) => [...items.keys()][index] ?? null,
    removeItem: (key) => void items.delete(key),
    setItem: (key, value) => void items.set(key, String(value)),
  }
}

beforeEach(() => {
  vi.stubGlobal('localStorage', memoryStorage())
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  delete LANGUAGES.xx
})

describe('the pair where nobody is signed in', () => {
  it('is English and German for an English browser', () => {
    browserAsks('en-US', 'en')
    expect(guestPair('en')).toEqual(['en', 'de'])
  })

  it('takes the first language of the browser that nexdeck speaks', () => {
    LANGUAGES.xx = 'Xxish'
    browserAsks('fr-FR', 'xx-YY', 'de')
    expect(browserLanguage()).toBe('xx')
    expect(guestPair('en')).toEqual(['en', 'xx'])
  })

  it('keeps the language on screen as one of the two', () => {
    LANGUAGES.xx = 'Xxish'
    browserAsks('de-DE')
    expect(guestPair('xx')).toEqual(['en', 'xx'])
    expect(guestPair('de')).toEqual(['en', 'de'])
  })

  it('falls back to German when the browser asks for nothing nexdeck speaks', () => {
    browserAsks('fr-FR', 'it')
    expect(browserLanguage()).toBeNull()
    expect(guestPair('en')).toEqual(['en', 'de'])
  })
})

describe('the language a signed-out page starts in', () => {
  it('is the one kept in this browser, if nexdeck still speaks it', () => {
    browserAsks('en-US')
    localStorage.setItem('nexdeck.language', 'de')
    expect(storedLanguage()).toBe('de')
    localStorage.setItem('nexdeck.language', 'fr')
    expect(storedLanguage()).toBe('en')
  })

  it('else the browser\'s', () => {
    browserAsks('de-AT')
    expect(storedLanguage()).toBe('de')
  })
})

describe('the account pair', () => {
  it('is taken as it is when it is two languages nexdeck speaks', () => {
    expect(accountPair(['de', 'en'])).toEqual(['de', 'en'])
  })

  it('falls back to English and German otherwise', () => {
    for (const broken of [undefined, [], ['en'], ['en', 'en'], ['en', 'fr'], ['en', 'de', 'xx']]) {
      expect(accountPair(broken)).toEqual(['en', 'de'])
    }
  })
})
