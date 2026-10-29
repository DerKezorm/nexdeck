/**
 * Sharing a card in the Card shop (KARTEN-16): the button, what the dialog asks for and shows, the sign-in to GitHub with a
 * code, a sign-in that ended while the words are kept, the file without signing in, one send for a double click, and
 * "My submissions".
 */
import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import i18next from 'i18next'
import { useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useAuth } from '../../../stores/auth'
import { calls, entry, failure, renderWith, reset, STATE_ON, stub, world } from '../../../test/shopWorld'
import { CustomCardsSettings } from '../CustomCardsSettings'
import { OwnIntegrations } from '../OwnIntegrations'

// The drawing of the card needs the renderers; what matters here is that the dialog asks for it.
vi.mock('../ImportPreview', () => ({ default: () => <div data-testid="tile-preview">tile</div> }))

const SLUG = 'queue-size'

function Where() {
  const where = useLocation()
  return <p data-testid="where">{where.pathname + where.search}</p>
}
const SIGNED_OUT = { signed_in: false, login: null, github_id: null, until: null, pending: null }
const SIGNED_IN = { signed_in: true, login: 'someone', github_id: '4242', until: '2027-04-30T10:00:00Z', pending: null }

const CHECK = (over: Record<string, unknown> = {}) => ({
  type: 'card',
  slug: SLUG,
  name: 'Queue size',
  version: '1.0.0',
  problems: [],
  warnings: { real_values: [] },
  signed_in: true,
  login: 'someone',
  mode: 'new',
  previous_version: null,
  based_on: null,
  removed: null,
  daily: { used: 2, max: 10, reached: false },
  github: null,
  suggested: { description: 'How many items wait in the queue.', category: 'media' },
  reads: [],
  repo: 'DerKezorm/nexdeck-workshop',
  ...over,
})

const SENT = { issue: { number: 12, url: 'https://github.com/DerKezorm/nexdeck-workshop/issues/12', state: 'open' }, created: true, changed: true, update: false }

const row = (over = {}) => ({
  slug: SLUG,
  name: { en: 'Queue size' },
  description: null,
  form: 'value',
  version: '1.0.0',
  author: null,
  requires: [],
  origin: 'local',
  shop_version: '',
  boards: [],
  users_may_place: false,
  updated_at: '2026-10-25T10:00:00Z',
  shop: null,
  ...over,
})

const SUBMISSION = (over = {}) => ({
  issue: 12,
  url: 'https://github.com/DerKezorm/nexdeck-workshop/issues/12',
  slug: SLUG,
  type: 'card',
  update: false,
  created_at: '2026-10-28T09:00:00Z',
  state: 'checking',
  reasons: [],
  removed: null,
  entry: null,
  local: true,
  ...over,
})

beforeEach(() => {
  localStorage.clear()
  reset([entry()], STATE_ON)
  world.given['GET /cards'] = { status: 200, body: { cards: [row()], limit: 200 } }
  world.given['GET /workshop/github'] = { status: 200, body: SIGNED_IN }
  world.given['POST /workshop/submit/check'] = { status: 200, body: CHECK() }
  world.given['GET /cards/queue-size'] = { status: 200, body: { slug: SLUG, yaml: 'nexdeck-card: 1\n', updated_at: '2026-10-25T10:00:00Z' } }
  world.given['POST /workshop/submit'] = { status: 200, body: SENT }
  useAuth.setState({ user: { id: 1, username: 'admin', role: 'admin' } as never, loading: false })
  stub()
})
afterEach(async () => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  await i18next.changeLanguage('en')
})

async function openDialog() {
  renderWith(<CustomCardsSettings />, '/system/cards')
  await userEvent.click(await screen.findByRole('button', { name: 'Share Queue size in the Card shop' }))
  return await screen.findByRole('dialog', { name: 'Share in the Card shop' })
}

const shareButton = (dialog: HTMLElement, name = 'Share') => within(dialog).getByRole('button', { name })

