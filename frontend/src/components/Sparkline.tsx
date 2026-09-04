import { useId } from 'react'

interface Props {
  values: number[]
  height?: number
  color?: string
  fill?: boolean
  className?: string
  min?: number
  max?: number
}

/** A tiny line with a soft area beneath it and a dot on the latest value. */
export function Sparkline({ values, height = 36, color = 'var(--nd-accent)', fill = true, className = '', min, max }: Props) {
  const id = useId()
  if (values.length < 2) {
    return <div className={className} style={{ height }} aria-hidden="true" />
  }
  const width = 100
  const low = min ?? Math.min(...values)
  const high = max ?? Math.max(...values)
  const span = high - low || 1
  const step = width / (values.length - 1)
  const points = values.map((v, i) => [i * step, height - 3 - ((v - low) / span) * (height - 6)] as const)
  const path = points.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(2)} ${y.toFixed(2)}`).join(' ')
  const area = `${path} L${width} ${height} L0 ${height} Z`
  const [lx, ly] = points[points.length - 1]
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className={className}
      style={{ width: '100%', height }}
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={color} stopOpacity="0.35" />
          <stop offset="1" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      {fill && <path d={area} fill={`url(#${id})`} />}
      <path d={path} fill="none" stroke={color} strokeWidth="1.6" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
      <circle cx={lx} cy={ly} r="2.2" fill={color} vectorEffect="non-scaling-stroke" />
    </svg>
  )
}
