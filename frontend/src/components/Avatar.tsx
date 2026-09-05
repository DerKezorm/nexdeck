import { serverUrl } from '../api/client'

interface Props {
  /** Address the server handed out, or nothing while the account has no picture. */
  url?: string | null
  name: string
  size?: number
  className?: string
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return '?'
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

/**
 * The profile picture, or the initials while there is none.
 *
 * The picture never scales the layout: width and height are set, and the image
 * is cropped to the circle instead of stretching it.
 */
export function Avatar({ url, name, size = 28, className = '' }: Props) {
  const box = { width: size, height: size }
  if (url) {
    return (
      <img
        src={url.startsWith('/') ? serverUrl(url) : url}
        alt=""
        width={size}
        height={size}
        style={box}
        className={`shrink-0 rounded-full border border-line object-cover ${className}`}
      />
    )
  }
  return (
    <span
      aria-hidden="true"
      style={{ ...box, fontSize: Math.max(10, Math.round(size * 0.38)) }}
      className={`shrink-0 rounded-full bg-gradient-to-br from-accent to-indigo-500 text-[#041016] font-semibold inline-flex items-center justify-center ${className}`}
    >
      {initials(name)}
    </span>
  )
}