describe('the button and what the dialog asks for', () => {
  it('karten16 ac1: every card of the list has a button "Share in the Card shop", and so has every own connection', async () => {
    renderWith(<CustomCardsSettings />, '/system/cards')
    const card = (await screen.findByText('Queue size')).closest('li')!
    expect(within(card).getByRole('button', { name: 'Share Queue size in the Card shop' })).toBeEnabled()
  })

  it('karten16 ac1: an own connection has the button too', async () => {
    world.given['GET /own-integrations'] = { status: 200, body: [{ short: 'memos', kind: 'custom:memos', name: 'Memos', logo: '', description: '', connections: 0, updated_at: '2026-10-25T10:00:00Z', updated_by: 'admin' }] }
    renderWith(<OwnIntegrations />, '/system/cards')
    await userEvent.click(await screen.findByRole('button', { name: 'Share Memos in the Card shop' }))
    await waitFor(() => expect(calls('POST', '/workshop/submit/check')[0].body).toEqual({ type: 'integration', slug: 'memos' }))
  })

  it('karten16 ac2: the dialog starts from what the card says, shows how it will look, and asks for category and licence', async () => {
    const dialog = await openDialog()
    expect(calls('POST', '/workshop/submit/check')[0].body).toEqual({ type: 'card', slug: SLUG })
    expect(await within(dialog).findByLabelText('Description')).toHaveValue('How many items wait in the queue.')
    expect(within(dialog).getByLabelText('Category')).toHaveValue('media')
    expect(await within(dialog).findByTestId('tile-preview')).toBeInTheDocument()
    expect(within(dialog).getByText('How it will look in the shop')).toBeInTheDocument()
    // The licence is not ticked for him: sharing waits for it.
    expect(shareButton(dialog)).toBeDisabled()
    await userEvent.click(within(dialog).getByRole('checkbox', { name: /MIT License/ }))
    expect(shareButton(dialog)).toBeEnabled()
    await userEvent.clear(within(dialog).getByLabelText('Description'))
    expect(shareButton(dialog)).toBeDisabled()
  })

  it('karten16 ac2: a category has to be picked from the list', async () => {
    world.given['POST /workshop/submit/check'] = { status: 200, body: CHECK({ suggested: { description: 'Text.', category: '' } }) }
    const dialog = await openDialog()
    await userEvent.click(await within(dialog).findByRole('checkbox', { name: /MIT License/ }))
    expect(shareButton(dialog)).toBeDisabled()
    await userEvent.selectOptions(within(dialog).getByLabelText('Category'), 'smart_home')
    expect(shareButton(dialog)).toBeEnabled()
  })

  it('karten16 ac2: demo data and English texts missing are said, and nothing can be shared', async () => {
    world.given['POST /workshop/submit/check'] = {
      status: 200,
      body: CHECK({ problems: [{ code: 'card_needs_demo', message: 'A card for the shop needs demo data.', path: 'demo' }, { code: 'weird_one', message: 'Something only the server knows.', path: '' }] }),
    }
    const dialog = await openDialog()
    const list = await within(dialog).findByTestId('share-problems')
    expect(within(list).getByText(/A card for the shop needs demo data. Add them in the editor./)).toBeInTheDocument()
    expect(within(list).getByText('Something only the server knows.')).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('checkbox', { name: /MIT License/ }))
    expect(shareButton(dialog)).toBeDisabled()
  })

  it('karten16 ec4: demo values that look like real ones are warned of with their places, and sharing stays possible', async () => {
    world.given['POST /workshop/submit/check'] = { status: 200, body: CHECK({ warnings: { real_values: [{ path: 'demo.queue.records[0].title', value: 'My Private Show' }] } }) }
    const dialog = await openDialog()
    const warning = await within(dialog).findByTestId('share-real-values')
    expect(warning).toHaveTextContent('demo.queue.records[0].title')
    expect(warning).toHaveTextContent('My Private Show')
    await userEvent.click(within(dialog).getByRole('checkbox', { name: /MIT License/ }))
    expect(shareButton(dialog)).toBeEnabled()
  })

  it('karten16 ec9: ten new ones today are said before sending', async () => {
    world.given['POST /workshop/submit/check'] = { status: 200, body: CHECK({ daily: { used: 10, max: 10, reached: true } }) }
    const dialog = await openDialog()
    expect(await within(dialog).findByTestId('share-daily')).toHaveTextContent('most the Workshop takes in a day')
    await userEvent.click(within(dialog).getByRole('checkbox', { name: /MIT License/ }))
    expect(shareButton(dialog)).toBeDisabled()
  })

  it('karten16 ac8: a card made from somebody else\'s says what it is based on', async () => {
    world.given['POST /workshop/submit/check'] = { status: 200, body: CHECK({ based_on: '777/their-card' }) }
    const dialog = await openDialog()
    expect(await within(dialog).findByText(/Based on 777\/their-card/)).toBeInTheDocument()
  })

  it('karten16 ec3: a private repository that does not let this account in is said in a sentence', async () => {
    world.given['POST /workshop/submit/check'] = { status: 200, body: CHECK({ github: { code: 'repo_no_access', message: 'x' } }) }
    const dialog = await openDialog()
    expect(await within(dialog).findByTestId('share-github-trouble')).toHaveTextContent('only invited accounts can share cards')
  })
})

