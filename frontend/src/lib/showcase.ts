/**
 * Showcase mode: the board as it looks, with nothing of the home in it.
 *
 * Dashboards are shown around, on forums and in chats, and every screenshot
 * so far was blacked out by hand or not at all: addresses, host names, the
 * names of the people who watch, what they watch. Switched on, the board
 * replaces all of that with made-up names that read like real ones, so the
 * picture still looks like a board in use and not like a redacted document.
 *
 * Nothing leaves the browser and nothing is stored on the server: it is a
 * way of drawing, kept in this browser only, and it changes no data.
 *
 * What is found, and how:
 *
 * - Everywhere, by its shape: IPv4 and IPv6 addresses, MAC addresses, mail
 *   addresses, host names on a home network's own endings (.lan, .local,
 *   .home.arpa, .fritz.box …) or on a dynamic DNS service, and every name
 *   under a domain the board's own services live on. The domains are read
 *   from the addresses of the cards on the board and from the address this
 *   page was opened at, because those are the operator's.
 * - The account's own name and user name, wherever they stand.
 * - By what a card is: the people and devices in what is playing, the
 *   events of a calendar, the subjects and senders of mail, the rows of a
 *   list of users, a city on the weather card. A camera, an embedded page
 *   and a note are blurred, since nothing in them can be told apart.
 * - Titles of films, series and music only when asked for as well: they
 *   say less about a home than an address does, and a board of covers with
 *   invented titles under them looks wrong.
 */
import { useMemo } from 'react'
import { create } from 'zustand'

const KEPT = 'nexdeck.showcase'

interface Kept {
  on: boolean
  media: boolean
}

function kept(): Kept {
  try {
    const value = JSON.parse(localStorage.getItem(KEPT) ?? '{}') as Partial<Kept>
    return { on: value.on === true, media: value.media === true }
  } catch {
    return { on: false, media: false }
  }
}

function keep(value: Kept): void {
  try {
    localStorage.setItem(KEPT, JSON.stringify(value))
  } catch {
    // A browser that keeps nothing forgets it on the next load, which is the safe way round.
  }
}

interface ShowcaseState extends Kept {
  /** Domains whose every name is the operator's, from the board's own addresses. */
  domains: string[]
  /** The account's own names, which are replaced wherever they stand. */
  names: string[]
  setOn: (on: boolean) => void
  setMedia: (media: boolean) => void
  setDomains: (domains: string[]) => void
  setNames: (names: string[]) => void
}

/**
 * Account names that are words of the interface as well. An account called
 * "home" would otherwise turn Home Assistant into Alex Assistant; such a name
 * says nothing about anybody, so it is left where it stands.
 */
const COMMON = new Set(['admin', 'administrator', 'user', 'home', 'root', 'guest', 'demo', 'test', 'nexdeck', 'media', 'server', 'family', 'kiosk', 'owner', 'operator'])

/** Whether an account name is worth replacing: long enough, and not a word every board uses. */
export function personal(name: string): boolean {
  const word = name.trim()
  return word.length >= 3 && !COMMON.has(word.toLowerCase())
}

export const useShowcase = create<ShowcaseState>((set, get) => ({
  ...kept(),
  domains: [],
  names: [],
  setOn: (on) => {
    set({ on })
    keep({ on, media: get().media })
  },
  setMedia: (media) => {
    set({ media })
    keep({ on: get().on, media })
  },
  setDomains: (domains) => {
    const next = [...new Set(domains.map((domain) => domain.toLowerCase()))].sort()
    if (next.join() !== get().domains.join()) set({ domains: next })
  },
  setNames: (names) => {
    const next = [...new Set(names.map((name) => name.trim()).filter(personal))].sort()
    if (next.join() !== get().names.join()) set({ names: next })
  },
}))

// ---------------------------------------------------------------------------
// The made-up names. Plain and believable; the films are the ones the demo
// mode shows, so a showcase board and the demo read alike.
// ---------------------------------------------------------------------------

