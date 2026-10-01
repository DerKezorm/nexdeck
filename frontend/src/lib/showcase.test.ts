import { beforeEach, describe, expect, it } from 'vitest'

import { domainOf, domainsOf, forgetGivenNames, madeUp, personal, playingLine, scrub } from './showcase'

beforeEach(() => forgetGivenNames())

describe('what showcase mode finds by its shape', () => {
  it('replaces addresses with ones from the documentation ranges', () => {
    expect(scrub('Gateway 10.20.30.1, DNS 1.1.1.1', [], [])).toBe('Gateway 192.0.2.1, DNS 192.0.2.2')
    expect(scrub('listening on fd00:1234::5', [], [])).toBe('listening on 2001:db8::1')
    expect(scrub('client aa:bb:cc:dd:ee:ff joined', [], [])).toBe('client 02:00:00:00:00:00 joined')
    expect(scrub('From anna.weber@example.org', [], [])).toBe('From user-a@example.com')
  })

  it('gives the same address the same stand-in every time, and two addresses two', () => {
    const first = scrub('10.0.0.5', [], [])
    expect(scrub('host at 10.0.0.5', [], [])).toBe(`host at ${first}`)
    expect(scrub('10.0.0.6', [], [])).not.toBe(first)
  })

  it('leaves versions, times and sizes alone', () => {
    for (const text of ['Plex 1.41.3.9314', 'Update 2.5.37 available', 'at 10:30', 'S03E05 · 1080p', '4.5 GB', 'v1.2.3', 'ratio 4.2']) {
      expect(scrub(text, [], [])).toBe(text)
    }
  })

  it('replaces host names of a home network and of dynamic DNS, not of the internet', () => {
    expect(scrub('nas.lan is up', [], [])).toBe('host-a.example is up')
    expect(scrub('pve.home.arpa', [], [])).toBe('host-b.example')
    expect(scrub('fritz.box', [], [])).toBe('host-c.example')
    expect(scrub('home.duckdns.org', [], [])).toBe('host-d.example')
    expect(scrub('github.com and news.ycombinator.com', [], [])).toBe('github.com and news.ycombinator.com')
    expect(scrub('steuer-2025.pdf', [], [])).toBe('steuer-2025.pdf')
  })

  it('replaces every name under a domain the board lives on', () => {
    expect(scrub('sonarr.mydomain.de expires in 12 days', ['mydomain.de'], [])).toBe('host-a.example expires in 12 days')
    expect(scrub('mydomain.de', ['mydomain.de'], [])).toBe('host-b.example')
    expect(scrub('notmydomain.de', ['mydomain.de'], [])).toBe('notmydomain.de')
  })

  it("replaces the account's own names as whole words", () => {
    expect(scrub('Morgan watched 3 films', [], ['Morgan'])).toBe('Alex watched 3 films')
    expect(scrub('morgan-laptop', [], ['Morgan'])).toBe('Alex-laptop')
    expect(scrub('Morganstreet', [], ['Morgan'])).toBe('Morganstreet')
  })
})

describe('the domains of the board', () => {
  it('reads the domain of an address', () => {
    expect(domainOf('sonarr.example.de')).toBe('example.de')
    expect(domainOf('deck.home.example.co.uk')).toBe('example.co.uk')
    expect(domainOf('10.0.0.1')).toBe('')
    expect(domainOf('localhost')).toBe('')
    expect(domainOf('nas')).toBe('')
  })

  it('collects them from the addresses of the cards', () => {
    expect(domainsOf(['https://sonarr.mydomain.de', 'http://10.0.0.2:8989', '', null, '/relative', 'https://plex.mydomain.de/web']).sort()).toEqual(['mydomain.de'])
  })
})

describe('made-up names', () => {
  it('hands out one per real name and keeps it', () => {
    expect(madeUp('person', 'anna')).toBe('Alex')
    expect(madeUp('person', 'ben')).toBe('Sam')
    expect(madeUp('person', 'Anna')).toBe('Alex')
  })

  it('runs on with a number once the list is used up', () => {
    const names = Array.from({ length: 12 }, (_, index) => madeUp('city', `city ${index}`))
    expect(new Set(names).size).toBe(12)
  })

  it('replaces the person and the device under something playing, and keeps the rest', () => {
    expect(playingLine('anna · Morgan iPhone · 4K · Direct play', 'anna')).toBe('Alex · Living room TV · 4K · Direct play')
    expect(playingLine('Living room · 4K', 'anna')).toBe('Living room · 4K')
  })
})

describe("the account's own names", () => {
  it('leaves names that are words every board uses, and very short ones', () => {
    expect(personal('Morgan')).toBe(true)
    expect(personal('admin')).toBe(false)
    expect(personal('Home')).toBe(false)
    expect(personal('jo')).toBe(false)
  })
})

