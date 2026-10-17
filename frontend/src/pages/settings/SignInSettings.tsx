/**
 * System, Sign-in: three cards one below the other, as the shared sign-in module lays them out for every nex app.
 * Order, wording and behaviour come from there; the parts (card, switch, field, dialog) are nexdeck's own.
 *
 * 1. Sign-in: password sign-in (locked on while no provider is active), the public address, the second factor.
 * 2. Sign-in providers: the list with its marks, the drag handle, and the form as a dialog.
 * 3. authentik in one step: address, token, "Set up", the blueprint, and the steps with the reason of a failure.
 *    Without a public address it suggests the browser's own and registers nothing guessed.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Copy, GripVertical } from 'lucide-react'
import { useEffect, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, del, get, patch, post, put, serverUrl } from '../../api/client'
import type { About } from '../../api/types'
import { Confirm, Dialog, Field, Switch, Toast } from '../../components/ui'
import {
  authentikIssuerChange,
  authentikProposal,
  authentikProxyWarning,
  authentikReasonKey,
  authentikRedirect,
  authentikStale,
  authentikStepKey,
  oidcErrorKey,
  oidcFormErrorKey,
  slugFromLabel,
  type AuthentikAddress,
} from '../../vendor/nexoidc/oidc'
import { SettingsCard } from './SettingsCard'

/** An entry as `GET /oidc/admin/providers` lists it (`providers.admin_view`); never a secret. */
export interface OidcProvider {
  id: number
  slug: string
  label: string
  issuer: string
  client_id: string
  has_secret: boolean
  scopes: string
  enabled: boolean
  auto_create: boolean
  trusts_second_factor: boolean
  managed: string
  position: number
  redirect_uri: string
  links: number
  editable: boolean
  registered_redirect_uri: string
  redirect_stale: boolean
}

interface ProviderForm {
  label: string
  slug?: string
  issuer: string
  client_id: string
  client_secret: string
  scopes: string
  enabled: boolean
  auto_create: boolean
  trusts_second_factor: boolean
}

interface SetupStep {
  key: string
  ok: boolean
  reason?: string
  status?: number
}

interface SetupResult {
  ok: boolean
  steps: SetupStep[]
  count?: number
  address?: AuthentikAddress | null
}

type Feedback = { text: string; level: 'ok' | 'error' } | null

/** What the server says with 409 `public_url_change`. */
type AddressQuestionValues = { count: number; address: string; hand: number }

function questionOf(values: Record<string, unknown>): AddressQuestionValues {
  return { count: Number(values.count ?? 0), address: String(values.address ?? ''), hand: Number(values.hand ?? 0) }
}

function AddressQuestion({ question }: { question: AddressQuestionValues }) {
  const { t } = useTranslation()
  return (
    <div className="space-y-2 text-sm text-muted" data-testid="address-question">
      {question.count > 0 && <p>{t('oidc.admin.addressChangeConfirm', { address: question.address })}</p>}
      {question.hand > 0 && <p>{t('oidc.admin.addressChangeHand', { count: question.hand })}</p>}
    </div>
  )
}

/** A refusal in the person's language: the module's sentence for its codes, else the server's text. */
function useProblem() {
  const { t } = useTranslation()
  return (failure: unknown): string => {
    if (!(failure instanceof ApiError)) return t('errors.network')
    const key = oidcFormErrorKey(failure.code) ?? oidcErrorKey(failure.code)
    return key ? t(key) : failure.message
  }
}

export function SignInSettings() {
  const providers = useQuery({ queryKey: ['oidc-admin-providers'], queryFn: () => get<OidcProvider[]>('/oidc/admin/providers') })
  const about = useQuery({ queryKey: ['about'], queryFn: () => get<About>('/about') })
  const [toast, setToast] = useState<Feedback>(null)
  const list = providers.data ?? []
  const reload = async () => {
    await providers.refetch()
    await about.refetch()
  }
  return (
    <>
      <SignInCard about={about.data} anyActive={list.some((entry) => entry.enabled)} reload={reload} tell={setToast} />
      <ProvidersCard providers={providers.data ?? null} publicUrl={about.data?.public_url ?? ''} reload={reload} tell={setToast} />
      <AuthentikCard reload={reload} />
      {toast && (
        <Toast level={toast.level} onClose={() => setToast(null)}>
          {toast.text}
        </Toast>
      )}
    </>
  )
}

