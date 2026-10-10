/**
 * "Works only once you set up a second factor." for the API tokens of an account that must set up a second factor
 * but has none yet, and is spared the duty in this session because it came in through a provider that checks the
 * second factor itself (sign-in blueprint 01). A token has no session: it asks the account and stays shut until the
 * account sets one up. Making one stays possible; this only says so, with the way to the setup.
 */
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'

import { useAuth } from '../stores/auth'

export function KeyFactorHint() {
  const { t } = useTranslation()
  const user = useAuth((state) => state.user)
  if (!user?.keys_need_second_factor) return null
  return (
    <p role="note" data-testid="key-needs-factor" className="mb-3 rounded-xl border border-line px-3 py-2 text-sm text-warn">
      {t('keyFactor.text')}{' '}
      <Link to="/settings" className="underline">
        {t('keyFactor.link')}
      </Link>
    </p>
  )
}