describe('sending', () => {
  it('karten16 ac5: sharing sends what was written, once, however often the button is pressed', async () => {
    const dialog = await openDialog()
    await userEvent.click(await within(dialog).findByRole('checkbox', { name: /MIT License/ }))
    const button = shareButton(dialog)
    await userEvent.dblClick(button)
    await within(dialog).findByTestId('share-done')
    expect(calls('POST', '/workshop/submit')).toHaveLength(1)
    expect(calls('POST', '/workshop/submit')[0].body).toEqual({ type: 'card', slug: SLUG, category: 'media', description: 'How many items wait in the queue.', changes: '', license: true })
    expect(within(dialog).getByRole('link', { name: 'Open issue 12 on GitHub' })).toHaveAttribute('href', SENT.issue.url)
  })

  it('karten16 ac7: an update asks for the list of changes and says it is an update', async () => {
    world.given['POST /workshop/submit/check'] = { status: 200, body: CHECK({ mode: 'update', previous_version: '1.0.0', daily: null }) }
    const dialog = await openDialog()
    expect(await within(dialog).findByText(/which is at version 1.0.0 now/)).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('checkbox', { name: /MIT License/ }))
    const send = shareButton(dialog, 'Submit update')
    expect(send).toBeDisabled()
    await userEvent.type(within(dialog).getByLabelText('What changed'), 'Added the unit.')
    expect(send).toBeEnabled()
    await userEvent.click(send)
    await within(dialog).findByTestId('share-done')
    expect(calls('POST', '/workshop/submit')[0].body).toMatchObject({ changes: 'Added the unit.' })
  })

  it('karten16 ac2: what the server finds wrong on sending is shown and the words stay', async () => {
    world.given['POST /workshop/submit'] = { status: 400, body: { detail: { code: 'submission_invalid', message: 'x', problems: [{ code: 'secret_in_text', message: 'x', path: 'description' }] } } }
    const dialog = await openDialog()
    await userEvent.type(await within(dialog).findByLabelText('Description'), ' More.')
    await userEvent.click(within(dialog).getByRole('checkbox', { name: /MIT License/ }))
    await userEvent.click(shareButton(dialog))
    expect(await within(dialog).findByText(/seems to hold a key or a password/)).toBeInTheDocument()
    expect(within(dialog).getByLabelText('Description')).toHaveValue('How many items wait in the queue. More.')
    expect(shareButton(dialog)).toBeEnabled()
  })

  it('karten16 ec2: a sign-in that ended asks again, in the same dialog, and what was written is kept', async () => {
    world.given['POST /workshop/submit'] = failure(409, 'github_login_needed', 'x')
    const dialog = await openDialog()
    await userEvent.type(await within(dialog).findByLabelText('Description'), ' Extra.')
    await userEvent.click(within(dialog).getByRole('checkbox', { name: /MIT License/ }))
    world.given['POST /workshop/submit/check'] = { status: 200, body: CHECK({ signed_in: false, login: null }) }
    await userEvent.click(shareButton(dialog))
    expect(await within(dialog).findByTestId('github-signin')).toBeInTheDocument()
    expect(within(dialog).getByLabelText('Description')).toHaveValue('How many items wait in the queue. Extra.')
    expect(within(dialog).getByRole('checkbox', { name: /MIT License/ })).toBeChecked()
  })
})

