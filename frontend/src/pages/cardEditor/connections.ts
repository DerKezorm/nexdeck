/**
 * The connections a card can be probed and previewed with (decision 4): those of the kinds the card names in
 * `requires`, switched on. Which one is used is the editor's own choice, never written into the card; until somebody
 * picks one, the first that fits.
 */
import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'

import { ApiError, get, post } from '../../api/client'
import type { Integration } from '../../api/types'
import { readAt } from '../../lib/cardDocument'
import type { ProbeAnswer } from './probe'
import { useCardEditor } from './store'

const NO_KINDS: string[] = []

/** The kinds the card reads through, from the card on screen or its last valid version. */
export function useRequiredKinds(): string[] {
  const card = useCardEditor((state) => state.card ?? state.lastValid?.card ?? null)
  return useMemo(() => {
    const kinds = card ? readAt(card, ['requires']) : undefined
    return Array.isArray(kinds) ? kinds.map(String) : NO_KINDS
  }, [card])
}

export function useConnections() {
  const kinds = useRequiredKinds()
  const integrations = useQuery({ queryKey: ['integrations'], queryFn: () => get<Integration[]>('/integrations') })
  const picked = useCardEditor((state) => state.integrationId)
  const fitting = useMemo(() => (integrations.data ?? []).filter((one) => kinds.includes(one.kind) && one.enabled !== false), [integrations.data, kinds])
  const chosen = fitting.find((one) => one.id === picked) ?? fitting[0] ?? null
  return { kinds, fitting, chosen, loaded: integrations.isSuccess }
}

/** Why a probe, the examples or the preview failed, the way a card says it (EC-2): the code, the sentence, the hint. */
export interface Failure {
  code: string
  message: string
  hint?: string
}

export function failureOf(failure: unknown): Failure {
  if (failure instanceof ApiError) return { code: failure.code, message: failure.message, hint: failure.hint }
  return { code: 'network', message: failure instanceof Error ? failure.message : String(failure) }
}

/**
 * Ask one path of the connection (KARTEN-9 AC-3). The answer stays in the editor's memory under the request id;
 * the chronicle names the probe without its answer (EC-4, on the server).
 */
export async function runProbe(requestId: string, integrationId: number, path: string): Promise<void> {
  const editor = useCardEditor.getState()
  editor.setProbe(requestId, { status: 'loading', path })
  try {
    const answer = await post<ProbeAnswer>('/cards/probe', { integration_id: integrationId, path })
    useCardEditor.getState().setProbe(requestId, { status: 'done', path, integrationId, answer })
  } catch (failure) {
    useCardEditor.getState().setProbe(requestId, { status: 'failed', path, ...failureOf(failure) })
  }
}
