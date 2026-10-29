/**
 * System, Skins: the skins of this installation, a new one from a starting
 * point (nothing, a copy, one of the looks, the console example), and the way
 * into the editor. Which skin everybody wears is chosen under Look.
 */
import { useQuery } from '@tanstack/react-query'
import { Pencil, Plus } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'

import { get } from '../../api/client'
import { Dialog, Spinner, Toast } from '../../components/ui'
import { useSkinTexts } from '../../lib/skin/texts'
import { SettingsCard } from '../settings/SettingsCard'
import { SkinShelf, useSkins } from '../settings/SkinChooser'
import type { Starter } from './SkinEditorPage'

export function SkinsPage() {
  const ready = useSkinTexts()
  const { t } = useTranslation()
  const navigate = useNavigate()
  const skins = useSkins()
  const [choosing, setChoosing] = useState(false)
  const [toast, setToast] = useState<{ text: string; level: 'ok' | 'error' } | null>(null)
  const starters = useQuery({ queryKey: ['skin-starters'], queryFn: () => get<{ starters: Starter[] }>('/skins/starters'), enabled: choosing })
  if (!ready || skins.isLoading) return <Spinner />
  const all = skins.data?.skins ?? []
  const own = all.filter((skin) => skin.origin !== 'builtin')
  const open = (from: string) => navigate(`/system/skins/new?from=${encodeURIComponent(from)}`)
  return (
    <>
      <SettingsCard title={t('skinEditor.page.title')} description={t('skinEditor.page.help')}>
        <ul className="divide-y divide-line text-sm" data-testid="skins-list">
          {all.map((skin) => (
            <li key={skin.key} className="flex items-center gap-2 py-2">
              <span className="flex-1 min-w-0">
                <span className="block truncate font-medium">{skin.name}</span>
                <span className="block truncate text-xs text-faint">{skin.origin === 'builtin' ? t('skinEditor.page.builtin') : skin.description || skin.key}</span>
              </span>
              {skin.origin !== 'builtin' && (
                <Link className="btn btn-flat" to={`/system/skins/${encodeURIComponent(skin.key)}/edit`}>
                  <Pencil size={14} /> {t('skinEditor.page.edit')}
                </Link>
              )}
            </li>
          ))}
        </ul>
        <button type="button" className="btn btn-accent mt-4" onClick={() => setChoosing(true)}>
          <Plus size={14} /> {t('skinEditor.page.new')}
        </button>
      </SettingsCard>
      <SettingsCard title={t('settings.skins.import')} description={t('settings.skins.importHelp')}>
        <SkinShelf onMessage={(text, level) => setToast({ text, level })} />
      </SettingsCard>
      <Dialog open={choosing} onClose={() => setChoosing(false)} title={t('skinEditor.page.startTitle')} size="lg">
        {starters.isLoading ? (
          <Spinner />
        ) : (
          <div className="flex flex-col gap-4">
            {(['empty', 'example', 'look'] as const).map((kind) => {
              const found = (starters.data?.starters ?? []).filter((starter) => starter.kind === kind)
              return found.length ? (
                <div key={kind}>
                  <p className="text-xs font-medium text-muted mb-1">{t(`skinEditor.page.kind.${kind}`)}</p>
                  <div className="flex flex-wrap gap-2">
                    {found.map((starter) => (
                      <button key={starter.key} type="button" className="btn" onClick={() => open(starter.key)}>
                        {kind === 'look' ? t(`settings.appearance.looks.${starter.key}`, { defaultValue: starter.name }) : kind === 'empty' ? t('skinEditor.page.empty') : starter.name}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null
            })}
            {own.length > 0 && (
              <div>
                <p className="text-xs font-medium text-muted mb-1">{t('skinEditor.page.kind.copy')}</p>
                <div className="flex flex-wrap gap-2">
                  {own.map((skin) => (
                    <button key={skin.key} type="button" className="btn" onClick={() => open(`skin:${skin.key}`)}>
                      {skin.name}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </Dialog>
      {toast && (
        <Toast level={toast.level} onClose={() => setToast(null)}>
          {toast.text}
        </Toast>
      )}
    </>
  )
}
