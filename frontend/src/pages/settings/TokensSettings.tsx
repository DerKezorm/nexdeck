import { useQuery } from '@tanstack/react-query'
import { Copy, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { del, get, post } from '../../api/client'
import type { ApiToken } from '../../api/types'
import { Field } from '../../components/ui'
import { SettingsCard } from './SettingsCard'

export function TokensSettings() {
  const { t } = useTranslation()
  const tokens = useQuery({ queryKey: ['tokens'], queryFn: () => get<ApiToken[]>('/tokens') })
  const [name, setName] = useState('')
  const [fresh, setFresh] = useState<ApiToken | null>(null)
  return (
    <SettingsCard title={t('settings.tokens.title')} description={t('settings.tokens.help')}>
      <ul className="space-y-1.5 mb-4">
        {(tokens.data ?? []).map((token) => (
          <li key={token.id} className="flex items-center gap-2 rounded-xl border border-line p-2.5 text-sm">
            <span className="flex-1 truncate">
              {token.name} <span className="num text-xs text-faint">{token.prefix}…</span>
            </span>
            <span className="text-[11px] text-faint">{token.last_used_at ? new Date(token.last_used_at).toLocaleString() : t('settings.tokens.neverUsed')}</span>
            <button className="btn btn-icon h-7 w-7 btn-danger" onClick={() => void del(`/tokens/${token.id}`).then(() => tokens.refetch())} aria-label={t('common.delete')}>
              <Trash2 size={14} />
            </button>
          </li>
        ))}
      </ul>
      {fresh && (
        <div className="glass rounded-xl p-3 mb-4 text-sm">
          <p className="mb-1">{t('settings.tokens.created')}</p>
          <div className="flex items-center gap-2">
            <code className="num text-xs break-all flex-1">{fresh.token}</code>
            <button className="btn btn-icon" onClick={() => void navigator.clipboard?.writeText(fresh.token ?? '')} aria-label={t('common.copy')}>
              <Copy size={14} />
            </button>
          </div>
          <p className="text-[11px] text-faint mt-2">{t('settings.tokens.usage')}</p>
          <pre className="text-[11px] num mt-1 whitespace-pre-wrap">{`curl -H "Authorization: Bearer ${fresh.token}" ${window.location.origin}/api/v1/boards`}</pre>
        </div>
      )}
      <Field label={t('settings.tokens.name')} htmlFor="t-name">
        <div className="flex gap-2">
          <input id="t-name" className="input" value={name} placeholder="Home Assistant" onChange={(e) => setName(e.target.value)} />
          <button
            className="btn btn-accent flex-none"
            disabled={!name.trim()}
            onClick={() =>
              void post<ApiToken>('/tokens', { name: name.trim() }).then((created) => {
                setFresh(created)
                setName('')
                void tokens.refetch()
              })
            }
          >
            {t('common.create')}
          </button>
        </div>
      </Field>
    </SettingsCard>
  )
}
