import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, ThumbsUp } from 'lucide-react'
import { lazy, Suspense, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { get, serverUrl } from '../../../api/client'
import { Select } from '../../../components/ui'
import { entryPath, pictureSrc, type ShopDetail, type ShopEntry, type ShopInstalledAnswer, type ShopState } from '../../../lib/cardShop'
import { pickText } from '../../../lib/cardText'
import { useGround } from '../../../lib/ground'
import { safeUrl } from '../../../lib/safeUrl'
import { Changelog } from './Changelog'
import { InstallDialog } from './InstallDialog'
import { PlaceOnBoard } from './PlaceOnBoard'
import { SkinUpdateDialog } from './SkinUpdateDialog'
import { UpdateDialog } from './UpdateDialog'
import { CheckedClass, ShopActs, useWarningText } from './ShopActs'
import { hasDiscussion, ThumbButton, ThumbNotes, ThumbSignIn, useThumb } from './shopThumb'
import { ShopBadges } from './ShopTile'

const ShopPreview = lazy(() => import('./ShopPreview'))

/** A date as people read it, in the viewer's language. */
function day(value: string, lang: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString(lang, { year: 'numeric', month: 'long', day: 'numeric' })
}

/** One fact of the detail page: a small label over its value. */
function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] text-faint">{label}</dt>
      <dd className="text-sm break-words">{children}</dd>
    </div>
  )
}

/**
 * One entry of the shop (KARTEN-14 AC-5, AC-6, AC-7, AC-14, EC-2, EC-3): description, list of changes, where it is based,
 * what it reads and which buttons it has, author, thumbs, version, license and the day it last changed, and the ways on:
 * preview with my data, install, place on a board.
 */
