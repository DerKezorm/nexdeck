import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'

import { ApiError, get, post } from '../../api/client'
import type { BoardSummary } from '../../api/types'
import { Field } from '../../components/ui'
import { SettingsCard } from './SettingsPage'

export function BoardsSettings() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const boards = useQuery({ queryKey: ['boards'], queryFn: () => get<BoardSummary[]>('/boards') })
  const [name, setName] = useState('')
  const [yamlText, setYamlText] = useState('')
  const [error, setError] = useState('')
  return (
    <>
      <SettingsCard title={t('settings.boards.title')} description={t('settings.boards.help')}>
        <ul className="space-y-1.5 mb-4">
          {(boards.data ?? []).map((board) => (
            <li key={board.id} className="flex items-center gap-2 rounded-xl border border-line p-2.5 text-sm">
              <Link to={`/b/${board.slug}`} className="flex-1 font-medium truncate hover:text-accent">
                {board.name}
              </Link>
              <span className="text-[11px] text-faint">{t('board.widgetCount', { count: board.widget_count })}</span>
              <span className="chip !py-0 text-[10px]">{t(`board.level.${board.permission}`, { defaultValue: board.permission })}</span>
              {board.provisioned && <span className="chip !py-0 text-[10px]">file</span>}
            </li>
          ))}
        </ul>
        <Field label={t('board.newName')} htmlFor="nb-name">
          <div className="flex gap-2">
            <input id="nb-name" className="input" value={name} onChange={(e) => setName(e.target.value)} />
            <button className="btn btn-accent flex-none" disabled={!name.trim()} onClick={() => void post<{ slug: string }>('/boards', { name: name.trim() }).then((created) => navigate(`/b/${created.slug}`))}>
              {t('common.create')}
            </button>
          </div>
        </Field>
      </SettingsCard>
      <SettingsCard title={t('board.import')} description={t('board.importHelp')}>
        <textarea className="input mb-2" rows={8} value={yamlText} onChange={(e) => setYamlText(e.target.value)} placeholder="nexdeck: 1&#10;board:&#10;  name: …" />
        {error && (
          <p className="text-sm text-bad mb-2" role="alert">
            {error}
          </p>
        )}
        <button
          className="btn"
          disabled={!yamlText.trim()}
          onClick={() => {
            setError('')
            void post<{ slug: string }>('/boards/import', { yaml_text: yamlText })
              .then((created) => navigate(`/b/${created.slug}`))
              .catch((failure) => setError(failure instanceof ApiError ? failure.message : t('errors.network')))
          }}
        >
          {t('board.importRun')}
        </button>
        <p className="text-[11px] text-faint mt-3">{t('settings.boards.provisioning')}</p>
      </SettingsCard>
    </>
  )
}
