import { useQuery, useQueryClient } from '@tanstack/react-query'
import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, get, post } from '../../../api/client'
import { Dialog, Spinner } from '../../../components/ui'
import {
  GITHUB_KEY,
  SHARE_CATEGORIES,
  SHARE_FAILURES,
  SHARE_PROBLEMS,
  SUBMISSIONS_KEY,
  shareProblems,
  type ShareCheck,
  type ShareFile,
  type ShareKind,
  type ShareProblem,
  type ShareSent,
} from '../../../lib/cardShare'
import type { CardForm } from '../../../lib/customCards'
import { GithubSignIn, GithubSignedIn, useGithub } from './GithubSignIn'

// Loaded on its own: the renderers come with the preview, not with the page of the settings.
const ImportPreview = lazy(() => import('../ImportPreview'))

/** The sentence of a problem the server found: its own words for the codes the interface knows, else the server's English. */
function problemText(t: (key: string, options?: Record<string, unknown>) => string, problem: ShareProblem, version?: string): string {
  if ((SHARE_PROBLEMS as readonly string[]).includes(problem.code)) return t(`cards.share.problem.${problem.code}`, { defaultValue: problem.message, version: version ?? '' })
  return problem.message
}

function failureText(t: (key: string, options?: Record<string, unknown>) => string, failure: unknown): string {
  if (!(failure instanceof ApiError)) return t('errors.network')
  if ((SHARE_FAILURES as readonly string[]).includes(failure.code)) return t(`cards.share.errors.${failure.code}`, { defaultValue: failure.message })
  return failure.message
}

