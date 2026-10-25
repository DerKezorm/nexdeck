/**
 * "Why?" (roadmap M6): the way from a red or yellow card, a row of the
 * attention card or a line of the chronicle to the diagnosis page of its
 * service. For administrators only; everybody else sees nothing here.
 *
 * ⚠️ A card is also drawn where there is no router (a test, a preview), so
 * outside one the link is a plain address.
 */
import type { MouseEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useInRouterContext } from 'react-router-dom'

import { diagnosisPath } from '../lib/diagnosis'
import { useAuth } from '../stores/auth'

export function WhyLink({ subject, name, at, className = '' }: { subject: string | null | undefined; name: string; at?: number; className?: string }) {
  const { t } = useTranslation()
  const admin = useAuth((state) => state.user?.role === 'admin')
  const routed = useInRouterContext()
  if (!admin || !subject) return null
  const to = diagnosisPath(subject, at)
  // The card or the row around it is a link or a button of its own.
  const keep = (event: MouseEvent) => event.stopPropagation()
  const props = { className: `nd-why ${className}`, title: t('diagnosis.whyOf', { name }), 'aria-label': t('diagnosis.whyOf', { name }), onClick: keep, 'data-testid': 'why-link' }
  return routed ? <Link to={to} {...props}>{t('diagnosis.why')}</Link> : <a href={to} {...props}>{t('diagnosis.why')}</a>
}
