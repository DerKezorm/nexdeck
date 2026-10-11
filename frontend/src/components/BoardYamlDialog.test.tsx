/**
 * The board edited as text (issue #36): it opens on the text with the numbers,
 * sends back what was changed, and stays open with the reason when the server says no.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { BoardYamlDialog } from './BoardYamlDialog'

const TEXT = 'nexdeck: 1\nboard:\n  name: Home\npages:\n- id: 4\n  name: Overview\n'

function server(answer: { status: number; body: unknown }) {
  const calls: { url: string; method: string; body: unknown }[] = []
  const fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    const method = (init?.method ?? 'GET').toUpperCase()
    calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null })
    if (method === 'GET') return new Response(TEXT, { status: 200, headers: { 'content-type': 'application/yaml' } })
    return new Response(JSON.stringify(answer.body), { status: answer.status, headers: { 'content-type': 'application/json' } })
  }
  vi.stubGlobal('fetch', fetch)
  return calls
}

describe('BoardYamlDialog', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('loads the text with the numbers and saves what was changed', async () => {
    const calls = server({ status: 200, body: { slug: 'home' } })
    const saved = vi.fn()
    const closed = vi.fn()
    render(<BoardYamlDialog open slug="home" onClose={closed} onSaved={saved} />)
    const area = screen.getByRole('textbox')
    await waitFor(() => expect((area as HTMLTextAreaElement).value).toBe(TEXT))
    expect(calls[0].url).toContain('/boards/home/export?ids=true')

    fireEvent.change(area, { target: { value: TEXT.replace('Home', 'House') } })
    await userEvent.click(screen.getByRole('button', { name: /^(Save|Speichern)$/ }))
    await waitFor(() => expect(saved).toHaveBeenCalledTimes(1))
    expect(closed).toHaveBeenCalledTimes(1)
    const sent = calls.find((call) => call.method === 'PUT')
    expect(sent?.url).toContain('/boards/home/yaml')
    expect(sent?.body).toEqual({ yaml_text: TEXT.replace('Home', 'House') })
  })

  it('stays open and says why when the text will not do', async () => {
    server({ status: 400, body: { detail: { code: 'bad_import', message: "Unknown widget kind 'nothing.like-this'." } } })
    const saved = vi.fn()
    const closed = vi.fn()
    render(<BoardYamlDialog open slug="home" onClose={closed} onSaved={saved} />)
    await waitFor(() => expect((screen.getByRole('textbox') as HTMLTextAreaElement).value).toBe(TEXT))
    await userEvent.click(screen.getByRole('button', { name: /^(Save|Speichern)$/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('nothing.like-this')
    expect(saved).not.toHaveBeenCalled()
    expect(closed).not.toHaveBeenCalled()
  })
})