// --- Card 1: sign-in -------------------------------------------------------------------------------------------------

function SignInCard({ about, anyActive, reload, tell }: { about: About | undefined; anyActive: boolean; reload: () => Promise<void>; tell: (feedback: Feedback) => void }) {
  const { t } = useTranslation()
  const problem = useProblem()
  const [address, setAddress] = useState('')
  const [question, setQuestion] = useState<AddressQuestionValues | null>(null)
  useEffect(() => {
    if (about) setAddress(about.public_url)
  }, [about])
  const save = (change: Record<string, unknown>) =>
    void patch('/settings', change)
      .then(() => reload())
      .then(() => tell({ text: t('common.saved'), level: 'ok' }))
      .catch((failure: unknown) => {
        if (failure instanceof ApiError && failure.code === 'public_url_change') {
          setQuestion(questionOf(failure.detail))
          return
        }
        tell({ text: failure instanceof ApiError && failure.code === 'public_url_invalid' ? t('oidc.authentik.why.unusable') : problem(failure), level: 'error' })
      })
  const passwordLogin = about?.password_login ?? true
  return (
    <SettingsCard title={t('oidc.admin.signInTitle')}>
      <div data-testid="sign-in-card">
        <Switch
          checked={passwordLogin}
          // Without an active provider nobody but an administrator could come in: the switch stays on.
          disabled={passwordLogin && !anyActive}
          onChange={(password_login) => save({ password_login })}
          label={t('oidc.admin.password')}
          description={t('oidc.admin.passwordHint')}
        />
        <form
          className="mt-2 flex items-start gap-2"
          onSubmit={(event) => {
            event.preventDefault()
            save({ public_url: address })
          }}
        >
          <div className="min-w-0 flex-1">
            <Field label={t('oidc.admin.address')} htmlFor="s-public-url" help={t('oidc.admin.addressHint')}>
              <input id="s-public-url" className="input" type="url" placeholder="https://deck.example.com" value={address} onChange={(e) => setAddress(e.target.value)} />
            </Field>
          </div>
          <button type="submit" className="btn flex-none mt-5">
            {t('common.save')}
          </button>
        </form>
        <Switch
          checked={about?.require_two_factor ?? false}
          onChange={(require_two_factor) => save({ require_two_factor })}
          label={t('settings.security.requireTwoFactor')}
          description={t('settings.security.requireTwoFactorHelp')}
        />
      </div>
      <Confirm
        open={question !== null}
        title={t('oidc.admin.address')}
        confirmLabel={t('common.save')}
        danger
        onCancel={() => setQuestion(null)}
        onConfirm={() => {
          setQuestion(null)
          save({ public_url: address, confirm_address: true })
        }}
      >
        {question && <AddressQuestion question={question} />}
      </Confirm>
    </SettingsCard>
  )
}

// --- Card 2: the provider list ---------------------------------------------------------------------------------------

/** The same issuer, however written at the end (the server's `same_issuer` for an issuer without a placeholder). */
function sameIssuer(a: string, b: string): boolean {
  return a.trim().replace(/\/+$/, '') === b.trim().replace(/\/+$/, '')
}