export function ShopDetailPage({
  entry,
  entries,
  state,
  onBack,
  onOpenEntry,
}: {
  entry: ShopEntry
  entries: ShopEntry[]
  state: ShopState
  onBack: () => void
  onOpenEntry: (id: string) => void
}) {
  const { t, i18n } = useTranslation()
  const lang = i18n.language
  const ground = useGround((s) => s.mode)
  const detail = useQuery({ queryKey: ['workshop-entry', entry.id], queryFn: () => get<ShopDetail>(`/workshop/entries/${entryPath(entry)}`), retry: false, refetchOnWindowFocus: false })
  const [previewing, setPreviewing] = useState(false)
  const [picked, setPicked] = useState('')
  const [installing, setInstalling] = useState(false)
  const [placing, setPlacing] = useState<{ slug: string; connection: number | null } | null>(null)
  const [done, setDone] = useState(false)
  const [updating, setUpdating] = useState(false)

  const name = pickText(entry.name, lang) || entry.slug
  const full = detail.data
  const connection = entry.connections.find((one) => String(one.id) === picked) ?? entry.connections[0] ?? null
  const basedOn = entry.based_on ? entries.find((one) => one.id === entry.based_on) : undefined
  const discussion = safeUrl(entry.discussion)
  const thumb = useThumb(entry, true)
  // What it reads and presses comes from the checked file, never from the catalog's words (the list's entry).
  const checked: ShopEntry | undefined = detail.isError ? { ...entry, verified: false } : full
  const warningText = useWarningText()
  const installed = entry.installed
  const recalled = entry.removed

  return (
    <div data-testid="shop-detail">
      <button className="btn btn-flat mb-3" onClick={onBack}>
        <ArrowLeft size={15} /> {t('cards.shop.back')}
      </button>

      <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <div className="aspect-[4/3] rounded-xl overflow-hidden bg-[color-mix(in_srgb,var(--nd-text)_6%,transparent)] flex items-center justify-center">
          <img src={serverUrl(pictureSrc(entry, ground))} alt="" className="w-full h-full object-contain" onError={(event) => (event.currentTarget.style.visibility = 'hidden')} />
        </div>
        <div className="min-w-0 grid gap-3 content-start">
          <div>
            <h3 className="text-lg font-semibold break-words">{name}</h3>
            <p className="text-sm text-muted">{t('cards.shop.by', { author: entry.author.login })}</p>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="chip !py-0 text-[11px]">{t(`cards.shop.type.${entry.type}`)}</span>
            {entry.type !== 'skin' && <CheckedClass entry={checked} />}
            <ShopBadges entry={entry} />
          </div>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
            <Fact label={t('cards.shop.facts.author')}>{entry.author.login}</Fact>
            <Fact label={t('cards.shop.facts.thumbs')}>
              {hasDiscussion(entry) ? (
                <ThumbButton thumb={thumb} onPress={() => void thumb.toggle()} />
              ) : (
                <span className="inline-flex items-center gap-1">
                  <ThumbsUp size={13} aria-hidden="true" /> {entry.thumbs}
                </span>
              )}
              {discussion && (
                <>
                  {' · '}
                  <a className="text-accent hover:underline" href={discussion} target="_blank" rel="noopener noreferrer">
                    {t('cards.shop.facts.discussion')}
                  </a>
                </>
              )}
              <ThumbNotes thumb={thumb} />
            </Fact>
            <Fact label={t('cards.shop.facts.version')}>{entry.version}</Fact>
            <Fact label={t('cards.shop.facts.license')}>{entry.license || t('cards.shop.facts.noLicense')}</Fact>
            <Fact label={t('cards.shop.facts.changed')}>{day(entry.updated_at, lang)}</Fact>
            {entry.based_on && (
              <Fact label={t('cards.shop.facts.basedOn')}>
                {basedOn ? (
                  <button className="text-accent hover:underline text-left" onClick={() => onOpenEntry(basedOn.id)}>
                    {pickText(basedOn.name, lang) || basedOn.slug}
                  </button>
                ) : (
                  entry.based_on
                )}
              </Fact>
            )}
          </dl>
          <ThumbSignIn thumb={thumb} />
        </div>
      </div>

      {recalled && (
        <p className={`mt-4 text-sm rounded-xl border p-3 ${recalled.level === 'harmful' ? 'border-bad/60 text-bad' : 'border-warn/60 text-warn'}`} role="note" data-testid="shop-removed-note" data-level={recalled.level}>
          <span className="font-medium">{t('cards.shop.removed')}</span>
          {recalled.reason ? `: ${recalled.reason}` : ''}
        </p>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-2 max-sm:flex-col max-sm:items-stretch" data-testid="shop-actions">
        {entry.type === 'card' && !recalled && (
          <>
            {entry.connections.length > 1 && (
              <Select className="!w-auto" value={String(connection?.id ?? '')} onChange={setPicked} options={entry.connections.map((one) => ({ value: String(one.id), label: one.name }))} id="shop-preview-connection" />
            )}
            <button className="btn" disabled={!connection} aria-expanded={previewing} onClick={() => setPreviewing(!previewing)}>
              {t('cards.shop.previewWithMine')}
            </button>
          </>
        )}
        {!recalled && installed === null && !entry.needs_newer && (
          <button className="btn btn-accent max-sm:w-full max-sm:h-12 max-sm:text-base" onClick={() => setInstalling(true)}>
            {t('cards.shop.install.button')}
          </button>
        )}
        {!recalled && installed === null && entry.needs_newer && (
          <button className="btn" disabled>
            {t('cards.shop.needsNexdeck', { version: entry.min_nexdeck ?? '' })}
          </button>
        )}
        {installed !== null && (
          <>
            <span className="chip" data-testid="shop-installed-version">
              {t('cards.shop.installedVersion', { version: installed.version })}
            </span>
            {installed.update && !recalled && (
              <button className="btn btn-accent" onClick={() => setUpdating(true)}>
                {t('cards.shop.update.button')}
              </button>
            )}
            {entry.type === 'card' && (
              <button className="btn" onClick={() => setPlacing({ slug: installed.slug, connection: connection?.id ?? null })}>
                {t('cards.shop.place.action')}
              </button>
            )}
          </>
        )}
        {entry.type === 'card' && !recalled && entry.connections.length === 0 && <span className="text-xs text-muted">{t('cards.shop.noPreviewConnection')}</span>}
      </div>
      {done && (
        <p className="mt-2 text-sm text-ok" role="status">
          {entry.type === 'skin' ? (
            <>
              {t('cards.shop.install.skinDone')}{' '}
              <Link className="underline" to="/system/skins">
                {t('cards.shop.install.toSkins')}
              </Link>
            </>
          ) : (
            t('cards.shop.install.done')
          )}
        </p>
      )}

      {full?.files_warning && (
        <p className="mt-3 text-sm text-warn" role="note" data-testid="shop-files-warning">
          {t('cards.shop.filesWarning', { message: warningText(full.files_warning) })}
        </p>
      )}

      {previewing && connection && (
        <div className="mt-3">
          <Suspense fallback={null}>
            <ShopPreview entry={entry} connection={connection.id} />
          </Suspense>
        </div>
      )}

      <section className="mt-6 grid gap-1">
        <h4 className="text-[11px] uppercase tracking-wide text-faint">{t('cards.shop.sections.description')}</h4>
        <p className="text-sm whitespace-pre-wrap break-words">{entry.description}</p>
      </section>

      <section className="mt-4 grid gap-1">
        <h4 className="text-[11px] uppercase tracking-wide text-faint">{t('cards.shop.sections.changes')}</h4>
        {detail.isPending ? (
          <p className="text-sm text-muted">{t('cards.shop.loading')}</p>
        ) : full?.changelog ? (
          <Changelog text={full.changelog} testId="shop-changelog" />
        ) : (
          <p className="text-sm text-muted">{t('cards.shop.noChanges')}</p>
        )}
      </section>

      <div className="mt-4 grid gap-4">
        <ShopActs entry={checked} />
      </div>

      <InstallDialog
        entry={entry}
        riskAcknowledged={state.risk_acknowledged}
        connections={entry.connections}
        open={installing}
        onClose={() => setInstalling(false)}
        onInstalled={(answer: ShopInstalledAnswer, chosen) => {
          setDone(true)
          if (answer.slug && entry.type === 'card') setPlacing({ slug: answer.slug, connection: chosen })
        }}
      />
      {entry.type === 'skin' ? (
        <SkinUpdateDialog skin={installed?.slug ?? ''} open={updating} onClose={() => setUpdating(false)} />
      ) : (
        <UpdateDialog slug={installed?.slug ?? ''} name={name} open={updating} onClose={() => setUpdating(false)} />
      )}
      <PlaceOnBoard slug={placing?.slug ?? ''} prefer={placing?.connection ?? null} open={placing !== null} onClose={() => setPlacing(null)} />
    </div>
  )
}
