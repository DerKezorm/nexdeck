/**
 * A skin while it is edited: the file as an object, with undo and redo, kept in
 * this browser so a reload or a crash loses nothing.
 *
 * Changes to the same field within half a second are one step back, so a
 * colour dragged across the picker or a word typed is undone at once, not a
 * letter at a time. A whole new file (an answer of the AI, a starting point) is
 * always a step of its own.
 */
import { useCallback, useState } from 'react'

/** The skin file (`nexdeck_skin: 1`); the server checks it, the editor only keeps it. */
export type SkinDoc = Record<string, unknown> & { nexdeck_skin: 1; key: string; name: string }

const COALESCE_MS = 500
const KEPT = 'nexdeck.skin-draft.'

export interface History {
  past: SkinDoc[]
  present: SkinDoc
  future: SkinDoc[]
  /** The field the last step changed and when, to fold the next change of it into the same step. */
  last: { tag: string; at: number } | null
}

export function start(doc: SkinDoc): History {
  return { past: [], present: doc, future: [], last: null }
}

/** One change. ``tag`` names the field; without one the change is always a step of its own. */
export function change(history: History, next: SkinDoc, tag?: string, now = Date.now()): History {
  if (next === history.present) return history
  const fold = tag !== undefined && history.last?.tag === tag && now - history.last.at < COALESCE_MS
  return {
    past: fold ? history.past : [...history.past, history.present].slice(-200),
    present: next,
    future: [],
    last: tag === undefined ? null : { tag, at: now },
  }
}

export function undo(history: History): History {
  const previous = history.past.at(-1)
  if (!previous) return history
  return { past: history.past.slice(0, -1), present: previous, future: [history.present, ...history.future], last: null }
}

export function redo(history: History): History {
  const [next, ...rest] = history.future
  if (!next) return history
  return { past: [...history.past, history.present], present: next, future: rest, last: null }
}

/** A copy of the file with one value set at a path; an undefined value takes the field out. */
export function setAt(doc: SkinDoc, path: (string | number)[], value: unknown): SkinDoc {
  const write = (target: unknown, depth: number): unknown => {
    const step = path[depth]
    const copy = (Array.isArray(target) ? [...target] : { ...((target as Record<string, unknown>) ?? {}) }) as Record<string | number, unknown>
    if (depth === path.length - 1) {
      if (value === undefined) {
        if (Array.isArray(copy)) (copy as unknown[]).splice(step as number, 1)
        else delete copy[step]
      } else copy[step] = value
      return copy
    }
    const inner = (target as Record<string | number, unknown> | undefined)?.[step]
    copy[step] = write(inner ?? (typeof path[depth + 1] === 'number' ? [] : {}), depth + 1)
    return copy
  }
  return write(doc, 0) as SkinDoc
}

export function keptDraft(key: string): SkinDoc | null {
  try {
    const text = localStorage.getItem(KEPT + key)
    return text ? (JSON.parse(text) as SkinDoc) : null
  } catch {
    return null
  }
}

export function keepDraft(key: string, doc: SkinDoc | null): void {
  try {
    if (doc) localStorage.setItem(KEPT + key, JSON.stringify(doc))
    else localStorage.removeItem(KEPT + key)
  } catch {
    // A browser that keeps nothing: the draft lives as long as the page.
  }
}

/** The editor's state: the file, its history and the ways to change it. */
export function useDraft(initial: SkinDoc) {
  const [history, setHistory] = useState<History>(() => start(initial))
  const set = useCallback((next: SkinDoc, tag?: string) => setHistory((current) => change(current, next, tag)), [])
  const at = useCallback((path: (string | number)[], value: unknown) => setHistory((current) => change(current, setAt(current.present, path, value), path.join('.'))), [])
  return {
    doc: history.present,
    set,
    at,
    replace: (doc: SkinDoc) => setHistory(start(doc)),
    undo: () => setHistory(undo),
    redo: () => setHistory(redo),
    canUndo: history.past.length > 0,
    canRedo: history.future.length > 0,
  }
}

export type Draft = ReturnType<typeof useDraft>
