import { useQuery } from '@tanstack/react-query'
import { Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, get, put } from '../../api/client'
import { Confirm, Field, Select, Switch, Toast } from '../../components/ui'
import { expiredKey, ownerOf, revokeKey, type McpAdminSettings, type McpKey, type McpLevel, type McpTool } from '../../lib/mcp'
import { useMcpTexts } from '../../lib/mcpTexts'
import { SettingsCard } from './SettingsCard'

/**
 * "AI from outside (MCP)" under System: the switches for the whole
 * installation, the list of blocked tools and every key of every account.
 *
 * Off by default. The highest level and the block list reach keys that
 * already exist, not only new ones.
 */
export function McpAdmin() {
  const ready = useMcpTexts()
  return ready ? <Panel /> : null
}

function Panel() {
  const { t } = useTranslation()
  const saved = useQuery({ queryKey: ['mcp-admin'], queryFn: () => get<McpAdminSettings>('/mcp/admin') })
  const tools = useQuery({ queryKey: ['mcp-tools'], queryFn: () => get<McpTool[]>('/mcp/tools') })
  const keys = useQuery({ queryKey: ['mcp-admin-keys'], queryFn: () => get<McpKey[]>('/mcp/admin/keys') })
  const [allowed, setAllowed] = useState(false)
  const [maxLevel, setMaxLevel] = useState<McpLevel>('act')
  const [oauth, setOauth] = useState(false)
  const [blocked, setBlocked] = useState<string[]>([])
  const [toast, setToast] = useState<{ text: string; level: 'ok' | 'error' } | null>(null)
  const [revoking, setRevoking] = useState<McpKey | null>(null)
  useEffect(() => {
    if (!saved.data) return
    setAllowed(saved.data.allowed)
    setMaxLevel(saved.data.max_level)
    setOauth(saved.data.oauth_allowed)
    setBlocked(saved.data.blocked_tools)
  }, [saved.data])

  const save = async () => {
    try {
      await put<McpAdminSettings>('/mcp/admin', { allowed, max_level: maxLevel, oauth_allowed: oauth, blocked_tools: blocked })
      await saved.refetch()
      void tools.refetch()
      setToast({ text: t('common.saved'), level: 'ok' })
    } catch (error) {
      setToast({ text: error instanceof ApiError ? error.message : t('errors.network'), level: 'error' })
    }
  }
  const list = keys.data ?? []
  return (
    <>
      <SettingsCard title={t('mcp.admin.title')} description={t('mcp.admin.help')}>
        <Switch checked={allowed} onChange={setAllowed} label={t('mcp.admin.allowed')} description={t('mcp.admin.allowedHelp')} />
        <Field label={t('mcp.admin.maxLevel')} htmlFor="mcp-max-level" help={t('mcp.admin.maxLevelHelp')}>
          <Select
            id="mcp-max-level"
            value={maxLevel}
            onChange={(value) => setMaxLevel(value === 'read' ? 'read' : 'act')}
            options={[
              { value: 'read', label: t('mcp.level.read') },
              { value: 'act', label: t('mcp.level.act') },
            ]}
          />
        </Field>
        <Switch checked={oauth} onChange={setOauth} label={t('mcp.admin.oauth')} description={t('mcp.admin.oauthHelp')} />
        <fieldset className="my-3">
          <legend className="block text-xs font-medium text-muted">{t('mcp.admin.blocked')}</legend>
          <p className="text-[11px] text-faint mb-1.5">{t('mcp.admin.blockedHelp')}</p>
          <ul className="space-y-1">
            {(tools.data ?? []).map((tool) => (
              <li key={tool.name}>
                <label className="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="accent-[var(--nd-accent)] w-4 h-4 mt-0.5 flex-none"
                    checked={blocked.includes(tool.name)}
                    onChange={(event) => setBlocked((current) => (event.target.checked ? [...current, tool.name] : current.filter((name) => name !== tool.name)))}
                  />
                  <span className="min-w-0">
                    <code className="num text-xs">{tool.name}</code>
                    <span className="block text-[11.5px] text-muted">{tool.description}</span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
        </fieldset>
        <div className="flex justify-end">
          <button className="btn btn-accent" onClick={() => void save()}>
            {t('common.save')}
          </button>
        </div>
      </SettingsCard>
      <SettingsCard title={t('mcp.admin.keysTitle')} description={t('mcp.admin.keysHelp')}>
        {!list.length && <p className="text-sm text-muted">{t('mcp.admin.noKeys')}</p>}
        <ul className="space-y-1.5" aria-label={t('mcp.admin.keysTitle')}>
          {list.map((row) => {
            const over = !row.revoked && expiredKey(row)
            return (
              <li key={row.id} className={`rounded-xl border border-line p-2.5 text-sm ${row.revoked || over ? 'opacity-60' : ''}`} data-testid={`mcp-admin-key-${row.id}`}>
                <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="flex-1 min-w-[160px] truncate">
                    {row.kind === 'oauth' && row.client ? row.client : row.name} <span className="num text-xs text-faint">{row.prefix}…</span>
                  </span>
                  <span className="chip text-[11px] text-muted">{ownerOf(row)}</span>
                  {row.kind === 'oauth' && <span className="chip text-[11px] text-muted">{t('mcp.keys.connected')}</span>}
                  <span className={`chip text-[11px] ${row.level === 'act' ? 'text-warn' : 'text-muted'}`}>{t(`mcp.level.${row.level}`)}</span>
                  {row.revoked && <span className="chip text-[11px] text-bad">{t('mcp.keys.revoked')}</span>}
                  {over && <span className="chip text-[11px] text-bad">{t('mcp.keys.expired')}</span>}
                  {!row.revoked && (
                    <button className="btn btn-icon h-7 w-7 btn-danger" onClick={() => setRevoking(row)} aria-label={t('mcp.admin.revokeKey', { name: row.name })}>
                      <Trash2 size={14} />
                    </button>
                  )}
                </div>
                <p className="text-[11.5px] text-muted mt-1">
                  {row.last_used_at ? t('mcp.keys.lastUsed', { when: new Date(row.last_used_at).toLocaleString() }) : t('mcp.keys.neverUsed')}
                  {' · '}
                  {row.expires_at ? t('mcp.keys.expiresOn', { date: new Date(row.expires_at).toLocaleDateString() }) : t('mcp.keys.noExpiry')}
                </p>
              </li>
            )
          })}
        </ul>
      </SettingsCard>
      <Confirm
        open={!!revoking}
        danger
        title={t('mcp.keys.revokeTitle')}
        body={revoking ? t('mcp.admin.revokeBody', { name: revoking.name, user: ownerOf(revoking) }) : ''}
        confirmLabel={t('mcp.keys.revoke')}
        onCancel={() => setRevoking(null)}
        onConfirm={() => {
          const target = revoking
          setRevoking(null)
          if (target) void revokeKey(target.id, true).then(() => keys.refetch())
        }}
      />
      {toast && (
        <Toast level={toast.level} onClose={() => setToast(null)}>
          {toast.text}
        </Toast>
      )}
    </>
  )
}
