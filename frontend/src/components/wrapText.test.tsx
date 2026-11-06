/**
 * "Wrap long text" on a JSON API card (#63): a long text breaks onto further
 * lines instead of ending in "…". A card that does not ask for it stays on
 * one line, as every card always did.
 */
import { render } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

import { DEMO_VIEWS } from '../demo/board'
import type { WidgetData, WidgetView } from '../lib/types'
import { renderWidget } from './renderers'

const LONG = 'The nightly backup of the media library finished with three warnings about files that changed while they were read'

function value(meta: Record<string, unknown>): HTMLElement {
  const view = { ...DEMO_VIEWS[0], id: 63, renderer: 'value' } as WidgetView
  const data = { status: 'ok', primary: { label: 'Backup', value: LONG }, meta } as unknown as WidgetData
  const { container } = render(<>{renderWidget({ widget: view, data })}</>)
  return container.querySelector('.value-number') as HTMLElement
}

function row(meta: Record<string, unknown>): { title: HTMLElement; subtitle: HTMLElement; value: HTMLElement } {
  const view = { ...DEMO_VIEWS[0], id: 64, renderer: 'list', kind: 'jsonapi.list' } as WidgetView
  const data = { status: 'ok', items: [{ title: LONG, subtitle: `${LONG}, again`, value: 'a value long enough to need a second line' }], meta } as unknown as WidgetData
  const { container } = render(<>{renderWidget({ widget: view, data })}</>)
  const spans = [...container.querySelectorAll('li span, li div')] as HTMLElement[]
  // The innermost element holding the text: its wrapper holds the same text.
  const find = (text: string) => spans.filter((element) => element.textContent === text).pop() as HTMLElement
  return { title: find(LONG), subtitle: find(`${LONG}, again`), value: find('a value long enough to need a second line') }
}

describe('wrapping long text', () => {
  it('the value card keeps to one line unless asked', () => {
    const number = value({})
    expect(number.className).not.toContain('value-wrap')
    expect(number.className).toContain('leading-none')
  })

  it('the value card breaks a long text when the card asks for it', () => {
    const number = value({ wrap: true })
    expect(number.className).toContain('value-wrap')
    expect(number.className).not.toContain('leading-none')
    expect(number.parentElement?.className).toContain('justify-center-safe')
  })

  it('the rows of a list are cut short unless asked', () => {
    const { title, subtitle, value: shown } = row({})
    expect(title.className).toContain('truncate')
    expect(subtitle.className).toContain('truncate')
    expect(shown.className).toContain('whitespace-nowrap')
  })

  it('the rows of a list break title, subtitle and value when the card asks for it', () => {
    const { title, subtitle, value: shown } = row({ wrap: true })
    for (const element of [title, subtitle]) {
      expect(element.className).not.toContain('truncate')
      expect(element.className).toContain('whitespace-normal')
    }
    expect(shown.className).not.toContain('whitespace-nowrap')
    // A row taller than the card keeps its dot and its value at the top, where they can be seen.
    const line = title.closest('li') as HTMLElement
    expect(line.className).toContain('items-start')
    expect(line.className).not.toContain('items-center')
  })

  it('the stylesheet lets a wrapped value go on over further lines', () => {
    const css = readFileSync(join(process.cwd(), 'src/styles/app.css'), 'utf8')
    const rule = css.slice(css.indexOf('.value-number.value-wrap {'))
    const body = rule.slice(0, rule.indexOf('}'))
    expect(body).toContain('white-space: normal')
    expect(body).toContain('overflow-wrap: anywhere')
  })
})
