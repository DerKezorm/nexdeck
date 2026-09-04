/**
 * The stage behind every board: a soft aurora by default, an uploaded image
 * with blur and dim when the board has one. Fixed, behind everything, and
 * never a network request unless the owner uploaded something.
 */
export interface Background {
  kind: string
  value?: string
  blur?: number
  dim?: number
}

export const BUNDLED: Record<string, string> = {
  aurora:
    'radial-gradient(1200px 600px at 8% -10%, var(--nd-aurora-1), transparent 60%), radial-gradient(900px 520px at 92% 8%, var(--nd-aurora-2), transparent 60%), radial-gradient(900px 600px at 50% 115%, var(--nd-aurora-3), transparent 60%)',
  dusk: 'radial-gradient(1000px 600px at 20% 0%, rgba(244,114,182,0.16), transparent 60%), radial-gradient(900px 600px at 90% 100%, rgba(129,140,248,0.18), transparent 60%)',
  ember: 'radial-gradient(1000px 600px at 90% -10%, rgba(251,146,60,0.16), transparent 60%), radial-gradient(900px 600px at 0% 100%, rgba(244,63,94,0.12), transparent 60%)',
  ocean: 'radial-gradient(1100px 600px at 50% -20%, rgba(14,165,233,0.2), transparent 60%), radial-gradient(900px 600px at 100% 100%, rgba(20,184,166,0.14), transparent 60%)',
  forest: 'radial-gradient(1100px 600px at 0% 0%, rgba(34,197,94,0.14), transparent 60%), radial-gradient(900px 600px at 100% 90%, rgba(132,204,22,0.1), transparent 60%)',
  violet: 'radial-gradient(1100px 600px at 80% -10%, rgba(168,85,247,0.2), transparent 60%), radial-gradient(900px 600px at 10% 100%, rgba(99,102,241,0.16), transparent 60%)',
  mono: 'radial-gradient(1100px 600px at 50% -20%, rgba(148,163,184,0.12), transparent 60%)',
  none: 'none',
}

export function BackgroundLayer({ background }: { background?: Background }) {
  const kind = background?.kind ?? 'bundled'
  const blur = background?.blur ?? 18
  const dim = background?.dim ?? 45
  const isImage = kind === 'upload' || kind === 'url'
  const gradient = kind === 'bundled' || kind === 'gradient' ? BUNDLED[background?.value ?? 'aurora'] ?? BUNDLED.aurora : BUNDLED.aurora
  return (
    <div className="fixed inset-0 -z-10 overflow-hidden" aria-hidden="true">
      <div className="absolute inset-0" style={{ background: 'var(--nd-bg)' }} />
      {isImage && background?.value ? (
        <div
          className="absolute -inset-6 bg-cover bg-center"
          style={{
            backgroundImage: `url(${background.value})`,
            filter: `blur(${blur}px)`,
            transform: 'scale(1.05)',
          }}
        />
      ) : (
        <div className="absolute inset-0" style={{ background: gradient }} />
      )}
      {isImage && <div className="absolute inset-0" style={{ background: `rgba(6,9,14,${dim / 100})` }} />}
      <div
        className="absolute inset-0 opacity-[0.35]"
        style={{
          backgroundImage:
            'linear-gradient(color-mix(in srgb, var(--nd-text) 4%, transparent) 1px, transparent 1px), linear-gradient(90deg, color-mix(in srgb, var(--nd-text) 4%, transparent) 1px, transparent 1px)',
          backgroundSize: '48px 48px',
          maskImage: 'radial-gradient(ellipse at 50% 0%, black 20%, transparent 75%)',
        }}
      />
    </div>
  )
}