describe('signing in to GitHub', () => {
  const notSignedIn = () => {
    world.given['GET /workshop/github'] = { status: 200, body: SIGNED_OUT }
    world.given['POST /workshop/submit/check'] = { status: 200, body: CHECK({ signed_in: false, login: null }) }
  }

  it('karten16 ac3: a code and a link are shown, and the dialog goes on when GitHub has said yes', async () => {
    notSignedIn()
    world.given['POST /workshop/github/login'] = { status: 200, body: { user_code: 'WDJB-1001', verification_uri: 'https://github.com/login/device', expires_in: 900, interval: 1 } }
    world.given['POST /workshop/github/login/poll'] = { status: 200, body: { status: 'signed_in', ...SIGNED_IN } }
    const dialog = await openDialog()
    await userEvent.click(await within(dialog).findByRole('button', { name: 'Sign in to GitHub' }))
    expect(await within(dialog).findByTestId('github-code')).toHaveTextContent('WDJB-1001')
    expect(within(dialog).getByRole('link', { name: 'Open github.com' })).toHaveAttribute('href', 'https://github.com/login/device')
    world.given['POST /workshop/submit/check'] = { status: 200, body: CHECK() }
    await waitFor(() => expect(within(dialog).getByTestId('github-signed-in')).toHaveTextContent('Signed in to GitHub as someone'), { timeout: 4000 })
    expect(calls('POST', '/workshop/github/login/poll').length).toBeGreaterThanOrEqual(1)
    expect(calls('POST', '/workshop/submit/check').length).toBeGreaterThanOrEqual(2)
  })

  it('karten16 ec1: a code that ran out is replaced by a new one', async () => {
    notSignedIn()
    let codes = 0
    world.given['POST /workshop/github/login'] = () => ({ status: 200, body: { user_code: `WDJB-${1000 + ++codes}`, verification_uri: 'https://github.com/login/device', expires_in: 900, interval: 1 } })
    world.given['POST /workshop/github/login/poll'] = { status: 200, body: { status: 'expired' } }
    const dialog = await openDialog()
    await userEvent.click(await within(dialog).findByRole('button', { name: 'Sign in to GitHub' }))
    expect(await within(dialog).findByText('The code ran out.', {}, { timeout: 4000 })).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Get a new code' }))
    expect(await within(dialog).findByTestId('github-code')).toHaveTextContent('WDJB-1002')
  })

  it('karten16 ac9: without signing in the submission is a file and a link to the form on GitHub', async () => {
    notSignedIn()
    URL.createObjectURL = vi.fn(() => 'blob:x')
    URL.revokeObjectURL = vi.fn()
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    world.given['POST /workshop/submit/file'] = { status: 200, body: { filename: 'nexdeck-submission-queue-size.md', text: '### Type\n', link: 'https://github.com/DerKezorm/nexdeck-workshop/issues/new?template=submit.yml' } }
    const dialog = await openDialog()
    const offline = await within(dialog).findByTestId('share-offline')
    const file = within(offline).getByRole('button', { name: 'Download the file' })
    expect(file).toBeDisabled()
    await userEvent.click(within(dialog).getByRole('checkbox', { name: /MIT License/ }))
    await userEvent.click(file)
    expect(await within(dialog).findByTestId('share-form-link')).toHaveAttribute('href', expect.stringContaining('issues/new?template=submit.yml'))
    expect(click).toHaveBeenCalledTimes(1)
    expect(calls('POST', '/workshop/submit')).toHaveLength(0)
  })
})

