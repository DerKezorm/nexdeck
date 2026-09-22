/**
 * The import from Homepage and Homarr: files in, a plan out, and nothing
 * made until the plan has been looked at, what is missing typed in and what
 * is not wanted left out.
 */
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useAuth } from '../stores/auth'
import { DashboardImport, fieldFor, type Plan } from './DashboardImport'

const PLAN: Plan = {
  source: 'homepage',
  connections: [
    { key: 'n1', kind: 'sonarr', label: 'Sonarr', icon: 'sonarr', name: 'Sonarr', config: { url: 'http://sonarr:8989', api_key: 'k' }, missing: [], fields: [], use: 'create', existing: [] },
    {
      key: 'n2', kind: 'radarr', label: 'Radarr', icon: 'radarr', name: 'Radarr', config: { url: 'http://radarr:7878' }, missing: ['api_key'],
      fields: [{ name: 'url', label: 'URL', secret: false, required: true }, { name: 'api_key', label: 'API key', secret: true, required: true }], use: 'create', existing: [{ id: 9, name: 'Radarr at home' }],
    },
  ],
  pages: [{ name: 'Media', cards: [
    { key: 'c1', kind: 'sonarr.status', title: 'Sonarr', icon: 'sonarr', connection: 'n1', include: true },
    { key: 'c2', kind: 'radarr.status', title: 'Radarr', icon: 'radarr', connection: 'n2', include: true },
    { key: 'c3', kind: 'core.app', title: 'Router', icon: 'lucide:link', connection: null, include: true },
  ] }],
  notes: ['Media > Radarr: api_key is a Homepage placeholder, not a value. Fill it in below.'],
}

const sent = vi.hoisted(() => ({ calls: [] as { path: string; body: Record<string, unknown> }[] }))
vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  post: vi.fn(async (path: string, body: Record<string, unknown>) => {
    sent.calls.push({ path, body })
    return path === '/imports/preview' ? structuredClone(PLAN) : { slug: 'from-homepage' }
  }),
}))

function show() {
  return render(
    <MemoryRouter>
      <DashboardImport />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  sent.calls = []
  useAuth.setState({ user: { id: 1, username: 'admin', role: 'admin' } as never })
})

describe('picked files', () => {
  it('find their field by name, and JSON means Homarr', () => {
    expect(fieldFor('services.yaml')).toBe('services')
    expect(fieldFor('my-bookmarks.yml')).toBe('bookmarks')
    expect(fieldFor('widgets.yaml')).toBe('widgets')
    expect(fieldFor('default.json')).toBe('config')
    expect(fieldFor('settings.yaml')).toBeNull()
  })
})

describe('the plan', () => {
  async function planned() {
    show()
    await userEvent.type(screen.getByLabelText('services.yaml'), '- Media:')
    await userEvent.click(screen.getByRole('button', { name: 'Show what would be made' }))
    await screen.findByLabelText('Name of the new board')
    expect(sent.calls[0]).toEqual({ path: '/imports/preview', body: { source: 'homepage', files: { services: '- Media:', bookmarks: '', widgets: '' } } })
  }

  it('holds the board back until a missing value is typed in', async () => {
    await planned()
    const make = screen.getByRole('button', { name: 'Make the board' })
    expect(make).toHaveProperty('disabled', true)
    expect(screen.getByText(/placeholder/)).toBeTruthy()
    await userEvent.type(screen.getByLabelText('API key'), 'typed-in')
    expect(make).toHaveProperty('disabled', false)
    await userEvent.click(make)
    await waitFor(() => expect(sent.calls).toHaveLength(2))
    const plan = sent.calls[1].body.plan as Plan
    expect(plan.connections[1].config.api_key).toBe('typed-in')
    expect(sent.calls[1].body.name).toBe('From Homepage')
  })

  it('takes the cards of a connection left out along, and sends a card left out as left out', async () => {
    await planned()
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Radarr' }), 'none')
    const radarr = screen.getByRole('checkbox', { name: /Radarr/ })
    expect(radarr).toHaveProperty('disabled', true)
    expect(screen.getByText('2 cards')).toBeTruthy()
    await userEvent.click(screen.getByRole('checkbox', { name: /Router/ }))
    expect(screen.getByText('1 card')).toBeTruthy()
    await userEvent.click(screen.getByRole('button', { name: 'Make the board' }))
    await waitFor(() => expect(sent.calls).toHaveLength(2))
    const plan = sent.calls[1].body.plan as Plan
    expect(plan.connections[1].use).toBeNull()
    expect(plan.pages[0].cards.find((card) => card.title === 'Router')?.include).toBe(false)
  })

  it('offers an existing connection, and creating one only to an administrator', async () => {
    useAuth.setState({ user: { id: 2, username: 'kim', role: 'user' } as never })
    await planned()
    const options = Array.from((screen.getByRole('combobox', { name: 'Radarr' }) as HTMLSelectElement).options).map((option) => option.value)
    expect(options).toEqual(['9', 'none'])
  })
})
