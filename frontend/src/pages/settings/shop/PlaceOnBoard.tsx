import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { ApiError, get, post } from '../../../api/client'
import type { BoardSummary } from '../../../api/types'
import { Dialog, Field, Select } from '../../../components/ui'
import { pickText } from '../../../lib/cardText'
import type { LibraryCard } from '../../../lib/customCards'

/**
 * "Place on a board" after an install (KARTEN-14 AC-7): the board, and when the card fits several connections, the
 * connection. The card goes onto the first page of the board, the way the card library places it.
 */
export function PlaceOnBoard({ slug, open, onClose, prefer }: { slug: string; open: boolean; onClose: () => void; prefer?: number | null }) {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const boards = useQuery({ queryKey: ['boards'], queryFn: () => get<BoardSummary[]>('/boards'), enabled: open })
  const library = useQuery({ queryKey: ['cards-library'], queryFn: () => get<{ cards: LibraryCard[] }>('/cards/library'), enabled: open })
  const [board, setBoard] = useState('')
  const [connection, setConnection] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [placed, setPlaced] = useState<string | null>(null)

  const card = (library.data?.cards ?? []).find((one) => one.slug === slug) ?? null
  const mine = (boards.data ?? []).filter((one) => (one.permission === 'edit' || one.permission === 'owner') && (one.pages ?? []).length > 0)
  const chosenBoard = mine.find((one) => one.slug === board) ?? mine[0] ?? null
  const fits = card?.fits ?? []
  const chosenConnection = fits.find((one) => String(one.id) === connection) ?? fits.find((one) => one.id === prefer) ?? fits[0] ?? null

  const close = () => {
    setPlaced(null)
    setError('')
    onClose()
  }

  const place = async () => {
    if (!card || !chosenBoard || !chosenConnection) return
    setBusy(true)
    setError('')
    try {
      await post(`/pages/${chosenBoard.pages[0].id}/widgets`, {
        kind: `custom.${card.form}`,
        title: pickText(card.name, i18n.language),
        integration_id: chosenConnection.id,
        options: { card: card.slug },
      })
      await queryClient.invalidateQueries({ queryKey: ['custom-cards'] })
      await queryClient.invalidateQueries({ queryKey: ['boards'] })
      setPlaced(chosenBoard.slug)
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : t('errors.network'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      open={open}
      onClose={close}
      title={t('cards.shop.place.title')}
      size="sm"
      footer={
        placed ? (
          <>
            <button className="btn" onClick={close}>
              {t('common.close')}
            </button>
            <Link className="btn btn-accent" to={`/b/${placed}`} onClick={close}>
              {t('cards.shop.place.open')}
            </Link>
          </>
        ) : (
          <>
            <button className="btn" onClick={close}>
              {t('cards.shop.place.later')}
            </button>
            <button className="btn btn-accent" disabled={busy || !card || !chosenBoard || !chosenConnection} onClick={() => void place()}>
              {t('cards.shop.place.action')}
            </button>
          </>
        )
      }
    >
      {placed ? (
        <p className="text-sm" role="status">
          {t('cards.shop.place.done')}
        </p>
      ) : (
        <>
          {library.isSuccess && card && fits.length === 0 && <p className="text-sm text-warn mb-3">{t('cards.shop.place.noConnection')}</p>}
          {boards.isSuccess && mine.length === 0 && <p className="text-sm text-warn mb-3">{t('cards.shop.place.noBoard')}</p>}
          {mine.length > 0 && (
            <Field label={t('cards.shop.place.board')}>
              <Select value={chosenBoard?.slug ?? ''} onChange={setBoard} options={mine.map((one) => ({ value: one.slug, label: one.name }))} />
            </Field>
          )}
          {fits.length > 1 && (
            <Field label={t('cards.shop.place.connection')}>
              <Select value={String(chosenConnection?.id ?? '')} onChange={setConnection} options={fits.map((one) => ({ value: String(one.id), label: one.name }))} />
            </Field>
          )}
          {error && (
            <p className="text-sm text-bad" role="alert">
              {error}
            </p>
          )}
        </>
      )}
    </Dialog>
  )
}