describe('My submissions', () => {
  const open = async () => {
    renderWith(<CustomCardsSettings />, '/system/cards?tab=submissions')
    return await screen.findByTestId('submissions')
  }

  it('karten16 ac6: each submission says where it stands, with the reasons or the reason', async () => {
    world.given['GET /workshop/submissions'] = {
      status: 200,
      body: {
        signed_in: true,
        login: 'someone',
        catalog_known: true,
        items: [
          SUBMISSION({ slug: 'a-card', issue: 1 }),
          SUBMISSION({ slug: 'bad-card', issue: 2, state: 'failed', reasons: ['The demo data do not work (line 12).', 'Add a description.'] }),
          SUBMISSION({ slug: 'good-card', issue: 3, state: 'in_shop', entry: { id: '4242/good-card', version: '1.2.0', thumbs: 5, discussion: null } }),
          SUBMISSION({ slug: 'gone-card', issue: 4, state: 'removed', removed: { level: 'harmful', reason: 'It deletes things.', at: '2026-10-27T10:00:00Z' } }),
          SUBMISSION({ slug: 'late-card', issue: 5, state: 'waiting' }),
        ],
      },
    }
    const list = await open()
    const by = (slug: string) => within(list).getByText(slug).closest('li')!
    expect(within(by('a-card')).getByText('In review')).toBeInTheDocument()
    expect(within(by('bad-card')).getByText('Needs a fix')).toBeInTheDocument()
    expect(within(by('bad-card')).getByTestId('submission-reasons')).toHaveTextContent('The demo data do not work (line 12).')
    expect(within(by('bad-card')).getByTestId('submission-reasons')).toHaveTextContent('Add a description.')
    expect(within(by('good-card')).getByText('In the Card shop')).toBeInTheDocument()
    expect(within(by('good-card')).getByText('Version 1.2.0')).toBeInTheDocument()
    expect(within(by('gone-card')).getByTestId('submission-removed')).toHaveTextContent('Removed (harmful): It deletes things.')
    expect(within(by('late-card')).getByText('Waits for tomorrow')).toBeInTheDocument()
  })

  it('karten16 ac6: signed out, it asks for the sign-in and shows nothing', async () => {
    world.given['GET /workshop/submissions'] = { status: 200, body: { signed_in: false, login: null, items: [], catalog_known: false } }
    world.given['GET /workshop/github'] = { status: 200, body: SIGNED_OUT }
    const list = await open()
    expect(within(list).getByTestId('github-signin')).toBeInTheDocument()
    expect(within(list).queryByTestId('submission')).toBeNull()
  })

  it('karten16 ac6: no submissions yet says so', async () => {
    world.given['GET /workshop/submissions'] = { status: 200, body: { signed_in: true, login: 'someone', items: [], catalog_known: true } }
    const list = await open()
    expect(await within(list).findByText('You have not shared anything yet')).toBeInTheDocument()
  })

  it('karten16 ac4: signing out deletes the sign-in', async () => {
    world.given['GET /workshop/submissions'] = () => ({
      status: 200,
      body: { signed_in: calls('DELETE', '/workshop/github').length === 0, login: 'someone', items: [], catalog_known: true },
    })
    const list = await open()
    await userEvent.click(await within(list).findByRole('button', { name: 'Sign out of GitHub' }))
    await waitFor(() => expect(calls('DELETE', '/workshop/github')).toHaveLength(1))
    expect(await within(list).findByTestId('github-signin')).toBeInTheDocument()
  })

  it('karten16 ac10: "Fix and resend" opens the card in the editor with the issue to send it into', async () => {
    world.given['GET /workshop/submissions'] = { status: 200, body: { signed_in: true, login: 'someone', items: [SUBMISSION({ state: 'failed', reasons: ['No.'] }), SUBMISSION({ slug: 'gone', issue: 13, state: 'failed', reasons: ['No.'], local: false })], catalog_known: true } }
    renderWith(
      <>
        <CustomCardsSettings />
        <Where />
      </>,
      '/system/cards?tab=submissions',
    )
    const list = await screen.findByTestId('submissions')
    const gone = within(list).getByText('gone').closest('li')!
    expect(within(gone).getByRole('button', { name: 'Fix and resend' })).toBeDisabled()
    await userEvent.click(within(within(list).getByText(SLUG).closest('li')!).getByRole('button', { name: 'Fix and resend' }))
    expect(screen.getByTestId('where')).toHaveTextContent('/system/custom-cards/queue-size/edit?resend=12')
  })

  it('karten16 ac7: a card in the shop can be handed in again as an update from the list', async () => {
    world.given['GET /workshop/submissions'] = { status: 200, body: { signed_in: true, login: 'someone', items: [SUBMISSION({ state: 'in_shop', entry: { id: '4242/queue-size', version: '1.0.0', thumbs: 1, discussion: null } })], catalog_known: true } }
    const list = await open()
    await userEvent.click(await within(list).findByRole('button', { name: 'Submit update' }))
    expect(await screen.findByRole('dialog', { name: 'Share in the Card shop' })).toBeInTheDocument()
    expect(calls('POST', '/workshop/submit/check')[0].body).toEqual({ type: 'card', slug: SLUG })
  })
})

describe('a credential in the demo data (S3)', () => {
  it('karten8s s3: secret_in_demo is said in the words of the interface with its place, and nothing can be shared', async () => {
    world.given['POST /workshop/submit/check'] = {
      status: 200,
      body: CHECK({ problems: [{ code: 'secret_in_demo', message: 'The demo data hold a credential at demo.host.apiKey (key apiKey).', path: 'demo.host.apiKey' }] }),
    }
    const dialog = await openDialog()
    const list = await within(dialog).findByTestId('share-problems')
    expect(within(list).getByText('The demo data hold a key or a password at demo.host.apiKey. Replace it with "[hidden]" or a made-up value.')).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('checkbox', { name: /MIT License/ }))
    expect(shareButton(dialog)).toBeDisabled()
  })
})
