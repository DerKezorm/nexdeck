import { create } from 'zustand'

import { del, get, post } from '../api/client'
import type { Notice } from '../api/types'

interface NoticeState {
  notices: Notice[]
  unread: number
  open: boolean
  toast: Notice | null
  load: () => Promise<void>
  push: (notice: Notice) => void
  markAll: () => Promise<void>
  markRead: (ids: number[]) => Promise<void>
  remove: (id: number) => Promise<void>
  setOpen: (open: boolean) => void
  dismissToast: () => void
}

export const useNotices = create<NoticeState>((set, getState) => ({
  notices: [],
  unread: 0,
  open: false,
  toast: null,
  load: async () => {
    const notices = await get<Notice[]>('/notices?limit=100')
    set({ notices, unread: notices.filter((n) => !n.read_at).length })
  },
  push: (notice) => {
    set((state) => ({ notices: [notice, ...state.notices.filter((n) => n.id !== notice.id)].slice(0, 200), unread: state.unread + (notice.read_at ? 0 : 1), toast: notice }))
    window.setTimeout(() => {
      if (getState().toast?.id === notice.id) set({ toast: null })
    }, 6000)
  },
  markAll: async () => {
    await post('/notices/read', { all: true })
    set((state) => ({ notices: state.notices.map((n) => ({ ...n, read_at: n.read_at ?? new Date().toISOString() })), unread: 0 }))
  },
  markRead: async (ids) => {
    await post('/notices/read', { ids })
    set((state) => {
      const notices = state.notices.map((n) => (ids.includes(n.id) ? { ...n, read_at: n.read_at ?? new Date().toISOString() } : n))
      return { notices, unread: notices.filter((n) => !n.read_at).length }
    })
  },
  remove: async (id) => {
    await del(`/notices/${id}`)
    set((state) => {
      const notices = state.notices.filter((n) => n.id !== id)
      return { notices, unread: notices.filter((n) => !n.read_at).length }
    })
  },
  setOpen: (open) => set({ open }),
  dismissToast: () => set({ toast: null }),
}))
