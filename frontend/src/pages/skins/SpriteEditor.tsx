/**
 * A sprite drawn by hand: rows of characters, one for each colour of its
 * palette and `.` for see-through, as the skin file keeps it. Paint with the
 * colour chosen, mirror, shift, change the size, or bring in a small picture,
 * which is cut to at most 32 by 32 pixels and 16 colours.
 */
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUp, FlipHorizontal, ImageUp, Plus } from 'lucide-react'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'

export interface SpriteData {
  palette: Record<string, string>
  rows: string[]
  tint?: boolean
}

const CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
const CLEAR = '.'

export function resize(rows: string[], width: number, height: number): string[] {
  return Array.from({ length: height }, (_, y) => (rows[y] ?? '').padEnd(width, CLEAR).slice(0, width))
}

export function mirror(rows: string[]): string[] {
  return rows.map((row) => [...row].reverse().join(''))
}

export function shift(rows: string[], dx: number, dy: number): string[] {
  const height = rows.length
  const width = rows[0]?.length ?? 0
  return Array.from({ length: height }, (_, y) =>
    Array.from({ length: width }, (_, x) => rows[(y - dy + height) % height][(x - dx + width) % width]).join(''),
  )
}

export function paint(rows: string[], x: number, y: number, char: string): string[] {
  return rows.map((row, index) => (index === y ? row.slice(0, x) + char + row.slice(x + 1) : row))
}

/** A picture as a sprite: at most `side` pixels on its long side and `colours` colours, see-through where it is. */
export function fromPixels(data: Uint8ClampedArray, width: number, height: number, colours: number): SpriteData {
  let step = 0
  for (;;) {
    const seen = new Map<string, string>()
    const rows: string[] = []
    let fits = true
    for (let y = 0; y < height && fits; y++) {
      let row = ''
      for (let x = 0; x < width; x++) {
        const at = (y * width + x) * 4
        if (data[at + 3] < 128) {
          row += CLEAR
          continue
        }
        // Colours are rounded a little more each round until no more than the palette holds are left.
        const round = (value: number) => Math.min(255, Math.round(value / (1 << step)) * (1 << step))
        const hex = '#' + [data[at], data[at + 1], data[at + 2]].map((value) => round(value).toString(16).padStart(2, '0')).join('')
        if (!seen.has(hex)) {
          if (seen.size >= colours) {
            fits = false
            break
          }
          seen.set(hex, CHARS[seen.size])
        }
        row += seen.get(hex)
      }
      rows.push(row)
    }
    if (fits) return { palette: Object.fromEntries([...seen].map(([hex, char]) => [char, hex])), rows }
    step += 1
  }
}

