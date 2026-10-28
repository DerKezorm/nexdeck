import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Copy, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { ApiError, get, post } from '../../api/client'
import type { BoardSummary } from '../../api/types'
import { RightsEditor } from '../../components/mcp/RightsEditor'
import { Confirm, Field, Select } from '../../components/ui'
import { addCommand, EXPIRIES, expiredKey, jsonConfig, revokeKey, type McpCreated, type McpKey, type McpLevel, type McpStatus, type McpTool } from '../../lib/mcp'
import { useMcpTexts } from '../../lib/mcpTexts'
import { useAuth } from '../../stores/auth'
import { SettingsCard } from './SettingsCard'

/**
 * "AI from outside (MCP)" in the account settings, beside the API tokens.
 *
 * A key lets a program such as Claude Code look at the boards of this account
 * over MCP. It carries its own level, its own boards and its own rights per
 * tool, and it is shown once. Loaded on its own, when the page opens.
 */
export function McpKeys() {
  const ready = useMcpTexts()
  const role = useAuth((state) => state.user?.role)
  if (!ready || !role || role === 'guest') return null
  return <Section admin={role === 'admin'} />
}

function CopyLine({ label, text, testid }: { label: string; text: string; testid: string }) {
  const { t } = useTranslation()
  return (
    <div className="mt-2">
      <div className="flex items-center gap-2">
        <span className="text-[11px] font-medium text-muted flex-1">{label}</span>
        <button className="btn btn-icon h-7 w-7" onClick={() => void navigator.clipboard?.writeText(text)} aria-label={t('mcp.keys.copyLine', { what: label })}>
          <Copy size={13} />
        </button>
      </div>
      <pre className="text-[11px] num whitespace-pre-wrap break-all rounded-lg border border-line p-2" data-testid={testid}>
        {text}
      </pre>
    </div>
  )
}

