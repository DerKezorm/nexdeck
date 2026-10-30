/**
 * A skin put on: which one, what the browser is handed of it, and the look it makes.
 *
 * The server compiles a skin (backend/app/skins); the page only puts the sheet
 * in, sets the marks the sheet answers to and lays the first layer over the
 * installation's look. 1984 is the exception that came first: nexdeck's own
 * sheet, worn as the card style `window` with its choices as before.
 *
 * Whose skin: an account's own when it chose one, else the installation's.
 */
import { create } from 'zustand'

import { get } from '../../api/client'
import type { Appearance, CardStyle, Theme } from '../appearance'

export interface SkinChoice {
  key?: string
  options?: Record<string, string>
  sounds?: boolean
  /** An account's word for no skin at all, nexdeck as it is, whatever the installation wears. */
  plain?: boolean
}

export interface SkinSound {
  wave: OscillatorType
  from: number
  to: number
  ms: number
  volume: number
}

export interface CompiledSkin {
  key: string
  css: string
  native: string | null
  options: { key: string; label: string; default: string; choices: { key: string; label: string }[] }[]
  tokens: {
    dark?: Record<string, string>
    light?: Record<string, string>
    accent?: string
    font?: string
    radius?: number
    gap?: number
    card_style?: CardStyle
  }
  fonts: string[]
  sounds: Record<string, SkinSound>
  presses: { part: string; selectors: string[]; sound: string }[]
}

/** The skin nexdeck ships with a sheet of its own; it needs nothing from the server. */
export const NATIVE_1984 = '1984'

export function chosenSkin(account: SkinChoice | null | undefined, installation: SkinChoice | null | undefined): SkinChoice {
  if (account?.plain) return {}
  if (account?.key) return account
  return installation?.key ? { ...installation, sounds: account?.sounds } : {}
}

export async function compiledSkin(key: string | undefined): Promise<CompiledSkin | null> {
  if (!key || key === NATIVE_1984) return null
  try {
    return await get<CompiledSkin>(`/skins/${encodeURIComponent(key)}/compiled`)
  } catch {
    // A skin that went or does not compile: the installation's look, never an error page.
    return null
  }
}

/** The look the page paints: the installation's, with the first layer of the skin over it and its sheet beside. */
export function wear(look: Appearance, choice: SkinChoice, compiled: CompiledSkin | null): Appearance {
  if (choice.key === NATIVE_1984) {
    return { ...look, card_style: 'window', retro: { ...look.retro, ...choice.options }, skin_key: undefined, skin_css: '', skin_options: {} }
  }
  const plain = { ...look, card_style: look.card_style === 'window' ? 'glass' : look.card_style, skin_key: undefined, skin_css: '', skin_options: {} }
  if (!choice.key || !compiled) return plain
  const tokens = compiled.tokens
  const theme: Theme | null | undefined = tokens.dark || tokens.light ? { name: compiled.key, dark: tokens.dark, light: tokens.light } : look.theme
  const options = Object.fromEntries(compiled.options.map((option) => [option.key, choice.options?.[option.key] ?? option.default]))
  return {
    ...plain,
    theme,
    accent: tokens.accent ?? (theme !== look.theme ? '' : look.accent),
    font: tokens.font ?? look.font,
    radius: tokens.radius ?? look.radius,
    gap: tokens.gap ?? look.gap,
    card_style: tokens.card_style ?? plain.card_style,
    skin_key: compiled.key,
    skin_css: compiled.css,
    skin_options: options,
    skin_fonts: compiled.fonts,
  }
}

/**
 * Asks the app to put this account's look on again, from the server: a page that painted a look of its own while it
 * was open (the settings of the look) asks for it when it is left, and so does whatever changed the skin everybody wears.
 */
export const usePaint = create<{ times: number; again: () => void }>((set) => ({ times: 0, again: () => set((current) => ({ times: current.times + 1 })) }))

/** A setting of the look a skin can take the place of. */
export type Replaced = 'theme' | 'accent' | 'card_style' | 'radius' | 'gap' | 'font'

/**
 * The settings of the look a skin takes the place of, by the rule `wear` lays it on with: its palettes replace the
 * colour theme and with it the accent (unless it names one of its own), and each of its other tokens the setting of
 * the same name. The page of the look says so beside each of them; the operator's style sheet is never replaced.
 */
export function replaces(compiled: CompiledSkin | null): Replaced[] {
  if (!compiled) return []
  const tokens = compiled.tokens
  const palette = Boolean(tokens.dark || tokens.light)
  const found: Replaced[] = palette ? ['theme', 'accent'] : tokens.accent != null ? ['accent'] : []
  for (const name of ['card_style', 'radius', 'gap', 'font'] as const) if (tokens[name] != null) found.push(name)
  return found
}

/** Put the skin of this account on: the one thing the pages call. */
export async function lookWithSkin(look: Appearance, account?: SkinChoice | null): Promise<{ look: Appearance; compiled: CompiledSkin | null; choice: SkinChoice }> {
  const choice = chosenSkin(account, look.skin)
  const compiled = await compiledSkin(choice.key)
  return { look: wear(look, choice, compiled), compiled, choice }
}
