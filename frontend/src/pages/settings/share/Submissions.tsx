import { useQuery } from '@tanstack/react-query'
import { ExternalLink, RefreshCw, Share2, ThumbsUp } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'

import { ApiError, get } from '../../../api/client'
import { EmptyState, Spinner } from '../../../components/ui'
import { SHARE_FAILURES, SUBMISSIONS_KEY, editorPath, type SubmissionRow, type Submissions as SubmissionList } from '../../../lib/cardShare'
import { GithubSignIn, GithubSignedIn, useGithub } from './GithubSignIn'
import { ShareDialog } from './ShareDialog'

const STATE_STYLE: Record<string, string> = {
  checking: 'text-muted',
  failed: 'text-bad',
  waiting: 'text-warn',
  in_shop: 'text-ok',
  removed: 'text-bad',
  closed: 'text-muted',
}

function Row({ row, onFix, onUpdate }: { row: SubmissionRow; onFix: (row: SubmissionRow) => void; onUpdate: (row: SubmissionRow) => void }) {
  const { t } = useTranslation()
  return (
    <li className="py-3 grid gap-1.5" data-testid="submission" data-state={row.state}>
      <div className="flex flex-wrap items-center gap-2 min-w-0">
        <span className="text-sm font-medium break-all">{row.slug}</span>
        <span className="chip !py-0 text-[11px]">{t(`cards.share.kind.${row.type}`)}</span>
        {row.update && <span className="chip !py-0 text-[11px]">{t('cards.share.submissions.update')}</span>}
        <span className={`text-sm ${STATE_STYLE[row.state] ?? ''}`}>{t(`cards.share.submissions.state.${row.state}`)}</span>
        {row.entry && (
          <span className="text-[12px] text-muted inline-flex items-center gap-1">
            {t('cards.share.submissions.version', { version: row.entry.version })}
            <ThumbsUp size={12} aria-hidden="true" />
            <span aria-label={t('cards.shop.thumbs', { count: row.entry.thumbs })}>{row.entry.thumbs}</span>
          </span>
        )}
      </div>
      {row.state === 'failed' && (
        <div className="text-sm" data-testid="submission-reasons">
          <p className="text-muted">{t('cards.share.submissions.reasons')}</p>
          <ul className="list-disc pl-5">
            {row.reasons.map((one, index) => (
              <li key={index} className="break-words">
                {one}
              </li>
            ))}
          </ul>
        </div>
      )}
      {row.state === 'removed' && row.removed && (
        <p className="text-sm break-words" data-testid="submission-removed">
          {t('cards.share.submissions.removedFor', { level: t(`cards.share.submissions.level.${row.removed.level}`, { defaultValue: row.removed.level }), reason: row.removed.reason })}
        </p>
      )}
      {row.state === 'waiting' && <p className="text-sm text-muted">{t('cards.share.submissions.waitingBody')}</p>}
      <div className="flex flex-wrap items-center gap-2">
        {row.state === 'failed' && (
          <button type="button" className="btn btn-accent" disabled={!row.local} title={row.local ? undefined : t('cards.share.submissions.cardGone')} onClick={() => onFix(row)}>
            {t('cards.share.submissions.fix')}
          </button>
        )}
        {row.state === 'in_shop' && row.local && (
          <button type="button" className="btn" onClick={() => onUpdate(row)}>
            <Share2 size={14} /> {t('cards.share.submissions.submitUpdate')}
          </button>
        )}
        <a className="btn btn-flat" href={row.url} target="_blank" rel="noopener noreferrer">
          <ExternalLink size={14} /> {t('cards.share.submissions.open', { number: row.issue })}
        </a>
      </div>
    </li>
  )
}

/**
 * "My submissions" (KARTEN-16 AC-6): what became of each card you shared, read from your issues in the Workshop and the
 * answer of its action: in review, needs a fix (with the reasons), in the Card shop, removed (with the reason).
 * "Fix and resend" opens the card in the editor and sends the corrected text into the same issue once it is saved.
 */
export function Submissions({ names }: { names?: Record<string, string> }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const github = useGithub()
  const list = useQuery({
    queryKey: SUBMISSIONS_KEY,
    queryFn: () => get<SubmissionList>('/workshop/submissions'),
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 0,
  })
  const [sharing, setSharing] = useState<SubmissionRow | null>(null)

  const trouble =
    list.isError && list.error instanceof ApiError
      ? (SHARE_FAILURES as readonly string[]).includes(list.error.code)
        ? t(`cards.share.errors.${list.error.code}`, { defaultValue: list.error.message })
        : list.error.message
      : list.isError
        ? t('errors.network')
        : ''

  if (list.isPending) {
    return (
      <p className="text-sm text-muted" role="status">
        <Spinner /> {t('common.loading')}
      </p>
    )
  }

  const data = list.data
  const signedIn = data?.signed_in === true

  return (
    <div className="grid gap-4" data-testid="submissions">
      <p className="text-sm text-muted">{t('cards.share.submissions.lead')}</p>
      {!signedIn && <GithubSignIn lead={t('cards.share.submissions.signedOut')} onSignedIn={() => void list.refetch()} />}
      {signedIn && github.data && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <GithubSignedIn state={github.data} onSignedOut={() => void list.refetch()} />
          <button type="button" className="btn btn-flat" onClick={() => void list.refetch()} disabled={list.isFetching}>
            <RefreshCw size={14} /> {t('common.refresh')}
          </button>
        </div>
      )}
      {trouble && (
        <p className="text-sm text-bad break-words" role="alert" data-testid="submissions-trouble">
          {trouble}
        </p>
      )}
      {signedIn && !trouble && data?.items.length === 0 && (
        <EmptyState title={t('cards.share.submissions.emptyTitle')} body={t('cards.share.submissions.emptyBody')} />
      )}
      {signedIn && data && data.items.length > 0 && (
        <>
          {!data.catalog_known && <p className="text-[12px] text-muted">{t('cards.share.submissions.catalogOff')}</p>}
          <ul className="divide-y divide-line">
            {data.items.map((row) => (
              <Row key={row.issue} row={row} onFix={(one) => navigate(editorPath(one.type, one.slug, one.issue))} onUpdate={setSharing} />
            ))}
          </ul>
        </>
      )}
      {sharing && <ShareDialog kind={sharing.type} slug={sharing.slug} name={names?.[sharing.slug] ?? sharing.slug} open onClose={() => setSharing(null)} />}
    </div>
  )
}
