/**
 * The row picker of a list card.
 *
 * ⚠️ Two ways it went wrong, both of them a one-way door: the buttons were
 * built from the rows the card was showing, so switching a row off took its
 * own button away, and the sheet kept the answer that belonged to the card
 * opened before it, so a disks card offered container names.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { FieldInput } from './FieldInput'
import type { FieldSpec } from '../api/types'

const SPEC: FieldSpec = {
  name: 'only_items',
  label: 'Entries',
  type: 'items',
  required: false,
  secret: false,
  default: null,
  help: '',
  placeholder: '',
  options: [],
}

const ALL = ['Drive 1', 'Drive 2', 'Drive 3']

function show(value: unknown, visible: string[], allTitles?: string[]) {
  const onChange = vi.fn()
  render(
    <FieldInput
      spec={SPEC}
      value={value}
      onChange={onChange}
      items={visible.map((title) => ({ title }))}
      allTitles={allTitles}
    />,
  )
  return onChange
}

describe('ItemPicker', () => {
  it('offers one button per row, all of them on while nothing is picked', () => {
    /** ⚠️ Nothing picked means everything is shown, so every button has to
        look it. Reading the empty list as "none on" leaves a card that shows
        all its rows next to a picker where none is ticked. */
    show([], ALL, ALL)
    for (const title of ALL) {
      expect(screen.getByRole('button', { name: title })).toHaveAttribute('aria-pressed', 'true')
    }
  })

  it('keeps the button of a row that is switched off', () => {
    /** ⚠️ The card shows one row; the picker still offers all three. */
    show(['Drive 2'], ['Drive 2'], ALL)
    expect(screen.getByRole('button', { name: 'Drive 1' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Drive 2' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Drive 1' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('still shows a chosen row the card no longer returns', () => {
    /** A disk that was pulled: the tick stays visible so it can be cleared. */
    show(['Drive 9'], ['Drive 1'], ['Drive 1'])
    expect(screen.getByRole('button', { name: 'Drive 9' })).toBeInTheDocument()
  })

  it('starts from everything, so the first click means "not this one"', async () => {
    const onChange = show([], ALL, ALL)
    await userEvent.click(screen.getByRole('button', { name: 'Drive 2' }))
    expect(onChange).toHaveBeenCalledWith(['Drive 1', 'Drive 3'])
  })

  it('goes back to meaning all of them when everything is ticked again', async () => {
    const onChange = show(['Drive 1', 'Drive 3'], ['Drive 1', 'Drive 3'], ALL)
    await userEvent.click(screen.getByRole('button', { name: 'Drive 2' }))
    expect(onChange).toHaveBeenCalledWith([])
  })

  it('says nothing is picked rather than showing an empty box', () => {
    show([], [], [])
    expect(screen.getByText(/no entries to pick from/i)).toBeInTheDocument()
  })

  it('falls back to the visible rows when the full list is missing', () => {
    show([], ['Drive 1'], undefined)
    expect(screen.getByRole('button', { name: 'Drive 1' })).toBeInTheDocument()
  })
})