function ProvidersCard({ providers, publicUrl, reload, tell }: { providers: OidcProvider[] | null; publicUrl: string; reload: () => Promise<void>; tell: (feedback: Feedback) => void }) {
  const { t } = useTranslation()
  const problem = useProblem()
  const [editing, setEditing] = useState<OidcProvider | 'new' | null>(null)
  const [removing, setRemoving] = useState<{ entry: OidcProvider; count: number; only: number } | null>(null)
  const [dragged, setDragged] = useState<number | null>(null)
  const list = providers ?? []
  const readOnly = list.some((entry) => !entry.editable)
  const fail = (failure: unknown) => tell({ text: problem(failure), level: 'error' })

  const move = (from: number, to: number) => {
    if (from === to || to < 0 || to >= list.length) return
    const ids = list.map((entry) => entry.id)
    const [taken] = ids.splice(from, 1)
    ids.splice(to, 0, taken)
    void put('/oidc/admin/providers/order', { ids }).then(reload).catch(fail)
  }

  return (
    <SettingsCard title={t('oidc.admin.providersTitle')} description={t('oidc.admin.providersText')}>
      {providers !== null && list.length === 0 && <p className="text-sm text-muted mb-3">{t('oidc.admin.empty')}</p>}
      {list.length > 0 && (
        <ul className="space-y-1.5 mb-3" data-testid="provider-list">
          {list.map((entry, index) => (
            <li
              key={entry.id}
              className={`flex flex-wrap items-center gap-2 rounded-xl border border-line p-2.5 text-sm ${dragged === index ? 'opacity-50' : ''}`}
              draggable={!readOnly}
              onDragStart={() => setDragged(index)}
              onDragEnd={() => setDragged(null)}
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => {
                event.preventDefault()
                if (dragged !== null) move(dragged, index)
                setDragged(null)
              }}
            >
              {!readOnly && list.length > 1 && (
                <button
                  type="button"
                  className="btn btn-icon btn-flat h-7 w-7 cursor-grab"
                  aria-label={t('signIn.order', { name: entry.label })}
                  onKeyDown={(event) => {
                    if (event.key === 'ArrowUp') move(index, index - 1)
                    if (event.key === 'ArrowDown') move(index, index + 1)
                  }}
                >
                  <GripVertical size={14} />
                </button>
              )}
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium">{entry.label}</span>
                <span className="block truncate text-xs text-faint">{entry.issuer}</span>
              </span>
              <span className="flex flex-wrap items-center gap-1.5 text-xs">
                <span className={`rounded-full px-2 ${entry.enabled ? 'bg-[color-mix(in_srgb,var(--nd-ok)_15%,transparent)] text-ok' : 'border border-line text-muted'}`}>
                  {entry.enabled ? t('oidc.admin.active') : t('oidc.admin.inactive')}
                </span>
                {entry.managed === 'authentik' && <span className="rounded-full border border-accent px-2 text-accent">{t('oidc.admin.managed')}</span>}
              </span>
              {entry.editable && (
                <span className="flex gap-1.5">
                  <button type="button" className="btn h-7 text-xs" onClick={() => setEditing(entry)}>
                    {t('oidc.admin.edit')}
                  </button>
                  <button
                    type="button"
                    className="btn btn-danger h-7 text-xs"
                    onClick={() =>
                      void get<{ count: number; only: number }>(`/oidc/admin/providers/${entry.id}/impact`)
                        .then((impact) => setRemoving({ entry, count: impact.count, only: impact.only }))
                        .catch(fail)
                    }
                  >
                    {t('oidc.admin.remove')}
                  </button>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      {!readOnly && (
        <button type="button" className="btn btn-accent" onClick={() => setEditing('new')}>
          {t('oidc.admin.add')}
        </button>
      )}
      {editing !== null && (
        <ProviderDialog
          entry={editing === 'new' ? null : editing}
          publicUrl={publicUrl}
          onClose={() => setEditing(null)}
          onSaved={async () => {
            setEditing(null)
            await reload()
            tell({ text: t('common.saved'), level: 'ok' })
          }}
        />
      )}
      <Confirm
        open={removing !== null}
        title={t('oidc.admin.remove')}
        confirmLabel={t('oidc.admin.remove')}
        danger
        onCancel={() => setRemoving(null)}
        onConfirm={() => {
          const entry = removing?.entry
          setRemoving(null)
          if (entry) void del(`/oidc/admin/providers/${entry.id}`).then(reload).catch(fail)
        }}
      >
        {removing && <p className="text-sm text-muted">{t('oidc.admin.removeConfirm', { name: removing.entry.label, count: removing.count, only: removing.only })}</p>}
      </Confirm>
    </SettingsCard>
  )
}

const EMPTY: ProviderForm = {
  label: '',
  slug: '',
  issuer: '',
  client_id: '',
  client_secret: '',
  scopes: 'openid profile email',
  enabled: true,
  auto_create: false,
  trusts_second_factor: true,
}

type FieldName = 'label' | 'slug' | 'issuer' | 'client_id' | 'client_secret' | 'scopes' | 'id'

function CopyField({ value }: { value: string }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  return (
    <div className="flex gap-2 items-center">
      <code className="input flex-1 truncate font-mono text-xs leading-8" data-testid="provider-redirect">
        {value}
      </code>
      <button
        type="button"
        className="btn flex-none"
        onClick={() =>
          void navigator.clipboard
            ?.writeText(value)
            .then(() => setCopied(true))
            .catch(() => setCopied(false))
        }
      >
        <Copy size={14} />
        {copied ? t('signIn.copied') : t('signIn.copy')}
      </button>
    </div>
  )
}

/** The provider form as a dialog, fields in the module's order. */
function ProviderDialog({ entry, publicUrl, onClose, onSaved }: { entry: OidcProvider | null; publicUrl: string; onClose: () => void; onSaved: () => Promise<void> }) {
  const { t } = useTranslation()
  const problem = useProblem()
  const [form, setForm] = useState<ProviderForm>(
    entry
      ? {
          label: entry.label,
          issuer: entry.issuer,
          client_id: entry.client_id,
          client_secret: '',
          scopes: entry.scopes,
          enabled: entry.enabled,
          auto_create: entry.auto_create,
          trusts_second_factor: entry.trusts_second_factor,
        }
      : EMPTY,
  )
  // The short name follows the name on the button until it is typed itself.
  const [slugTyped, setSlugTyped] = useState(false)
  const [busy, setBusy] = useState(false)
  const [fieldError, setFieldError] = useState<{ field: FieldName; text: string } | null>(null)
  const [confirmIssuer, setConfirmIssuer] = useState<number | null>(null)
  const slug = entry ? entry.slug : slugTyped ? (form.slug ?? '') : slugFromLabel(form.label)
  const base = (publicUrl || window.location.origin).replace(/\/+$/, '')
  const redirect = entry ? entry.redirect_uri : `${base}/api/v1/oidc/${slug || '…'}/callback`
  const set = (change: Partial<ProviderForm>) => setForm((current) => ({ ...current, ...change }))

  const errorFor = (failure: unknown): { field: FieldName; text: string } => {
    const field = failure instanceof ApiError && typeof failure.detail.field === 'string' ? (failure.detail.field as FieldName) : 'id'
    return { field, text: problem(failure) }
  }

  const save = async () => {
    setBusy(true)
    setFieldError(null)
    try {
      const body = { ...form, slug: entry ? undefined : slug }
      if (entry) await put(`/oidc/admin/providers/${entry.id}`, body)
      else await post('/oidc/admin/providers', body)
      await onSaved()
    } catch (failure) {
      setFieldError(errorFor(failure))
    } finally {
      setBusy(false)
    }
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    // Another issuer is another provider: say first how many accounts will have to link again.
    if (entry && entry.links > 0 && !sameIssuer(entry.issuer, form.issuer)) {
      try {
        const impact = await get<{ issuer_change: number }>(`/oidc/admin/providers/${entry.id}/impact?issuer=${encodeURIComponent(form.issuer.trim())}`)
        if (impact.issuer_change > 0) return setConfirmIssuer(impact.issuer_change)
      } catch (failure) {
        return setFieldError(errorFor(failure))
      }
    }
    await save()
  }

  const problemAt = (field: FieldName) =>
    fieldError?.field === field ? (
      <p role="alert" className="-mt-2 mb-3 text-xs text-bad">
        {fieldError.text}
      </p>
    ) : null

  return (
    <Dialog
      open
      onClose={() => !busy && onClose()}
      title={entry ? `${t('oidc.admin.edit')}: ${entry.label}` : t('oidc.admin.add')}
      footer={
        <>
          <button type="button" className="btn" onClick={onClose} disabled={busy}>
            {t('common.cancel')}
          </button>
          <button type="submit" form="provider-form" className="btn btn-accent" disabled={busy}>
            {t('common.save')}
          </button>
        </>
      }
    >
      <form id="provider-form" onSubmit={(event) => void submit(event)} data-testid="provider-form">
        <Field label={t('oidc.admin.label')} htmlFor="p-label">
          <input id="p-label" className="input" value={form.label} onChange={(e) => set({ label: e.target.value })} />
        </Field>
        {problemAt('label')}
        {entry ? (
          <p className="mb-3 text-xs text-muted">
            {t('oidc.admin.slug')}: <code className="font-mono">{entry.slug}</code>
          </p>
        ) : (
          <>
            <Field label={t('oidc.admin.slug')} htmlFor="p-slug" help={t('oidc.admin.slugHint')}>
              <input
                id="p-slug"
                className="input"
                value={slug}
                onChange={(e) => {
                  setSlugTyped(true)
                  set({ slug: e.target.value })
                }}
              />
            </Field>
            {problemAt('slug')}
          </>
        )}
        <Field label={t('oidc.admin.issuer')} htmlFor="p-issuer" help={t('oidc.admin.issuerHint')}>
          <input id="p-issuer" className="input" placeholder="https://auth.example.com/application/o/nexdeck/" value={form.issuer} onChange={(e) => set({ issuer: e.target.value })} />
        </Field>
        {problemAt('issuer')}
        <Field label={t('oidc.admin.clientId')} htmlFor="p-client">
          <input id="p-client" className="input" value={form.client_id} onChange={(e) => set({ client_id: e.target.value })} />
        </Field>
        {problemAt('client_id')}
        <Field label={t('oidc.admin.secret')} htmlFor="p-secret">
          <input
            id="p-secret"
            className="input"
            type="password"
            autoComplete="off"
            placeholder={entry?.has_secret ? t('oidc.admin.secretKept') : ''}
            value={form.client_secret}
            onChange={(e) => set({ client_secret: e.target.value })}
          />
        </Field>
        {problemAt('client_secret')}
        <div className="mb-3">
          <span className="block text-xs font-medium text-muted mb-1">{t('oidc.admin.redirect')}</span>
          <CopyField value={redirect} />
        </div>
        <Switch checked={form.enabled} onChange={(enabled) => set({ enabled })} label={t('oidc.admin.enabled')} />
        <Switch checked={form.auto_create} onChange={(auto_create) => set({ auto_create })} label={t('oidc.admin.autoCreate')} description={t('oidc.admin.autoCreateHint')} />
        <Switch
          checked={form.trusts_second_factor}
          onChange={(trusts_second_factor) => set({ trusts_second_factor })}
          label={t('oidc.admin.trustsSecondFactor')}
          description={t('oidc.admin.trustsSecondFactorHint')}
        />
        <details className="mt-2" open={fieldError?.field === 'scopes' ? true : undefined}>
          <summary className="cursor-pointer text-xs text-muted">{t('signIn.more')}</summary>
          <div className="mt-2">
            <Field label={t('oidc.admin.scopes')} htmlFor="p-scopes">
              <input id="p-scopes" className="input" value={form.scopes} onChange={(e) => set({ scopes: e.target.value })} />
            </Field>
            {problemAt('scopes')}
          </div>
        </details>
        {problemAt('id')}
      </form>
      <Confirm
        open={confirmIssuer !== null}
        title={t('oidc.admin.issuer')}
        confirmLabel={t('common.save')}
        danger
        onCancel={() => setConfirmIssuer(null)}
        onConfirm={() => {
          setConfirmIssuer(null)
          void save()
        }}
      >
        <p className="text-sm text-muted">{t('oidc.admin.issuerChangeConfirm', { count: confirmIssuer ?? 0 })}</p>
      </Confirm>
    </Dialog>
  )
}

// --- Card 3: authentik in one step ------------------------------------------------------------------------------------

async function fetchAddress(): Promise<AuthentikAddress | null> {
  try {
    return await get<AuthentikAddress>('/oidc/authentik/address')
  } catch {
    return null
  }
}

function AuthentikCard({ reload }: { reload: () => Promise<void> }) {
  const { t } = useTranslation()
  const queries = useQueryClient()
  const problem = useProblem()
  const [authentik, setAuthentik] = useState({ url: '', token: '' })
  const [steps, setSteps] = useState<SetupResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)
  // The button stopped before it wrote anything: another issuer, this many accounts would have to link again.
  const [asking, setAsking] = useState<{ count: number; adopt: boolean } | null>(null)
  // "Use it only" stopped: saving the address leaves a redirect address behind that a provider knows.
  const [question, setQuestion] = useState<AddressQuestionValues | null>(null)
  const [address, setAddress] = useState<AuthentikAddress | null>(null)
  useEffect(() => {
    let current = true
    void fetchAddress().then((found) => current && setAddress(found))
    return () => {
      current = false
    }
  }, [])

  // While nexdeck has no public address, the card offers the one the browser uses (never one the server guessed).
  const proposal = authentikProposal(window.location.origin, (globalThis as { __NEXDECK_BASE__?: string }).__NEXDECK_BASE__ ?? '')
  const missing = address !== null && address.public_url === ''
  const stale = address ? authentikStale(address) : null

  const take = async (found: AuthentikAddress | null) => {
    setAddress(found ?? (await fetchAddress()))
    await reload()
    void queries.invalidateQueries({ queryKey: ['about'] })
  }

  const start = async (confirm: boolean, adopt: boolean) => {
    setSteps(null)
    setAsking(null)
    setFailure(null)
    setBusy(true)
    try {
      const answer = await post<SetupResult>('/oidc/authentik/setup', {
        url: authentik.url,
        token: authentik.token,
        confirm_issuer_change: confirm,
        public_url: adopt ? proposal : '',
      })
      // Not a failure: the button waits for the administrator's yes, nothing was changed. The token stays.
      const count = authentikIssuerChange(answer)
      if (count !== null) {
        setAsking({ count, adopt })
        return
      }
      setSteps(answer)
      // The token was for this run only; it does not stay in the page either.
      setAuthentik((current) => ({ ...current, token: '' }))
      await take(answer.address ?? null)
    } catch (error) {
      setFailure(problem(error))
    } finally {
      setBusy(false)
    }
  }

  const adoptOnly = async (confirm: boolean) => {
    setQuestion(null)
    setFailure(null)
    try {
      await take(await post<AuthentikAddress>('/oidc/authentik/address', { public_url: proposal, confirm }))
    } catch (error) {
      if (error instanceof ApiError && error.code === 'public_url_change') return setQuestion(questionOf(error.detail))
      if (error instanceof ApiError && error.code === 'public_url_invalid') return setFailure(t('oidc.authentik.why.unusable'))
      setFailure(problem(error))
    }
  }

  return (
    <SettingsCard title={t('oidc.authentik.title')} description={t('oidc.authentik.text')}>
      {missing && address && (
        <div className="mb-3 space-y-1.5 rounded-xl border border-line px-3 py-2 text-xs text-warn" data-testid="authentik-no-address">
          <p>{t('oidc.authentik.noAddress')}</p>
          <p className="break-all font-mono text-sm text-[var(--nd-text)]" data-testid="authentik-proposal">
            {proposal}
          </p>
          <p className="break-all">
            {t('oidc.admin.redirect')}: <code className="font-mono">{authentikRedirect(proposal, address)}</code>
          </p>
          {authentikProxyWarning(proposal, address) && <p data-testid="authentik-proxy-warning">{t('oidc.authentik.proxyWarning', { address: address.seen })}</p>}
        </div>
      )}
      {stale && (
        <p className="mb-3 rounded-xl border border-line px-3 py-2 text-xs text-warn" data-testid="authentik-stale">
          {t('oidc.authentik.stale', { address: stale })}
        </p>
      )}
      <form
        className="grid sm:grid-cols-2 gap-x-3"
        onSubmit={(event) => {
          event.preventDefault()
          void start(false, missing)
        }}
      >
        <Field label={t('oidc.authentik.url')} htmlFor="a-url">
          <input id="a-url" className="input" type="url" placeholder="https://auth.example.com" value={authentik.url} onChange={(e) => setAuthentik((a) => ({ ...a, url: e.target.value }))} />
        </Field>
        <Field label={t('oidc.authentik.token')} htmlFor="a-token">
          <input id="a-token" className="input" type="password" autoComplete="new-password" value={authentik.token} onChange={(e) => setAuthentik((a) => ({ ...a, token: e.target.value }))} />
        </Field>
        <div className="flex flex-wrap items-center gap-2 sm:col-span-2">
          <button type="submit" className="btn btn-accent" disabled={busy || !authentik.url.trim() || !authentik.token.trim()}>
            {missing ? t('oidc.authentik.adopt') : t('oidc.authentik.run')}
          </button>
          {missing && (
            <button type="button" className="btn" disabled={busy} onClick={() => void adoptOnly(false)}>
              {t('oidc.authentik.adoptOnly')}
            </button>
          )}
          {missing ? (
            <span className="text-sm text-faint">{t('oidc.authentik.blueprint')}</span>
          ) : (
            <a className="text-sm text-accent hover:underline" href={serverUrl('/api/v1/oidc/authentik/blueprint')} download>
              {t('oidc.authentik.blueprint')}
            </a>
          )}
        </div>
      </form>
      {busy && (
        <p className="mt-3 text-xs text-muted" aria-live="polite">
          {t('oidc.authentik.asking')}
        </p>
      )}
      {failure && (
        <p role="alert" className="mt-3 text-xs text-bad">
          {failure}
        </p>
      )}
      {steps && (
        <ol className="mt-3 space-y-1.5 text-sm" data-testid="authentik-steps">
          {steps.steps.map((step) => {
            const name = authentikStepKey(step.key)
            const why = step.ok ? null : authentikReasonKey(step.reason)
            return (
              <li key={step.key} className="flex gap-2">
                <span className={step.ok ? 'text-ok' : 'text-bad'} aria-hidden="true">
                  {step.ok ? '✓' : '✗'}
                </span>
                <span>
                  <span className={step.ok ? '' : 'font-medium text-bad'}>{name ? t(name) : step.key}</span>
                  {why && <span className="block text-xs text-muted">{t(why, { status: step.status ?? 0, count: steps.count ?? 0 })}</span>}
                </span>
              </li>
            )
          })}
        </ol>
      )}
      <Confirm
        open={asking !== null}
        title={t('oidc.authentik.title')}
        confirmLabel={t('oidc.authentik.run')}
        danger
        onCancel={() => setAsking(null)}
        onConfirm={() => void start(true, asking?.adopt ?? false)}
      >
        <p className="text-sm text-muted">{t('oidc.admin.issuerChangeConfirm', { count: asking?.count ?? 0 })}</p>
      </Confirm>
      <Confirm open={question !== null} title={t('oidc.admin.address')} confirmLabel={t('common.save')} danger onCancel={() => setQuestion(null)} onConfirm={() => void adoptOnly(true)}>
        {question && <AddressQuestion question={question} />}
      </Confirm>
    </SettingsCard>
  )
}