const PEOPLE = ['Alex', 'Sam', 'Robin', 'Kim', 'Jo', 'Charlie', 'Mika', 'Toni', 'Luca', 'Noa']
const DEVICES = ['Living room TV', 'Bedroom TV', 'Phone', 'Tablet', 'Laptop', 'Office', 'Kitchen', 'Projector']
const MEDIA = ['The Quiet Harbour', 'Orbital', 'Nightshift', 'Harbour Lights', 'Glass Mountains', 'Paper Satellites', 'Low Tide', 'The Last Signal', 'Copper Fields', 'Northbound', 'Static Bloom', 'Kestrel', 'Saltwater Hymn', 'Midnight Ferry', 'Copper Sky', 'Orbital Decay']
const EVENTS = ['Dentist', 'Team meeting', 'Swap the backup disks', 'Birthday dinner', 'Parents evening', 'Car service', 'Yoga', 'Call with the bank', 'Football', 'Haircut']
const SUBJECTS = ['Your order has shipped', 'Invoice for September', 'Weekly report', 'Re: Plans for the weekend', 'Backup finished', 'New sign-in to your account', 'Your parcel is on its way', 'Meeting notes']
const SENDERS = ['Shop', 'Alex', 'Newsletter', 'Backup', 'Sam', 'Bank', 'Delivery', 'Robin']
const CITIES = ['Springfield', 'Riverton', 'Lakeside', 'Fairview']

export type Kind = 'person' | 'device' | 'media' | 'event' | 'subject' | 'sender' | 'city'
const LISTS: Record<Kind, string[]> = { person: PEOPLE, device: DEVICES, media: MEDIA, event: EVENTS, subject: SUBJECTS, sender: SENDERS, city: CITIES }

/**
 * One made-up name per real one, the same one for as long as the page is
 * open: Anna is Alex on every card, and two people are never both Alex while
 * the list has names left. Handed out in the order things are first drawn.
 */
const given = new Map<string, string>()
const counters = new Map<string, number>()

function stable(kind: string, real: string, make: (index: number) => string): string {
  const key = `${kind}\u0000${real.toLowerCase()}`
  const known = given.get(key)
  if (known !== undefined) return known
  const index = counters.get(kind) ?? 0
  counters.set(kind, index + 1)
  const made = make(index)
  given.set(key, made)
  return made
}

/** Forget every name handed out; for tests, and nothing else needs it. */
export function forgetGivenNames(): void {
  given.clear()
  counters.clear()
}

function listed(kind: Kind, real: string): string {
  const list = LISTS[kind]
  return stable(kind, real, (index) => (index < list.length ? list[index] : `${list[index % list.length]} ${Math.floor(index / list.length) + 1}`))
}

function letters(index: number): string {
  let text = ''
  let number = index
  do {
    text = String.fromCharCode(97 + (number % 26)) + text
    number = Math.floor(number / 26) - 1
  } while (number >= 0)
  return text
}

// ---------------------------------------------------------------------------
// What is found by its shape.
// ---------------------------------------------------------------------------