export function SpriteEditor({ sprite, onChange, limits }: { sprite: SpriteData; onChange: (next: SpriteData) => void; limits: { side: number; colours: number } }) {
  const { t } = useTranslation()
  const chars = Object.keys(sprite.palette)
  const [brush, setBrush] = useState(chars[0] ?? CLEAR)
  const [drawing, setDrawing] = useState(false)
  const width = sprite.rows[0]?.length ?? 0
  const height = sprite.rows.length
  const cell = Math.max(8, Math.floor(240 / Math.max(width, height)))
  const set = (rows: string[]) => onChange({ ...sprite, rows })
  const bringIn = (file: File) => {
    const image = new Image()
    image.onload = () => {
      const scale = Math.min(1, limits.side / Math.max(image.width, image.height))
      const canvas = document.createElement('canvas')
      canvas.width = Math.max(1, Math.round(image.width * scale))
      canvas.height = Math.max(1, Math.round(image.height * scale))
      const context = canvas.getContext('2d')
      if (!context) return
      context.imageSmoothingEnabled = false
      context.drawImage(image, 0, 0, canvas.width, canvas.height)
      onChange(fromPixels(context.getImageData(0, 0, canvas.width, canvas.height).data, canvas.width, canvas.height, limits.colours))
      URL.revokeObjectURL(image.src)
    }
    image.src = URL.createObjectURL(file)
  }
  return (
    <div className="flex flex-col gap-2" data-testid="sprite-editor">
      <div
        className="grid self-start border border-line select-none touch-none"
        style={{ gridTemplateColumns: `repeat(${width}, ${cell}px)`, background: 'repeating-conic-gradient(#8884 0 25%, transparent 0 50%) 0 0 / 8px 8px' }}
        onPointerUp={() => setDrawing(false)}
        onPointerLeave={() => setDrawing(false)}
      >
        {sprite.rows.flatMap((row, y) =>
          [...row].map((char, x) => (
            <button
              key={`${x}-${y}`}
              type="button"
              aria-label={`${x + 1}, ${y + 1}`}
              className="block p-0 border-0"
              style={{ width: cell, height: cell, background: char === CLEAR ? 'transparent' : sprite.palette[char], outline: '1px solid #8882' }}
              onPointerDown={(event) => {
                event.preventDefault()
                setDrawing(true)
                set(paint(sprite.rows, x, y, brush))
              }}
              onPointerEnter={() => drawing && set(paint(sprite.rows, x, y, brush))}
            />
          )),
        )}
      </div>
      <div className="flex flex-wrap items-center gap-1" role="radiogroup" aria-label={t('skinEditor.palette')}>
        <button type="button" role="radio" aria-checked={brush === CLEAR} className="btn btn-flat btn-icon text-xs" onClick={() => setBrush(CLEAR)} title={t('skinEditor.clear')}>
          ⌫
        </button>
        {chars.map((char) => (
          <span key={char} className="flex items-center">
            <button type="button" role="radio" aria-checked={brush === char} aria-label={char} className={`w-6 h-6 rounded border ${brush === char ? 'border-accent ring-2 ring-[var(--nd-accent)]' : 'border-line'}`} style={{ background: sprite.palette[char] }} onClick={() => setBrush(char)} />
            {brush === char && <input type="color" className="w-6 h-6 p-0 border-0" value={sprite.palette[char]} onChange={(event) => onChange({ ...sprite, palette: { ...sprite.palette, [char]: event.target.value } })} aria-label={t('skinEditor.colourOf', { char })} />}
          </span>
        ))}
        {chars.length < limits.colours && (
          <button
            type="button"
            className="btn btn-flat btn-icon"
            aria-label={t('skinEditor.addColour')}
            onClick={() => {
              const char = [...CHARS].find((letter) => !(letter in sprite.palette)) ?? 'Z'
              onChange({ ...sprite, palette: { ...sprite.palette, [char]: '#ffffff' } })
              setBrush(char)
            }}
          >
            <Plus size={14} />
          </button>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-1 text-xs">
        <button type="button" className="btn btn-flat btn-icon" onClick={() => set(mirror(sprite.rows))} aria-label={t('skinEditor.mirror')} title={t('skinEditor.mirror')}>
          <FlipHorizontal size={14} />
        </button>
        <button type="button" className="btn btn-flat btn-icon" onClick={() => set(shift(sprite.rows, -1, 0))} aria-label={t('skinEditor.shiftLeft')}>
          <ArrowLeft size={14} />
        </button>
        <button type="button" className="btn btn-flat btn-icon" onClick={() => set(shift(sprite.rows, 1, 0))} aria-label={t('skinEditor.shiftRight')}>
          <ArrowRight size={14} />
        </button>
        <button type="button" className="btn btn-flat btn-icon" onClick={() => set(shift(sprite.rows, 0, -1))} aria-label={t('skinEditor.shiftUp')}>
          <ArrowUp size={14} />
        </button>
        <button type="button" className="btn btn-flat btn-icon" onClick={() => set(shift(sprite.rows, 0, 1))} aria-label={t('skinEditor.shiftDown')}>
          <ArrowDown size={14} />
        </button>
        <label className="flex items-center gap-1">
          {t('skinEditor.width.label')}
          <input type="number" className="input h-7 w-14 text-xs" min={1} max={limits.side} value={width} onChange={(event) => set(resize(sprite.rows, Math.min(limits.side, Math.max(1, Number(event.target.value))), height))} />
        </label>
        <label className="flex items-center gap-1">
          {t('skinEditor.height')}
          <input type="number" className="input h-7 w-14 text-xs" min={1} max={limits.side} value={height} onChange={(event) => set(resize(sprite.rows, width, Math.min(limits.side, Math.max(1, Number(event.target.value)))))} />
        </label>
        <label className="btn btn-flat cursor-pointer" title={t('skinEditor.pictureHelp')}>
          <ImageUp size={14} /> {t('skinEditor.picture')}
          <input type="file" accept="image/png,image/gif,image/webp" className="sr-only" onChange={(event) => event.target.files?.[0] && bringIn(event.target.files[0])} />
        </label>
      </div>
      <label className="flex items-center gap-2 text-xs">
        <input type="checkbox" checked={sprite.tint === true} onChange={(event) => onChange({ ...sprite, tint: event.target.checked || undefined })} />
        {t('skinEditor.tint')}
      </label>
    </div>
  )
}
