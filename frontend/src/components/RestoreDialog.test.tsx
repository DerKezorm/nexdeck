/**
 * The restore dialog, and the sentence it has to get right.
 *
 * ⚠️ Whether the credentials survive a restore depends on two things, not
 * one: whether the archive brings a key, and whether this installation would
 * ignore it because NEXDECK_SECRET_KEY is set. Asking only the first makes
 * the preview look reassuring in the one combination that ruins the
 * installation, which is exactly what happened in nexview.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'

import { RestoreDialog } from './RestoreDialog'

const VERDICT = {
  version: '0.1.0',
  created_at: '2026-09-06T10:00:00Z',
  kind: 'manual',
  note: 'before the migration',
  contains: ['nexdeck.db', 'secret.key'],
  restorable: true,
  reason: 'ok',
  key_inside: true,
  key_from_env: false,
}

function answerWith(verdict: Record<string, unknown>) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/backups/inspect')) {
      return new Response(JSON.stringify(verdict), { status: 200, headers: { 'content-type': 'application/json' } })
    }
    return new Response('', { status: 204 })
  })
}

async function lookInside(verdict: Record<string, unknown>) {
  vi.stubGlobal('fetch', answerWith(verdict))
  const done = vi.fn()
  render(<RestoreDialog open username="admin" onClose={() => undefined} onDone={done} />)
  const user = userEvent.setup()
  await user.upload(
    document.querySelector('#restore-file') as HTMLInputElement,
    new File([new Uint8Array([1, 2, 3])], 'backup.zip', { type: 'application/zip' }),
  )
  await user.type(document.querySelector('#restore-password') as HTMLInputElement, 'the-password')
  await user.click(screen.getByRole('button', { name: /Look inside|Reingucken/i }))
  await waitFor(() => expect(screen.getByText(/before the migration/)).toBeInTheDocument())
  return { user, done }
}

describe('RestoreDialog', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('shows what is in the archive before anything is replaced', async () => {
    await lookInside(VERDICT)
    expect(screen.getByText('0.1.0')).toBeInTheDocument()
  })

  it('stays quiet about the key when the archive brings one and nothing overrides it', async () => {
    await lookInside(VERDICT)
    expect(screen.queryByText(/NEXDECK_SECRET_KEY/)).toBeNull()
  })

  it('warns hardest when there is no key anywhere', async () => {
    /** ⚠️ The combination that leaves every connection unreadable. */
    await lookInside({ ...VERDICT, key_inside: false, key_from_env: false })
    expect(screen.getByText(/entered again|neu eingetragen/i)).toBeInTheDocument()
  })

  it('explains the variable when the archive has no key but the machine does', async () => {
    await lookInside({ ...VERDICT, key_inside: false, key_from_env: true })
    expect(screen.getByText(/NEXDECK_SECRET_KEY/)).toBeInTheDocument()
    expect(screen.queryByText(/entered again|neu eingetragen/i)).toBeNull()
  })

  it('says the variable wins when both have one', async () => {
    await lookInside({ ...VERDICT, key_inside: true, key_from_env: true })
    expect(screen.getByText(/wins|gewinnt/i)).toBeInTheDocument()
  })

  it('will not replace anything until the name is typed', async () => {
    const { user } = await lookInside(VERDICT)
    const go = screen.getByRole('button', { name: /Replace everything|alles ersetzen/i })
    expect(go).toBeDisabled()

    await user.type(document.querySelector('#restore-confirm') as HTMLInputElement, 'wrong')
    expect(go).toBeDisabled()

    await user.clear(document.querySelector('#restore-confirm') as HTMLInputElement)
    await user.type(document.querySelector('#restore-confirm') as HTMLInputElement, 'admin')
    expect(go).toBeEnabled()
  })

  it('does not offer to replace a backup from a newer nexdeck', async () => {
    await lookInside({ ...VERDICT, restorable: false, reason: 'too_new' })
    expect(document.querySelector('#restore-confirm')).toBeNull()
    expect(screen.getByRole('button', { name: /Replace everything|alles ersetzen/i })).toBeDisabled()
  })
})
