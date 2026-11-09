import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'

import { useAuth } from '../../stores/auth'
import { IntegrationsSettings } from './IntegrationsSettings'

const state = vi.hoisted(() => ({
  enrolled: false,
  rejectEnrolment: false,
  rejectUnenrolment: false,
  requests: [] as { path: string; body: unknown }[],
}))

const adapter = {
  kind: 'synology',
  label: 'Synology',
  category: 'system',
  description: '',
  icon: 'synology',
  beta: false,
  docs_url: '',
  needs_integration: true,
  widgets: [],
  fields: [
    { name: 'url', label: 'URL', type: 'url', required: true },
    { name: 'username', label: 'User name', type: 'text', required: true },
    { name: 'password', label: 'Password', type: 'password', required: true, secret: true },
    { name: 'device_id', label: 'Trusted device', type: 'password', secret: true },
  ],
}

function response(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function show() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })

  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <IntegrationsSettings />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function openEditor() {
  await userEvent.click(
    await screen.findByRole('button', { name: 'Edit Synology NAS' }),
  )
  return screen.findByRole('dialog')
}

beforeEach(() => {
  state.enrolled = false
  state.rejectEnrolment = false
  state.rejectUnenrolment = false
  state.requests = []

  useAuth.setState({
    user: { id: 1, username: 'admin', role: 'admin' } as never,
    loading: false,
  })

  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input).replace(/^.*\/api\/v1/, '')
    const method = init?.method ?? 'GET'

    if (path === '/adapters') return response([adapter])

    if (path === '/integrations' && method === 'GET') {
      return response([{
        id: 7,
        kind: 'synology',
        label: 'Synology',
        icon: 'synology',
        beta: false,
        name: 'Synology NAS',
        config: {
          url: 'https://nas.local:5001',
          username: 'testuser',
          password: '********',
          ...(state.enrolled ? { device_id: '********' } : {}),
        },
        enabled: true,
        demo: false,
        admin_only: false,
        muted: false,
        last_ok_at: null,
        last_error: '',
        widget_count: 0,
        created_at: '2026-11-06T10:00:00Z',
      }])
    }

    if (path === '/about') {
      return response({
        version: '1.3.0',
        demo: false,
        demo_forced: false,
        demo_data: false,
      })
    }

    if (path === '/integrations/versions') return response({})
    if (path === '/boards') return response([])
    if (path === '/integrations/found') {
      return response({ found: [], ignored: 0, looked_at: null })
    }

    if (path === '/integrations/7/mfa/enrol' && method === 'POST') {
      const body = JSON.parse(String(init?.body))
      state.requests.push({ path, body })
      if (state.rejectEnrolment) {
        return response({
          detail: {
            code: 'synology_mfa_failed',
            message: 'Synology MFA enrolment failed.',
          },
        }, 400)
      }
      state.enrolled = true
      return response({
        ok: true,
        message: 'Synology trusted device enrolled successfully.',
      })
    }

    if (path === '/integrations/7/mfa/unenrol' && method === 'POST') {
      const body = JSON.parse(String(init?.body))
      state.requests.push({ path, body })
      if (state.rejectUnenrolment) {
        return response({
          detail: {
            code: 'synology_unenrol_failed',
            message: 'Could not remove Synology trusted device.',
          },
        }, 400)
      }
      state.enrolled = false
      return response({
        ok: true,
        message: 'Synology trusted device removed.',
      })
    }

    return response({})
  }))
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Synology trusted-device enrolment', () => {
  it('shows enrolment controls without exposing the device credential field', async () => {
    show()
    const dialog = await openEditor()

    expect(within(dialog).getByText('Synology trusted device')).toBeInTheDocument()
    expect(within(dialog).getByText('Not enrolled')).toBeInTheDocument()
    expect(within(dialog).getByLabelText('Authentication code')).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Enrol trusted device' })).toBeDisabled()

    expect(within(dialog).queryByText('Trusted device')).toBeNull()
  })

  it('only enables enrolment for a six-digit code', async () => {
    show()
    const dialog = await openEditor()
    const code = within(dialog).getByLabelText('Authentication code')
    const button = within(dialog).getByRole('button', { name: 'Enrol trusted device' })

    await userEvent.type(code, '12345')
    expect(button).toBeDisabled()

    await userEvent.type(code, '6')
    expect(button).toBeEnabled()
  })

  it('enrols a trusted device and keeps the editor open', async () => {
    show()
    const dialog = await openEditor()

    await userEvent.type(
      within(dialog).getByLabelText('Authentication code'),
      '123456',
    )

    await userEvent.click(
      within(dialog).getByRole('button', { name: 'Enrol trusted device' }),
    )

    await waitFor(() => {
      expect(state.requests).toEqual([{
        path: '/integrations/7/mfa/enrol',
        body: { otp: '123456' },
      }])
    })

    expect(await within(dialog).findByText('Enrolled')).toBeInTheDocument()
    expect(within(dialog).getByText('Synology trusted device enrolled successfully.')).toBeInTheDocument()
    expect(within(dialog).getByLabelText('Authentication code')).toHaveValue('')
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('rejects an invalid MFA code without marking the device enrolled', async () => {
    state.rejectEnrolment = true
    show()

    const dialog = await openEditor()
    const code = within(dialog).getByLabelText('Authentication code')

    await userEvent.type(code, '123456')
    await userEvent.click(
      within(dialog).getByRole('button', { name: 'Enrol trusted device' }),
    )

    expect(
      await within(dialog).findByText('Synology MFA enrolment failed.'),
    ).toBeInTheDocument()

    expect(within(dialog).getByText('Not enrolled')).toBeInTheDocument()
    expect(code).toHaveValue('')
    expect(state.enrolled).toBe(false)
    expect(state.requests).toHaveLength(1)
  })


  it.each([
    ['URL', 'https://another-nas.local:5001'],
    ['User name', 'differentuser'],
    ['Password', 'new-password'],
  ])('blocks MFA enrolment when %s has unsaved changes', async (field, value) => {
    show()

    const dialog = await openEditor()

    const input = within(dialog).getByLabelText(new RegExp(`^${field}\\s*\\*?$`))

    await userEvent.clear(input)
    await userEvent.type(input, value)

    expect(
      within(dialog).getByText('Save changes first'),
    ).toBeInTheDocument()

    await userEvent.type(
      within(dialog).getByLabelText('Authentication code'),
      '123456',
    )

    expect(
      within(dialog).getByRole('button', { name: 'Enrol trusted device' }),
    ).toBeDisabled()

    expect(state.requests).toHaveLength(0)
  })


  it('retains enrolled status when the editor is reopened', async () => {
    show()

    const dialog = await openEditor()

    await userEvent.type(
      within(dialog).getByLabelText('Authentication code'),
      '123456',
    )

    await userEvent.click(
      within(dialog).getByRole('button', { name: 'Enrol trusted device' }),
    )

    expect(await within(dialog).findByText('Enrolled')).toBeInTheDocument()

    await waitFor(() => {
      expect(state.enrolled).toBe(true)
    })

    await userEvent.click(
      within(dialog).getByRole('button', { name: 'Cancel' }),
    )

    await waitFor(() => {
      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    })

    const reopened = await openEditor()

    expect(within(reopened).getByText('Enrolled')).toBeInTheDocument()
    expect(
      within(reopened).getByRole('button', { name: 'Re-enrol trusted device' }),
    ).toBeDisabled()
  })


  it('shows Un-enrol only for an enrolled trusted device', async () => {
    show()
    const dialog = await openEditor()

    expect(
      within(dialog).queryByRole('button', { name: 'Un-enrol trusted device' }),
    ).not.toBeInTheDocument()

    expect(within(dialog).getByText('Not enrolled')).toBeInTheDocument()
  })

  it('requires confirmation before removing the trusted device', async () => {
    state.enrolled = true
    show()

    const dialog = await openEditor()

    await userEvent.click(
      within(dialog).getByRole('button', { name: 'Un-enrol trusted device' }),
    )

    const confirmation = await screen.findByRole('dialog', {
      name: 'Un-enrol Synology trusted device?',
    })

    expect(state.requests).toHaveLength(0)
    expect(state.enrolled).toBe(true)

    await userEvent.click(
      within(confirmation).getByRole('button', { name: 'Cancel' }),
    )

    await waitFor(() => {
      expect(
        screen.queryByRole('dialog', {
          name: 'Un-enrol Synology trusted device?',
        }),
      ).not.toBeInTheDocument()
    })

    expect(state.requests).toHaveLength(0)
    expect(within(dialog).getByText('Enrolled')).toBeInTheDocument()
  })

  it('un-enrols without an MFA code and updates the status', async () => {
    state.enrolled = true
    show()

    const dialog = await openEditor()

    expect(within(dialog).getByLabelText('Authentication code')).toHaveValue('')

    await userEvent.click(
      within(dialog).getByRole('button', { name: 'Un-enrol trusted device' }),
    )

    const confirmation = await screen.findByRole('dialog', {
      name: 'Un-enrol Synology trusted device?',
    })

    await userEvent.click(
      within(confirmation).getByRole('button', { name: 'Un-enrol' }),
    )

    await waitFor(() => {
      expect(state.requests).toEqual([{
        path: '/integrations/7/mfa/unenrol',
        body: {},
      }])
    })

    expect(await within(dialog).findByText('Not enrolled')).toBeInTheDocument()
    expect(state.enrolled).toBe(false)

    expect(
      within(dialog).queryByRole('button', { name: 'Un-enrol trusted device' }),
    ).not.toBeInTheDocument()

    expect(
      within(dialog).getByText(/A new MFA code is required to re-enrol/),
    ).toBeInTheDocument()
  })

  it('preserves enrolment when the Un-enrol API fails', async () => {
    state.enrolled = true
    state.rejectUnenrolment = true
    show()

    const dialog = await openEditor()

    await userEvent.click(
      within(dialog).getByRole('button', { name: 'Un-enrol trusted device' }),
    )

    const confirmation = await screen.findByRole('dialog', {
      name: 'Un-enrol Synology trusted device?',
    })

    await userEvent.click(
      within(confirmation).getByRole('button', { name: 'Un-enrol' }),
    )

    expect(
      await within(dialog).findByText('Could not remove Synology trusted device.'),
    ).toBeInTheDocument()

    expect(within(dialog).getByText('Enrolled')).toBeInTheDocument()
    expect(state.enrolled).toBe(true)
    expect(state.requests).toHaveLength(1)
  })

})
