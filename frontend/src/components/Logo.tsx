/**
 * The nexdeck mark: a deck of three stacked cards, the front one lit in the
 * accent, and the live dot glowing at the top right. Cards are what a board
 * is made of, the stack is the deck, the dot is what makes it live.
 */
export function LogoMark({ size = 28, className = '' }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <linearGradient id="nd-front" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#a5f3fc" />
          <stop offset="0.55" stopColor="#22d3ee" />
          <stop offset="1" stopColor="#0891b2" />
        </linearGradient>
        <linearGradient id="nd-mid" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#22d3ee" stopOpacity="0.55" />
          <stop offset="1" stopColor="#0e7490" stopOpacity="0.55" />
        </linearGradient>
      </defs>
      <rect x="1.5" y="1.5" width="29" height="29" rx="8.5" fill="#0f1420" stroke="rgba(255,255,255,0.12)" />
      {/* back card */}
      <rect x="11" y="7.5" width="14" height="9" rx="2.2" fill="#22d3ee" fillOpacity="0.22" />
      {/* middle card */}
      <rect x="8.5" y="11" width="14" height="9" rx="2.2" fill="url(#nd-mid)" />
      {/* front card with a tiny value line */}
      <rect x="6" y="14.5" width="14" height="9" rx="2.2" fill="url(#nd-front)" />
      <path d="M8.5 21.2l2.4-2.3 2 1.4 2.3-3.1 2.3 1.6" fill="none" stroke="#062a33" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
      {/* live dot */}
      <circle cx="24.6" cy="8.2" r="2.4" fill="#22d3ee" />
      <circle cx="24.6" cy="8.2" r="4.4" fill="none" stroke="#22d3ee" strokeOpacity="0.35" strokeWidth="1" />
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
