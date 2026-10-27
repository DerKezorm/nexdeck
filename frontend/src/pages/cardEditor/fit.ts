/**
 * Whether the blocks of a card put together from blocks fit the card in the preview (KARTEN-7 AC-7). The preview
 * measures its card and tells this store; the builder reads it and warns. Memory only: it belongs to what is on screen.
 */
import { create } from 'zustand'

interface FitState {
  /** The content is larger than the card: a list scrolls and the rest is cut off. */
  overflowing: boolean
  report: (overflowing: boolean) => void
}

export const useFit = create<FitState>((set, get) => ({
  overflowing: false,
  report: (overflowing) => {
    if (get().overflowing !== overflowing) set({ overflowing })
  },
}))
