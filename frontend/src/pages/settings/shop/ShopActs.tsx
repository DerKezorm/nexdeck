import { useTranslation } from 'react-i18next'

import type { ShopEntry } from '../../../lib/cardShop'
import { pickText } from '../../../lib/cardText'
import { ClassChip } from './ShopTile'

/** The sentence for a warning the server sends with an entry (`files_warning`): its own words for the codes the interface knows. */
export function useWarningText() {
  const { t } = useTranslation()
  return (warning: { code: string; message: string }) => t(`cards.shop.errors.${warning.code}`, { defaultValue: warning.message })
}

/**
 * What an entry reads and which buttons it has, read from its checked definition (KARTEN-14 AC-5). The catalog's own words
 * are never shown here: when they differ from the file the page says so, and when the file could not be read it shows
 * nothing of it.
 */
export function ShopActs({ entry }: { entry: ShopEntry | undefined }) {
  const { t, i18n } = useTranslation()
  const lang = i18n.language
  if (!entry) {
    return (
      <p className="text-sm text-muted" data-testid="shop-acts-loading">
        {t('cards.shop.loading')}
      </p>
    )
  }
  if (!entry.verified) {
    return (
      <p className="text-sm text-warn" role="note" data-testid="shop-unchecked">
        {t('cards.shop.unchecked')}
      </p>
    )
  }
  if (entry.type === 'skin') {
    return (
      <p className="text-sm" data-testid="shop-skin-acts">
        {t('cards.shop.skinActs')}
      </p>
    )
  }
  const labelOf = (kind: string) => entry.requires.find((need) => need.kind === kind)?.label ?? kind
  return (
    <>
      {entry.claims_differ.length > 0 && (
        <p className="text-sm text-warn rounded-xl border border-warn/50 p-3" role="note" data-testid="shop-claims-differ">
          {t('cards.shop.claimsDiffer', { parts: entry.claims_differ.map((part) => t(`cards.shop.claimPart.${part}`, { defaultValue: part })).join(', ') })}
        </p>
      )}
      <section className="grid gap-1" data-testid="shop-reads">
        <h4 className="text-[11px] uppercase tracking-wide text-faint">{t('cards.shop.sections.reads')}</h4>
        {entry.reads.length === 0 ? (
          <p className="text-sm text-muted">{t('cards.shop.noReads')}</p>
        ) : (
          <ul className="grid gap-0.5">
            {entry.reads.map((read, index) => (
              <li key={index} className="text-sm break-words">
                {labelOf(read.kind)} <span className="font-mono text-[12px] text-muted">{read.path}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="grid gap-1" data-testid="shop-buttons">
        <h4 className="text-[11px] uppercase tracking-wide text-faint">{t('cards.shop.sections.buttons')}</h4>
        {entry.buttons.length === 0 ? (
          <p className="text-sm text-muted">{t('cards.exchange.noButtons')}</p>
        ) : (
          <ul className="grid gap-0.5">
            {entry.buttons.map((button, index) => (
              <li key={index} className="text-sm break-words">
                {pickText(button.label, lang)} <span className="font-mono text-[12px] text-muted">{button.method} {button.path}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  )
}

/** The class of the checked definition as a small chip; nothing while the definition is still being fetched. */
export function CheckedClass({ entry }: { entry: ShopEntry | undefined }) {
  return entry ? <ClassChip entry={entry.verified ? entry : { ...entry, class: 'unknown' }} /> : null
}