/** The file of a submission, handed to the browser. */
function saveFile(file: ShareFile): void {
  const url = URL.createObjectURL(new Blob([file.text], { type: 'text/markdown' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = file.filename
  document.body.append(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

/**
 * "Share in the Card shop" (KARTEN-16): the things the Workshop asks for (English texts, demo data, a description, a
 * category, the MIT licence), how the card will look in the shop, a warning when the demo data look like real values,
 * the sign-in to GitHub when it is needed, and the way without it: a file and a link to the form on GitHub.
 *
 * What the administrator wrote stays where it is when the sign-in ended or GitHub is out of reach (EC-2): he signs in
 * again in the same dialog and sends.
 */
export function ShareDialog({ kind, slug, name, form, open, onClose }: { kind: ShareKind; slug: string; name: string; form?: CardForm; open: boolean; onClose: () => void }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const github = useGithub(open)
  const check = useQuery({
    queryKey: ['workshop-share-check', kind, slug],
    queryFn: () => post<ShareCheck>('/workshop/submit/check', { type: kind, slug }),
    enabled: open,
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 0,
    gcTime: 0,
  })
  const text = useQuery({
    queryKey: ['workshop-share-text', slug],
    queryFn: () => get<{ yaml: string }>(`/cards/${encodeURIComponent(slug)}`),
    enabled: open && kind === 'card',
    retry: false,
    refetchOnWindowFocus: false,
    gcTime: 0,
  })
  const [description, setDescription] = useState('')
  const [category, setCategory] = useState('')
  const [changes, setChanges] = useState('')
  const [license, setLicense] = useState(false)
  const [touched, setTouched] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [problems, setProblems] = useState<ShareProblem[]>([])
  const [sent, setSent] = useState<ShareSent | null>(null)
  const [file, setFile] = useState<ShareFile | null>(null)
  const sending = useRef(false)

  const data = check.data
  // What the card says about itself is the start of the dialog; what the administrator typed is never overwritten.
  useEffect(() => {
    if (data && !touched) {
      setDescription(data.suggested.description)
      setCategory(data.suggested.category)
    }
  }, [data, touched])

  const close = () => {
    setDescription('')
    setCategory('')
    setChanges('')
    setLicense(false)
    setTouched(false)
    setError('')
    setProblems([])
    setSent(null)
    setFile(null)
    onClose()
  }

  const body = { type: kind, slug, category, description, changes, license }
  const update = data?.mode === 'update'
  const signedIn = data?.signed_in === true && github.data?.signed_in !== false
  const dailyReached = data?.daily?.reached === true
  const blocking = (data?.problems.length ?? 0) > 0
  const ready = !!data && !blocking && signedIn && !dailyReached && description.trim() !== '' && category !== '' && license && (!update || changes.trim() !== '')

  const share = async () => {
    if (sending.current || !ready) return
    sending.current = true
    setBusy(true)
    setError('')
    setProblems([])
    try {
      const answer = await post<ShareSent>('/workshop/submit', body)
      await queryClient.invalidateQueries({ queryKey: SUBMISSIONS_KEY })
      setSent(answer)
    } catch (failure) {
      if (failure instanceof ApiError && failure.code === 'github_login_needed') {
        queryClient.setQueryData(GITHUB_KEY, { signed_in: false, login: null, github_id: null, until: null, pending: null })
        void check.refetch()
      }
      const found = shareProblems(failure)
      if (found.length) setProblems(found)
      else setError(failureText(t, failure))
    } finally {
      sending.current = false
      setBusy(false)
    }
  }

  const prepare = async () => {
    setBusy(true)
    setError('')
    setProblems([])
    try {
      const made = await post<ShareFile>('/workshop/submit/file', body)
      setFile(made)
      saveFile(made)
    } catch (failure) {
      const found = shareProblems(failure)
      if (found.length) setProblems(found)
      else setError(failureText(t, failure))
    } finally {
      setBusy(false)
    }
  }

  const shown = [...(data?.problems ?? []), ...problems]

  return (
    <Dialog
      open={open}
      onClose={close}
      title={t('cards.share.title')}
      size="lg"
      footer={
        sent ? (
          <button className="btn btn-accent" onClick={close}>
            {t('common.close')}
          </button>
        ) : (
          <>
            <button className="btn" onClick={close}>
              {t('common.cancel')}
            </button>
            <button className="btn btn-accent" disabled={busy || !ready} onClick={() => void share()}>
              {busy && <Spinner />}
              {t(update ? 'cards.share.sendUpdate' : 'cards.share.send')}
            </button>
          </>
        )
      }
    >
      {check.isPending && (
        <p className="text-sm text-muted" role="status">
          {t('cards.share.checking')}
        </p>
      )}
      {check.isError && (
        <p className="text-sm text-bad break-words" role="alert">
          {failureText(t, check.error)}
        </p>
      )}

      {sent && (
        <div className="grid gap-2" role="status" data-testid="share-done">
          <p className="text-sm">{t(!sent.created && !sent.changed ? 'cards.share.done.unchanged' : sent.update ? 'cards.share.done.update' : 'cards.share.done.new', { name })}</p>
          <a className="text-accent hover:underline text-sm" href={sent.issue.url} target="_blank" rel="noopener noreferrer">
            {t('cards.share.done.open', { number: sent.issue.number })}
          </a>
          <p className="text-sm text-muted">{t('cards.share.done.where')}</p>
        </div>
      )}

      {data && !sent && (
        <div className="grid gap-4">
          <p className="text-sm text-muted">{t('cards.share.lead')}</p>

          <div className="grid gap-1 text-sm" data-testid="share-mode">
            <span className="font-medium">{name || data.name || slug}</span>
            {update ? (
              <span className="text-muted">{t('cards.share.mode.update', { version: data.previous_version ?? '' })}</span>
            ) : (
              <span className="text-muted">{t('cards.share.mode.new')}</span>
            )}
            {data.based_on && <span className="text-muted">{t('cards.share.mode.basedOn', { id: data.based_on })}</span>}
            {data.daily && (
              <span className={dailyReached ? 'text-bad' : 'text-muted'} role={dailyReached ? 'alert' : undefined} data-testid="share-daily">
                {t(dailyReached ? 'cards.share.daily.reached' : 'cards.share.daily.used', { used: data.daily.used, max: data.daily.max })}
              </span>
            )}
          </div>

          {data.github && (
            <p className="text-sm text-bad break-words" role="alert" data-testid="share-github-trouble">
              {t(`cards.share.errors.${data.github.code}`, { defaultValue: data.github.message })}
            </p>
          )}

          {shown.length > 0 && (
            <div className="rounded-xl border border-line p-3 grid gap-1" role="alert" data-testid="share-problems">
              <h3 className="font-semibold text-sm text-bad">{t('cards.share.problems')}</h3>
              <ul className="text-sm list-disc pl-5">
                {shown.map((one, index) => (
                  <li key={`${one.code}-${index}`} className="break-words" data-code={one.code}>
                    {problemText(t, one, data.previous_version ?? '')}
                    {one.path && one.code !== one.path ? <span className="text-muted font-mono text-[12px]"> ({one.path})</span> : null}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {data.warnings.real_values.length > 0 && (
            <div className="rounded-xl border border-warn/50 p-3 grid gap-1" role="status" data-testid="share-real-values">
              <h3 className="font-semibold text-sm text-warn">{t('cards.share.realValues.title')}</h3>
              <p className="text-sm text-muted">{t('cards.share.realValues.body')}</p>
              <ul className="text-sm list-disc pl-5">
                {data.warnings.real_values.map((one) => (
                  <li key={one.path} className="break-words">
                    <span className="font-mono text-[12px]">{one.path}</span>: {one.value}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="grid gap-1">
            <h3 className="font-semibold text-sm">{t('cards.share.preview')}</h3>
            {kind === 'card' && form && text.data ? (
              <Suspense fallback={<p className="text-sm text-muted">{t('cards.exchange.previewLoading')}</p>}>
                <ImportPreview yaml={text.data.yaml} form={form} name={data.name} icon="" />
              </Suspense>
            ) : kind === 'integration' ? (
              <div className="rounded-xl border border-line p-3 grid gap-1" data-testid="share-tile">
                <span className="text-sm font-medium">{data.name}</span>
                <span className="text-[12px] text-muted">{t('cards.share.reads', { count: data.reads.length })}</span>
                <ul className="text-[12px] font-mono break-all">
                  {data.reads.slice(0, 6).map((one) => (
                    <li key={one.path}>{one.label}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>

          <div className="grid gap-1">
            <label htmlFor="share-description" className="text-sm font-medium">
              {t('cards.share.description')}
            </label>
            <textarea
              id="share-description"
              className="input"
              rows={3}
              value={description}
              onChange={(event) => {
                setTouched(true)
                setDescription(event.target.value)
              }}
            />
            <span className="text-[12px] text-muted">{t('cards.share.descriptionHelp')}</span>
          </div>

          <div className="grid gap-1">
            <label htmlFor="share-category" className="text-sm font-medium">
              {t('cards.share.category')}
            </label>
            <select
              id="share-category"
              className="input"
              value={category}
              onChange={(event) => {
                setTouched(true)
                setCategory(event.target.value)
              }}
            >
              <option value="">{t('cards.share.categoryPick')}</option>
              {SHARE_CATEGORIES.map((one) => (
                <option key={one} value={one}>
                  {t(`cards.share.categories.${one}`)}
                </option>
              ))}
            </select>
          </div>

          {update && (
            <div className="grid gap-1">
              <label htmlFor="share-changes" className="text-sm font-medium">
                {t('cards.share.changes')}
              </label>
              <textarea id="share-changes" className="input" rows={3} value={changes} onChange={(event) => setChanges(event.target.value)} />
              <span className="text-[12px] text-muted">{t('cards.share.changesHelp')}</span>
            </div>
          )}

          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-1"
              checked={license}
              onChange={(event) => {
                setTouched(true)
                setLicense(event.target.checked)
              }}
            />
            <span>{t('cards.share.license')}</span>
          </label>

          {error && (
            <p className="text-sm text-bad break-words" role="alert" data-testid="share-error">
              {error}
            </p>
          )}

          {!signedIn ? (
            <div className="grid gap-3">
              <GithubSignIn onSignedIn={() => void check.refetch()} />
              <div className="rounded-xl border border-line p-4 grid gap-2 justify-items-start" data-testid="share-offline">
                <h3 className="font-semibold text-[15px]">{t('cards.share.offline.title')}</h3>
                <p className="text-sm text-muted">{t('cards.share.offline.body')}</p>
                <button type="button" className="btn" disabled={busy || !data || blocking || description.trim() === '' || category === '' || !license} onClick={() => void prepare()}>
                  {t('cards.share.offline.file')}
                </button>
                {file && (
                  <a className="text-accent hover:underline text-sm" href={file.link} target="_blank" rel="noopener noreferrer" data-testid="share-form-link">
                    {t('cards.share.offline.form')}
                  </a>
                )}
              </div>
            </div>
          ) : (
            github.data && <GithubSignedIn state={github.data} onSignedOut={() => void check.refetch()} />
          )}
        </div>
      )}
    </Dialog>
  )
}