function Section({ admin }: { admin: boolean }) {
  const { t } = useTranslation()
  const status = useQuery({ queryKey: ['mcp-status'], queryFn: () => get<McpStatus>('/mcp/status') })
  const tools = useQuery({ queryKey: ['mcp-tools'], queryFn: () => get<McpTool[]>('/mcp/tools') })
  const keys = useQuery({ queryKey: ['mcp-keys'], queryFn: () => get<McpKey[]>('/mcp/keys') })
  const boards = useQuery({ queryKey: ['boards'], queryFn: () => get<BoardSummary[]>('/boards') })

  const [name, setName] = useState('')
  const [level, setLevel] = useState<McpLevel>('read')
  const [days, setDays] = useState('90')
  const [allBoards, setAllBoards] = useState(true)
  const [picked, setPicked] = useState<number[]>([])
  const [fresh, setFresh] = useState<McpCreated | null>(null)
  const [failure, setFailure] = useState('')
  const [open, setOpen] = useState<number | null>(null)
  const [revoking, setRevoking] = useState<McpKey | null>(null)

  if (!status.data) return null
  const info = status.data
  const list = keys.data ?? []
  const names = new Map((boards.data ?? []).map((board) => [board.id, board.name]))
  const canAct = info.max_level === 'act'
  const complete = !!name.trim() && (allBoards || picked.length > 0)

  const create = async () => {
    setFailure('')
    try {
      const created = await post<McpCreated>('/mcp/keys', {
        name: name.trim(),
        level: canAct ? level : 'read',
        expires_days: days === 'never' ? null : Number(days),
        boards: allBoards ? null : picked,
      })
      setFresh(created)
      setName('')
      setLevel('read')
      setAllBoards(true)
      setPicked([])
      void keys.refetch()
    } catch (error) {
      setFailure(error instanceof ApiError ? error.message : t('errors.network'))
    }
  }

  return (
    <div id="mcp">
      <SettingsCard title={t('mcp.keys.title')} description={t('mcp.keys.help')}>
        {!info.allowed && (
          <p className="rounded-xl border border-warn/50 p-3 mb-4 text-sm" data-testid="mcp-off">
            {admin ? (
              <>
                {t('mcp.keys.offAdmin')}{' '}
                <Link to="/system/mcp" className="text-accent">
                  {t('mcp.keys.offAdminLink')}
                </Link>
              </>
            ) : (
              t('mcp.keys.off')
            )}
          </p>
        )}
        {fresh && (
          <div className="glass rounded-xl p-3 mb-4 text-sm" data-testid="mcp-fresh">
            <p className="mb-1">{t('mcp.keys.created')}</p>
            <div className="flex items-center gap-2">
              <code className="num text-xs break-all flex-1" data-testid="mcp-token">
                {fresh.token}
              </code>
              <button className="btn btn-icon" onClick={() => void navigator.clipboard?.writeText(fresh.token)} aria-label={t('common.copy')}>
                <Copy size={14} />
              </button>
            </div>
            <CopyLine label={t('mcp.keys.claudeCode')} text={addCommand(info.endpoint, fresh.token)} testid="mcp-command" />
            <CopyLine label={t('mcp.keys.json')} text={jsonConfig(info.endpoint, fresh.token)} testid="mcp-json" />
            <button className="btn mt-3" onClick={() => setFresh(null)}>
              {t('mcp.keys.copied')}
            </button>
          </div>
        )}
        <ul className="space-y-1.5 mb-4" aria-label={t('mcp.keys.title')}>
          {list.map((row) => {
            const gone = row.revoked
            const over = !gone && expiredKey(row)
            const shown = open === row.id && !gone && !over
            return (
              <li key={row.id} className={`rounded-xl border border-line p-2.5 text-sm ${gone || over ? 'opacity-60' : ''}`} data-testid={`mcp-key-${row.id}`}>
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="flex-1 min-w-[160px] truncate">
                    {row.kind === 'oauth' && row.client ? row.client : row.name} <span className="num text-xs text-faint">{row.prefix}…</span>
                  </span>
                  {row.kind === 'oauth' && <span className="chip text-[11px] text-muted">{t('mcp.keys.connected')}</span>}
                  <span className={`chip text-[11px] ${row.level === 'act' ? 'text-warn' : 'text-muted'}`}>{t(`mcp.level.${row.level}`)}</span>
                  {gone && <span className="chip text-[11px] text-bad">{t('mcp.keys.revoked')}</span>}
                  {over && <span className="chip text-[11px] text-bad">{t('mcp.keys.expired')}</span>}
                  {!gone && (
                    <button className="btn btn-icon h-7 w-7 btn-danger" onClick={() => setRevoking(row)} aria-label={t('mcp.keys.revokeKey', { name: row.name })}>
                      <Trash2 size={14} />
                    </button>
                  )}
                </div>
                <p className="text-[11.5px] text-muted mt-1">
                  {row.boards === null ? t('mcp.keys.boardsAll') : t('mcp.keys.boardsSome', { names: row.boards.map((id) => names.get(id) ?? '…').join(', ') || '…' })}
                  {' · '}
                  {row.last_used_at ? t('mcp.keys.lastUsed', { when: new Date(row.last_used_at).toLocaleString() }) : t('mcp.keys.neverUsed')}
                  {' · '}
                  {row.expires_at ? t('mcp.keys.expiresOn', { date: new Date(row.expires_at).toLocaleDateString() }) : t('mcp.keys.noExpiry')}
                </p>
                {!gone && !over && (
                  <button className="btn btn-flat mt-1 -ml-2 text-[12.5px]" aria-expanded={shown} onClick={() => setOpen(shown ? null : row.id)}>
                    {shown ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    {t('mcp.rights.title')}
                  </button>
                )}
                {shown && tools.data && <RightsEditor keyRow={row} tools={tools.data} admin={admin} onSaved={() => void keys.refetch()} />}
              </li>
            )
          })}
        </ul>
        {info.allowed && (
          <>
            <Field label={t('mcp.form.name')} htmlFor="mcp-name">
              <input id="mcp-name" className="input" value={name} placeholder={t('mcp.form.namePlaceholder')} onChange={(event) => setName(event.target.value)} />
            </Field>
            {canAct && (
              <Field label={t('mcp.form.level')} htmlFor="mcp-level" help={t(`mcp.form.levelHelp.${level}`)}>
                <Select
                  id="mcp-level"
                  value={level}
                  onChange={(value) => setLevel(value === 'act' ? 'act' : 'read')}
                  options={[
                    { value: 'read', label: t('mcp.level.read') },
                    { value: 'act', label: t('mcp.level.act') },
                  ]}
                />
              </Field>
            )}
            <Field label={t('mcp.form.expires')} htmlFor="mcp-expires">
              <Select
                id="mcp-expires"
                value={days}
                onChange={setDays}
                options={EXPIRIES.map((value) => ({ value: value === null ? 'never' : String(value), label: value === null ? t('mcp.form.never') : t('mcp.form.days', { days: value }) }))}
              />
            </Field>
            <fieldset className="mb-3">
              <legend className="block text-xs font-medium text-muted mb-1">{t('mcp.form.boards')}</legend>
              <label className="flex items-center gap-2 text-sm py-0.5">
                <input type="radio" name="mcp-boards" className="accent-[var(--nd-accent)]" checked={allBoards} onChange={() => setAllBoards(true)} />
                {t('mcp.form.boardsAll')}
              </label>
              <label className="flex items-center gap-2 text-sm py-0.5">
                <input type="radio" name="mcp-boards" className="accent-[var(--nd-accent)]" checked={!allBoards} onChange={() => setAllBoards(false)} />
                {t('mcp.form.boardsPick')}
              </label>
              {!allBoards && (
                <ul className="ml-6 mt-1 space-y-0.5">
                  {(boards.data ?? []).map((board) => (
                    <li key={board.id}>
                      <label className="flex items-center gap-2 text-sm">
                        <input
                          type="checkbox"
                          className="accent-[var(--nd-accent)] w-4 h-4"
                          checked={picked.includes(board.id)}
                          onChange={(event) => setPicked((current) => (event.target.checked ? [...current, board.id] : current.filter((id) => id !== board.id)))}
                        />
                        {board.name}
                      </label>
                    </li>
                  ))}
                </ul>
              )}
            </fieldset>
            {failure && <p className="text-xs text-bad mb-2">{failure}</p>}
            <button className="btn btn-accent" disabled={!complete} onClick={() => void create()}>
              {t('mcp.form.create')}
            </button>
          </>
        )}
      </SettingsCard>
      <Confirm
        open={!!revoking}
        danger
        title={t('mcp.keys.revokeTitle')}
        body={revoking ? t('mcp.keys.revokeBody', { name: revoking.name }) : ''}
        confirmLabel={t('mcp.keys.revoke')}
        onCancel={() => setRevoking(null)}
        onConfirm={() => {
          const target = revoking
          setRevoking(null)
          if (target) void revokeKey(target.id).then(() => keys.refetch())
        }}
      />
    </div>
  )
}
