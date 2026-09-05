import { useQuery } from '@tanstack/react-query'
import { Copy, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'

import { ApiError, del, get, patch, post, put, upload } from '../api/client'
import type { BoardSummary, BoardWithLive, KioskToken } from '../api/types'
import { BUNDLED } from './BackgroundLayer'
import { Confirm, Field, Select, Sheet, Switch } from './ui'

interface Props {
  open: boolean
  board: BoardWithLive
  boards: BoardSummary[]
  canEdit: boolean
  onClose: () => void
  onChanged: () => void
  /** Shows a background and the layout settings on the board while they are being chosen. */
  onPreview?: (background: BoardWithLive['background'], settings: Record<string, unknown>) => void
}

type Tab = 'boards' | 'look' | 'pages' | 'sharing' | 'kiosk' | 'file'

/** Board switcher plus the board's own settings: look, pages, sharing, kiosk, file. */
export function BoardSettingsSheet({ open, board, boards, canEdit, onClose, onChanged, onPreview }: Props) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [tab, setTab] = useState<Tab>('boards')
  const [name, setName] = useState(board.name)
  const [background, setBackground] = useState(board.background)
  const [settings, setSettings] = useState<Record<string, unknown>>(board.settings ?? {})
  const [error, setError] = useState('')
  const [uploading, setUploading] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deletingPage, setDeletingPage] = useState<{ id: number; name: string; widgets: number } | null>(null)
  const [newBoard, setNewBoard] = useState('')
  const [importText, setImportText] = useState('')
  const [kioskForm, setKioskForm] = useState({ name: 'Wall display', allow_actions: false, cycle_seconds: 0, dim_from: '', dim_to: '' })
  const [freshToken, setFreshToken] = useState<KioskToken | null>(null)
  const users = useQuery({ queryKey: ['users'], queryFn: () => get<{ id: number; username: string; display_name: string; role: string }[]>('/users'), enabled: open && tab === 'sharing' })
  const shares = useQuery({ queryKey: ['shares', board.slug], queryFn: () => get<{ id: number; user_id: number | null; role: string | null; level: string }[]>(`/boards/${board.slug}/shares`), enabled: open && tab === 'sharing' && canEdit })
  const kiosks = useQuery({ queryKey: ['kiosk', board.slug], queryFn: () => get<KioskToken[]>(`/boards/${board.slug}/kiosk-tokens`), enabled: open && tab === 'kiosk' && canEdit })

  // Opening the sheet starts from what is saved: an unsaved draft from last
  // time is gone, exactly as closing without saving promised.
  useEffect(() => {
    setName(board.name)
    setBackground(board.background)
    setSettings(board.settings ?? {})
    setError('')
  }, [board, open])
  useEffect(() => {
    if (open) onPreview?.(background, settings)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [background, settings, open])

  const saveLook = async () => {
    setError('')
    try {
      await patch(`/boards/${board.slug}`, { name, background, settings })
      onChanged()
      onClose()
    } catch (failure) {
      setError(failure instanceof ApiError ? failure.message : t('errors.network'))
    }
  }

  const tabs: Tab[] = canEdit ? ['boards', 'look', 'pages', 'sharing', 'kiosk', 'file'] : ['boards', 'file']

  return (
    <Sheet open={open} onClose={onClose} title={t('board.settings')} wide>
      <div className="flex gap-1 mb-4 flex-wrap">
        {tabs.map((entry) => (
          <button key={entry} className="btn h-8 text-xs" aria-pressed={tab === entry} onClick={() => setTab(entry)}>
            {t(`board.tabs.${entry}`)}
          </button>
        ))}
      </div>
      {error && (
        <p className="text-sm text-bad mb-2" role="alert">
          {error}
        </p>
      )}

      {tab === 'boards' && (
        <div>
          <ul className="space-y-1 mb-4">
            {boards.map((entry) => (
              <li key={entry.id}>
                <button
                  className={`w-full text-left flex items-center gap-3 px-3 py-2 rounded-xl ${entry.id === board.id ? 'bg-accent-soft' : 'hover:bg-surface-hover'}`}
                  onClick={() => {
                    onClose()
                    navigate(`/b/${entry.slug}`)
                  }}
                >
                  <span className="flex-1 text-sm font-medium">{entry.name}</span>
                  <span className="text-[11px] text-faint">{t('board.widgetCount', { count: entry.widget_count })}</span>
                  {entry.provisioned && <span className="chip !py-0 text-[10px]">file</span>}
                </button>
              </li>
            ))}
          </ul>
          <div className="flex gap-2">
            <input className="input" placeholder={t('board.newName')} value={newBoard} onChange={(e) => setNewBoard(e.target.value)} />
            <button
              className="btn btn-accent flex-none"
              disabled={!newBoard.trim()}
              onClick={() => {
                void post<{ slug: string }>('/boards', { name: newBoard.trim() }).then((created) => {
                  setNewBoard('')
                  onChanged()
                  onClose()
                  navigate(`/b/${created.slug}`)
                })
              }}
            >
              {t('common.create')}
            </button>
          </div>
        </div>
      )}

      {tab === 'look' && (
        <div>
          <Field label={t('board.name')} htmlFor="b-name">
            <input id="b-name" className="input" value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label={t('board.background')}>
            <div className="grid grid-cols-4 gap-2">
              {Object.entries(BUNDLED).map(([key, gradient]) => (
                <button
                  key={key}
                  type="button"
                  className={`h-14 rounded-xl border ${background.kind === 'bundled' && (background.value ?? 'aurora') === key ? 'border-accent' : 'border-line'}`}
                  style={{ background: `${gradient === 'none' ? '' : gradient + ','} var(--nd-bg)` }}
                  onClick={() => setBackground({ kind: 'bundled', value: key })}
                  aria-label={key}
                  title={key}
                />
              ))}
            </div>
          </Field>
          <Field label={t('board.upload')} help={t('board.uploadHelp')}>
            <input
              className="input pt-1.5"
              type="file"
              accept="image/*"
              disabled={uploading}
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (!file) return
                setError('')
                setUploading(true)
                upload('/assets', file, { kind: 'background' })
                  .then((asset) => setBackground({ kind: 'upload', value: (asset as { url: string }).url, blur: background.blur ?? 18, dim: background.dim ?? 45 }))
                  .catch((failure) => setError(failure instanceof ApiError ? failure.message : t('errors.network')))
                  .finally(() => setUploading(false))
              }}
            />
            {uploading && <p className="text-[11px] text-muted mt-1">{t('common.loading')}</p>}
          </Field>
          {background.kind === 'upload' && (
            <div className="grid grid-cols-2 gap-3">
              <Field label={t('board.blur')}>
                <input type="range" min={0} max={40} value={background.blur ?? 18} onChange={(e) => setBackground({ ...background, blur: Number(e.target.value) })} className="w-full" />
              </Field>
              <Field label={t('board.dim')}>
                <input type="range" min={0} max={90} value={background.dim ?? 45} onChange={(e) => setBackground({ ...background, dim: Number(e.target.value) })} className="w-full" />
              </Field>
            </div>
          )}
          <Switch checked={Boolean(settings.compact)} onChange={(compact) => setSettings((current) => ({ ...current, compact }))} label={t('board.autoCompact')} description={t('board.autoCompactHelp')} />
          <p className="text-[11px] text-faint mb-3">{t('board.previewHint')}</p>
          <button className="btn btn-accent" onClick={() => void saveLook()}>
            {t('common.save')}
          </button>
        </div>
      )}

      {tab === 'pages' && (
        <ul className="space-y-2">
          {board.pages.map((page) => (
            <li key={page.id} className="flex items-center gap-2">
              <input
                className="input"
                defaultValue={page.name}
                onBlur={(e) => {
                  if (e.target.value.trim() && e.target.value !== page.name) void patch(`/pages/${page.id}`, { name: e.target.value.trim() }).then(onChanged)
                }}
              />
              <button
                className="btn btn-icon btn-danger"
                disabled={board.pages.length <= 1}
                onClick={() => setDeletingPage({ id: page.id, name: page.name, widgets: page.widgets.length })}
                aria-label={t('board.deletePageTitle', { name: page.name })}
                title={board.pages.length <= 1 ? t('board.lastPage') : t('board.deletePage')}
              >
                <Trash2 size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}

      {tab === 'sharing' && (
        <div>
          <p className="text-xs text-muted mb-3">{t('board.sharingHelp')}</p>
          {(['user', 'guest'] as const).map((role) => {
            const current = shares.data?.find((s) => s.role === role)
            return (
              <Field key={role} label={t(`board.shareRole.${role}`)}>
                <Select
                  value={current?.level ?? 'none'}
                  onChange={(level) => {
                    const others = (shares.data ?? []).filter((s) => s.role !== role).map((s) => ({ user_id: s.user_id, role: s.role, level: s.level }))
                    const next = level === 'none' ? others : [...others, { user_id: null, role, level }]
                    void put(`/boards/${board.slug}/shares`, { shares: next }).then(() => shares.refetch())
                  }}
                  options={[{ value: 'none', label: t('board.level.none') }, { value: 'view', label: t('board.level.view') }, { value: 'edit', label: t('board.level.edit') }, { value: 'act', label: t('board.level.act') }]}
                />
              </Field>
            )
          })}
          <h4 className="text-xs font-medium text-muted mt-4 mb-2">{t('board.shareUsers')}</h4>
          {(users.data ?? []).filter((u) => u.id !== board.owner_id).map((user) => {
            const current = shares.data?.find((s) => s.user_id === user.id)
            return (
              <div key={user.id} className="flex items-center gap-2 mb-2">
                <span className="flex-1 text-sm truncate">{user.display_name || user.username}</span>
                <Select
                  className="!w-40"
                  value={current?.level ?? 'none'}
                  onChange={(level) => {
                    const others = (shares.data ?? []).filter((s) => s.user_id !== user.id).map((s) => ({ user_id: s.user_id, role: s.role, level: s.level }))
                    const next = level === 'none' ? others : [...others, { user_id: user.id, role: null, level }]
                    void put(`/boards/${board.slug}/shares`, { shares: next }).then(() => shares.refetch())
                  }}
                  options={[{ value: 'none', label: t('board.level.none') }, { value: 'view', label: t('board.level.view') }, { value: 'edit', label: t('board.level.edit') }, { value: 'act', label: t('board.level.act') }]}
                />
              </div>
            )
          })}
        </div>
      )}

      {tab === 'kiosk' && (
        <div>
          <p className="text-xs text-muted mb-3">{t('board.kioskHelp')}</p>
          <ul className="space-y-2 mb-4">
            {(kiosks.data ?? []).map((token) => (
              <li key={token.id} className="flex items-center gap-2 rounded-xl border border-line p-2">
                <span className="flex-1 text-sm">
                  {token.name} <span className="text-faint num text-xs">{token.prefix}…</span>
                  {token.allow_actions && <span className="chip ml-2 !py-0 text-[10px]">{t('board.kioskActions')}</span>}
                </span>
                <button className="btn btn-icon btn-danger" onClick={() => void del(`/kiosk-tokens/${token.id}`).then(() => kiosks.refetch())} aria-label={t('common.delete')}>
                  <Trash2 size={14} />
                </button>
              </li>
            ))}
          </ul>
          {freshToken && (
            <div className="glass rounded-xl p-3 mb-4 text-sm">
              <p className="mb-1">{t('board.kioskCreated')}</p>
              <div className="flex items-center gap-2">
                <code className="num text-xs break-all flex-1">{`${window.location.origin}${freshToken.url}`}</code>
                <button className="btn btn-icon" onClick={() => void navigator.clipboard?.writeText(`${window.location.origin}${freshToken.url}`)} aria-label={t('common.copy')}>
                  <Copy size={14} />
                </button>
              </div>
            </div>
          )}
          <Field label={t('board.kioskName')}>
            <input className="input" value={kioskForm.name} onChange={(e) => setKioskForm((f) => ({ ...f, name: e.target.value }))} />
          </Field>
          <div className="grid grid-cols-3 gap-2">
            <Field label={t('board.kioskCycle')} help={t('board.kioskCycleHelp')}>
              <input className="input" type="number" min={0} value={kioskForm.cycle_seconds} onChange={(e) => setKioskForm((f) => ({ ...f, cycle_seconds: Number(e.target.value) || 0 }))} />
            </Field>
            <Field label={t('board.kioskDimFrom')}>
              <input className="input" type="time" value={kioskForm.dim_from} onChange={(e) => setKioskForm((f) => ({ ...f, dim_from: e.target.value }))} />
            </Field>
            <Field label={t('board.kioskDimTo')}>
              <input className="input" type="time" value={kioskForm.dim_to} onChange={(e) => setKioskForm((f) => ({ ...f, dim_to: e.target.value }))} />
            </Field>
          </div>
          <Switch checked={kioskForm.allow_actions} onChange={(allow_actions) => setKioskForm((f) => ({ ...f, allow_actions }))} label={t('board.kioskAllow')} description={t('board.kioskAllowHelp')} />
          <button className="btn btn-accent mt-2" onClick={() => void post<KioskToken>(`/boards/${board.slug}/kiosk-tokens`, kioskForm).then((created) => { setFreshToken(created); void kiosks.refetch() })}>
            {t('board.kioskCreate')}
          </button>
        </div>
      )}

      {tab === 'file' && (
        <div>
          <p className="text-xs text-muted mb-2">{t('board.fileHelp')}</p>
          <a className="btn mb-4 inline-flex" href={`/api/v1/boards/${board.slug}/export`} download>
            {t('board.export')}
          </a>
          <Field label={t('board.import')} help={t('board.importHelp')}>
            <textarea className="input" rows={6} value={importText} onChange={(e) => setImportText(e.target.value)} placeholder="nexdeck: 1&#10;board:&#10;  name: …" />
          </Field>
          <button
            className="btn"
            disabled={!importText.trim()}
            onClick={() => {
              setError('')
              void post<{ slug: string }>('/boards/import', { yaml_text: importText })
                .then((created) => {
                  onChanged()
                  onClose()
                  navigate(`/b/${created.slug}`)
                })
                .catch((failure) => setError(failure instanceof ApiError ? failure.message : t('errors.network')))
            }}
          >
            {t('board.importRun')}
          </button>
          {board.permission === 'owner' && !board.provisioned && (
            <div className="mt-6 pt-4 border-t border-line">
              <button className="btn btn-danger" onClick={() => setConfirmDelete(true)}>
                {t('board.delete')}
              </button>
            </div>
          )}
        </div>
      )}
      <Confirm
        open={deletingPage !== null}
        title={deletingPage ? t('board.deletePageTitle', { name: deletingPage.name }) : ''}
        body={deletingPage && deletingPage.widgets > 0 ? t('board.deletePageBody', { count: deletingPage.widgets }) : t('board.deletePageEmpty')}
        danger
        onCancel={() => setDeletingPage(null)}
        onConfirm={() => {
          const page = deletingPage
          setDeletingPage(null)
          if (page) void del(`/pages/${page.id}`).then(onChanged).catch((failure) => setError(failure instanceof ApiError ? failure.message : t('errors.network')))
        }}
      />
      <Confirm
        open={confirmDelete}
        title={t('board.delete')}
        body={t('board.deleteBody')}
        danger
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => {
          setConfirmDelete(false)
          void del(`/boards/${board.slug}`).then(() => {
            onChanged()
            onClose()
            navigate('/')
          })
        }}
      />
    </Sheet>
  )
}