const OCTET = '(?:25[0-5]|2[0-4]\\d|1\\d\\d|[1-9]?\\d)'
/** Not inside a longer run of digits and dots: 1.41.3.9314 is a version, not an address. */
const IPV4 = new RegExp(`(?<![\\d.])${OCTET}(?:\\.${OCTET}){3}(?![\\d.]*\\d)`, 'g')
/** At least two groups and a double colon, or eight groups: a time like 10:30 is not one. */
const IPV4_ALONE = new RegExp(`^${OCTET}(?:\\.${OCTET}){3}$`)
const IPV6 = /(?<![\w:])(?:[0-9a-f]{1,4}:){7}[0-9a-f]{1,4}(?![\w:])|(?<![\w:])(?:[0-9a-f]{1,4}:){1,6}:(?:[0-9a-f]{1,4}(?::[0-9a-f]{1,4})*)?(?![\w:])|(?<![\w:])::(?:[0-9a-f]{1,4}:){0,5}[0-9a-f]{1,4}(?![\w:])/gi
const MAC = /(?<![\w:-])(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}(?![\w:-])/gi
const MAIL = /[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g
/** Endings that only a home network uses, and the dynamic DNS services people put their homes on. */
const HOME_ENDINGS = ['lan', 'local', 'home', 'internal', 'intranet', 'localdomain', 'home.arpa', 'fritz.box', 'box', 'corp', 'test']
const DYNAMIC = ['duckdns.org', 'ts.net', 'synology.me', 'myfritz.net', 'dynv6.net', 'ddns.net', 'no-ip.org', 'freeddns.org', 'dyndns.org', 'myds.me', 'tplinkdns.com', 'dynu.net', 'nip.io', 'sslip.io']
const NAME = /(?<![\w@.-])(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]*[a-z0-9](?![\w-])/gi

function escape(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/** Whether a host name belongs to the home: by its ending, a dynamic DNS service, or a domain of the board. */
function ownName(host: string, domains: string[]): boolean {
  const name = host.toLowerCase()
  const under = (domain: string) => name === domain || name.endsWith(`.${domain}`)
  return HOME_ENDINGS.some(under) || DYNAMIC.some(under) || domains.some(under)
}

/**
 * The domain a host lives under, as far as it can be told without a list of
 * every ending in the world: the last two labels, or three where the second
 * last is short, as in example.co.uk.
 */
export function domainOf(host: string): string {
  const name = host.toLowerCase().replace(/\.$/, '')
  if (!name.includes('.') || IPV4_ALONE.test(name) || name === 'localhost') return ''
  const labels = name.split('.')
  if (labels.length >= 3 && labels[labels.length - 2].length <= 3 && labels[labels.length - 1].length === 2) return labels.slice(-3).join('.')
  return labels.slice(-2).join('.')
}

/** The domains of a set of addresses, for `setDomains`. */
export function domainsOf(addresses: (string | undefined | null)[]): string[] {
  const found = new Set<string>()
  for (const address of addresses) {
    if (!address) continue
    let host: string
    try {
      host = new URL(address, 'http://placeholder.invalid').hostname
    } catch {
      continue
    }
    if (host === 'placeholder.invalid') continue
    const domain = domainOf(host)
    if (domain) found.add(domain)
  }
  return [...found]
}

/**
 * A text with everything found by its shape replaced, and the account's own
 * names. What is left is word for word as it was.
 */
export function scrub(text: string, domains: string[], names: string[]): string {
  if (!text) return text
  let result = text
    .replace(MAIL, (address) => stable('mail', address, (index) => `user-${letters(index)}@example.com`))
    .replace(MAC, (address) => stable('mac', address, (index) => `02:00:00:00:${((index >> 8) & 255).toString(16).padStart(2, '0')}:${(index & 255).toString(16).padStart(2, '0')}`))
    .replace(IPV4, (address) => stable('ipv4', address, (index) => `192.0.2.${(index % 254) + 1}`))
    .replace(IPV6, (address) => (address.includes(':') && /[0-9a-f]/i.test(address) ? stable('ipv6', address, (index) => `2001:db8::${(index + 1).toString(16)}`) : address))
    .replace(NAME, (host) => (ownName(host, domains) ? stable('host', host, (index) => `host-${letters(index)}.example`) : host))
  for (const name of names) {
    result = result.replace(new RegExp(`(?<![\\w])${escape(name)}(?![\\w])`, 'gi'), (found) => listed('person', found))
  }
  return result
}

/** A made-up name of a kind, the same one for the same real name. */
export function madeUp(kind: Kind, real: string): string {
  return real ? listed(kind, real) : real
}

/**
 * What playing media says under its title, "anna · Living room · 4K ·
 * Direct play": the person and the device are replaced, the rest is kept.
 * Only when the first part is the user the row names, so a subtitle of
 * another shape is left to the shape rules.
 */
export function playingLine(subtitle: string, user: string): string {
  const parts = subtitle.split(' · ')
  if (!user || parts[0] !== user) return subtitle
  return [madeUp('person', parts[0]), ...(parts.length > 1 ? [madeUp('device', parts[1])] : []), ...parts.slice(2)].join(' · ')
}

export interface Disguise {
  on: boolean
  /** Everything found by its shape, and the account's own names. */
  free: (text: string) => string
  /** A made-up name of a kind. */
  as: (kind: Kind, text: string) => string
  /** The title of a film, a series or an album: made up only when media titles are asked for too. */
  media: (text: string) => string
  /** Whether titles are made up too, and with them every picture that would give the title away. */
  mediaHidden: boolean
}

const PLAIN: Disguise = { on: false, free: (text) => text, as: (_kind, text) => text, media: (text) => text, mediaHidden: false }

/** The way a card writes what it shows, in showcase mode or not. */
export function useDisguise(): Disguise {
  const on = useShowcase((state) => state.on)
  const media = useShowcase((state) => state.media)
  const domains = useShowcase((state) => state.domains)
  const names = useShowcase((state) => state.names)
  return useMemo(() => {
    if (!on) return PLAIN
    const free = (text: string) => scrub(text, domains, names)
    return { on: true, free, as: madeUp, media: (text: string) => (media ? madeUp('media', text) : free(text)), mediaHidden: media }
  }, [on, media, domains, names])
}

