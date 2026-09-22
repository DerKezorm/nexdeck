/**
 * Leave demo mode, with what the demo invented.
 *
 * Asks the server first what would go and says it in the confirmation: the
 * invented connections, the cards that read them, boards that were nothing
 * but the demo. A connection somebody set up for real and only tried in demo
 * mode is named as kept. Switching the flag alone used to leave the demo's
 * connections inventing data on a board that no longer said so.
 */
import { useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'

import { ApiError, get, post } from '../api/client'
import { Confirm } from './ui'

interface Plan {
  flag: boolean
  forced: boolean
  connections: string[]
  switched: string[]
  boards: string[]
  cards: number
  pages: number
}

export function LeaveDemo({ className = 'btn', label }: { className?: string; label?: string }) {
  const { t } = useTranslation()
  const queries = useQueryClient()
  const navigate = useNavigate()
  const [plan, setPlan] = useState<Plan | null>(null)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')

  const ask = () => {
    setMessage('')
    get<Plan>('/demo/leave')
      .then(setPlan)
      .catch((failure) => setMessage(failure instanceof ApiError ? failure.message : t('errors.network')))
  }

  const leave = () => {
    setBusy(true)
    post<Plan & { starter: string | null }>('/demo/leave', {})
      .then((done) => {
        setPlan(null)
        void queries.invalidateQueries()
        // A board that went may be the one on screen.
        if (done.boards.length) navigate(done.starter ? `/b/${done.starter}` : '/')
      })
      .catch((failure) => setMessage(failure instanceof ApiError ? failure.message : t('errors.network')))
      .finally(() => setBusy(false))
  }

  const nothing = plan && !plan.connections.length && !plan.switched.length && !plan.cards
  return (
    <>
      <button type="button" className={className} onClick={ask}>
        {label ?? t('demoLeave.button')}
      </button>
      {message && !plan && (
        <p className="text-sm text-bad mt-1" role="alert">
          {message}
        </p>
      )}
      <Confirm
        open={plan !== null}
        title={t('demoLeave.title')}
        body={t('demoLeave.intro')}
        danger={Boolean(plan && (plan.cards || plan.connections.length))}
        confirmLabel={t('demoLeave.confirm')}
        confirmDisabled={busy}
        onCancel={() => setPlan(null)}
        onConfirm={leave}
      >
        {plan && (
          <ul className="mt-3 space-y-1.5 text-sm" data-testid="demo-leave-plan">
            {nothing && <li>{t('demoLeave.nothing')}</li>}
            {plan.connections.length > 0 && <li>{t('demoLeave.connections', { count: plan.connections.length })}</li>}
            {plan.cards > 0 && <li>{t('demoLeave.cards', { count: plan.cards })}</li>}
            {plan.boards.length > 0 && <li>{t('demoLeave.boards', { names: plan.boards.join(', ') })}</li>}
            {plan.pages > 0 && <li>{t('demoLeave.pages', { count: plan.pages })}</li>}
            {plan.switched.length > 0 && <li>{t('demoLeave.switched', { names: plan.switched.join(', ') })}</li>}
            <li className="text-muted">{t('demoLeave.kept')}</li>
          </ul>
        )}
        {message && plan && (
          <p className="text-sm text-bad mt-2" role="alert">
            {message}
          </p>
        )}
      </Confirm>
    </>
  )
}
