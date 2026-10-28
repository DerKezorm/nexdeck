import { useTranslation } from 'react-i18next'

import { pickText } from '../../../lib/cardText'
import type { ShopCatalog, ShopState } from '../../../lib/cardShop'
import { visible } from '../../../lib/cardShop'

/** The entries of the catalog, by name. */
export function ShopList({ catalog }: { catalog: ShopCatalog; state: ShopState }) {
  const { i18n } = useTranslation()
  return (
    <ul data-testid="shop-list">
      {catalog.entries.filter(visible).map((entry) => (
        <li key={entry.id}>{pickText(entry.name, i18n.language)}</li>
      ))}
    </ul>
  )
}
