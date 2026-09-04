import { createElement, useState } from 'react'
import { Box, type LucideProps } from 'lucide-react'
import * as icons from 'lucide-react'

import { iconUrl } from '../lib/format'

interface Props {
  icon?: string | null
  size?: number
  className?: string
}

/**
 * A service logo (dashboard-icons name, URL or upload) or, with the
 * ``lucide:`` prefix, a symbol from the UI icon set.
 */
export function ServiceIcon({ icon, size = 20, className = '' }: Props) {
  const [failed, setFailed] = useState(false)
  if (icon && icon.startsWith('lucide:')) {
    return createElement(lucideIcon(icon.slice(7)), { size, className, 'aria-hidden': 'true' })
  }
  const url = iconUrl(icon)
  if (!url || failed) {
    return <Box size={size} className={`${className} text-muted`} aria-hidden="true" />
  }
  return (
    <img
      src={url}
      width={size}
      height={size}
      alt=""
      className={`${className} object-contain`}
      style={{ width: size, height: size }}
      loading="lazy"
      onError={() => setFailed(true)}
    />
  )
}

export function lucideIcon(name: string): React.ComponentType<LucideProps> {
  const pascal = name
    .split(/[-_ ]/)
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join('')
  const found = (icons as unknown as Record<string, React.ComponentType<LucideProps>>)[pascal]
  return found ?? Box
}
