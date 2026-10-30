/**
 * System, Skin workshop: the skins of this installation, a new one from a
 * starting point (nothing, a copy, one of the looks, the console example), and
 * the way into the editor. A skin is shared in the Card shop from here, one
 * that came from there takes its update here, and each says whether everybody
 * or this account wears it; "Wear for everybody" makes it the installation's.
 * Look has the same choice beside the settings a skin may replace.
 */
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Pencil, Plus, RefreshCw, Share2 } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useNavigate } from 'react-router-dom'

import { ApiError, get, post } from '../../api/client'
import { Dialog, Spinner, Toast } from '../../components/ui'
import { SHOP_UPDATES_KEY, type ShopUpdates } from '../../lib/cardShop'
import { useSkinTexts } from '../../lib/skin/texts'
import { usePaint } from '../../lib/skin/wear'
import { useAuth } from '../../stores/auth'
import { SettingsCard } from '../settings/SettingsCard'
import { ShareDialog } from '../settings/share/ShareDialog'
import { SkinUpdateDialog } from '../settings/shop/SkinUpdateDialog'
import { SkinShelf, useSkins } from '../settings/SkinChooser'
import type { Appearance } from '../../lib/appearance'
import type { Starter } from './SkinEditorPage'

export function SkinsPage() {
  const ready = useSkinTexts()
  const { t } = useTranslation()
  const navigate = useNavigate()
  const skins = useSkins()
  const [choosing, setChoosing] = useState(false)
  const [toast, setToast] = useState<{ text: string; level: 'ok' | 'error' } | null>(null)
  const [sharing, setSharing] = useState<{ key: string; name: string } | null>(null)
  const [updating, setUpdating] = useState('')
  const updates = useQuery({ queryKey: SHOP_UPDATES_KEY, queryFn: () => get<ShopUpdates>('/workshop/updates') })
  const waiting = new Set((updates.data?.updates ?? []).filter((one) => one.type === 'skin').map((one) => one.slug))
  const starters = useQuery({ queryKey: ['skin-starters'], queryFn: () => get<{ starters: Starter[] }>('/skins/starters'), enabled: choosing })
  const look = useQuery({ queryKey: ['appearance'], queryFn: () => get<Appearance>('/settings/appearance') })
  const mine = useAuth((state) => state.user?.skin?.key ?? '')
  const client = useQueryClient()
  // The server names 1984 as the skin 1984 also where it is stored the old way, as the card style window.
  const forAll = look.data?.skin?.key ?? ''
  const wearForAll = async (key: string, name: string) => {
    try {
      const answer = await post<Appearance>(`/skins/${encodeURIComponent(key)}/wear`, {})
      client.setQueryData(['appearance'], answer)
      usePaint.getState().again()
      setToast({ text: t('skinEditor.page.nowForAll', { name }), level: 'ok' })
    } catch (failure) {
      setToast({ text: failure instanceof ApiError ? failure.message : t('errors.network'), level: 'error' })
    }
  }
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
                <span className="flex flex-wrap items-center gap-1.5">
                  <span className="truncate font-medium">{skin.name}</span>
                  {forAll === skin.key && (
                    <span className="chip !py-0 text-[11px] text-accent" data-testid="worn-by-all">
                      <Check size={11} /> {t('skinEditor.page.wornByAll')}
                    </span>
                  )}
                  {mine === skin.key && (
                    <span className="chip !py-0 text-[11px]" data-testid="worn-by-you">
                      {t('skinEditor.page.wornByYou')}
                    </span>
                  )}
                </span>
                <span className="block truncate text-xs text-faint">
                  {t(`settings.skins.origin.${skin.origin}`, { defaultValue: '' })}
                  {skin.origin !== 'builtin' && (skin.description || skin.key) ? ` · ${skin.description || skin.key}` : ''}
                </span>
              </span>
              {forAll !== skin.key && skin.wearable && (
                <button type="button" className="btn btn-flat" onClick={() => void wearForAll(skin.key, skin.name)}>
                  {t('skinEditor.page.wearForAll')}
                </button>
              )}
              {waiting.has(skin.key) && (
                <button type="button" className="btn btn-accent" onClick={() => setUpdating(skin.key)}>
                  <RefreshCw size={14} /> {t('skinEditor.page.update')}
                </button>
              )}
              {skin.origin !== 'builtin' && (
                <>
                  <Link className="btn btn-flat" to={`/system/skins/${encodeURIComponent(skin.key)}/edit`}>
                    <Pencil size={14} /> {t('skinEditor.page.edit')}
                  </Link>
                  <button type="button" className="btn btn-flat" onClick={() => setSharing({ key: skin.key, name: skin.name })} aria-label={t('cards.share.buttonNamed', { name: skin.name })}>
                    <Share2 size={14} /> {t('skinEditor.page.share')}
                  </button>
                </>
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
      {sharing && <ShareDialog kind="skin" slug={sharing.key} name={sharing.name} open onClose={() => setSharing(null)} />}
      <SkinUpdateDialog skin={updating} open={updating !== ''} onClose={() => setUpdating('')} />
      {toast && (
        <Toast level={toast.level} onClose={() => setToast(null)}>
          {toast.text}
        </Toast>
      )}
    </>
  )
}
