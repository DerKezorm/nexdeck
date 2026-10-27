/** The address bar help says what Safari cannot do as a limit of Safari, beside the short address of this installation. */
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { AddressBarHelp } from './AddressBarHelp'

describe('AddressBarHelp', () => {
  it('names the short address of this installation and what Safari cannot do', () => {
    render(<AddressBarHelp />)
    expect(screen.getByText(new RegExp(`${window.location.origin}/go/plex`))).toBeInTheDocument()
    expect(screen.getByText(/Safari cannot add search engines/)).toBeInTheDocument()
    expect(screen.getByText(/Chrome, Edge and Firefox/)).toBeInTheDocument()
  })
})
