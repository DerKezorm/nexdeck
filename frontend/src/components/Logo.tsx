import { useId } from 'react'

/**
 * The nexdeck mark: a deck of three stacked cards, the front one carrying a
 * small chart. Cards are what a board is made of, the stack is the deck.
 *
 * The source of every version is nexapps/icons-vergleich/neu.py; the same
 * shape is in public/icon.svg (favicon) and tools/app-icons.mjs (home
 * screen). The colours come from app.css (--nd-logo-…) and follow the theme:
 * a dark tile in dark mode, a white one in light mode.
 */
export function LogoMark({ size = 28, className = '' }: { size?: number; className?: string }) {
  // ⚠️ One id per mark: a gradient whose first copy sits in a hidden part of the page (the sidebar on a phone) draws
  // nothing for every other copy that points at it.
  const id = `nd-mark-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`
  const line = `url(#${id})`
  const ground = { fill: 'var(--nd-logo-ground)' }
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" className={className} aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id={id} gradientUnits="userSpaceOnUse" x1="10" y1="10" x2="54" y2="54">
          <stop offset="0" style={{ stopColor: 'var(--nd-logo-gradient-1)' }} />
          <stop offset=".5" style={{ stopColor: 'var(--nd-logo-gradient-2)' }} />
          <stop offset="1" style={{ stopColor: 'var(--nd-logo-gradient-3)' }} />
        </linearGradient>
      </defs>
      <rect x="2" y="2" width="60" height="60" rx="16" style={ground} />
      <rect
        x="2.75"
        y="2.75"
        width="58.5"
        height="58.5"
        rx="15.3"
        fill="none"
        strokeWidth="1.5"
        style={{ stroke: 'var(--nd-logo-rim)', strokeOpacity: 'var(--nd-logo-rim-opacity)' }}
      />
      {/* back, middle and front card */}
      <rect x="24" y="12.5" width="28" height="19" rx="4.5" stroke={line} strokeWidth="3.6" strokeOpacity=".45" style={ground} />
      <rect x="18" y="20.5" width="28" height="19" rx="4.5" stroke={line} strokeWidth="3.8" strokeOpacity=".75" style={ground} />
      <rect x="12" y="29" width="28" height="20" rx="4.5" stroke={line} strokeWidth="4.2" style={ground} />
      {/* the chart on the front card */}
      <path
        d="M17.5 42.5l4.6-4.6 4 2.8 4.6-6 4 2.8"
        fill="none"
        strokeWidth="3.4"
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{ stroke: 'var(--nd-logo-chart)' }}
      />
    </svg>
  )
}

export function Logo({ size = 28 }: { size?: number }) {
  return (
    <span className="inline-flex items-center gap-2 select-none">
      <LogoMark size={size} />
      <span className="font-semibold tracking-tight" style={{ fontSize: size * 0.62 }}>
        nex<span className="text-accent">deck</span>
      </span>
    </span>
  )
}
