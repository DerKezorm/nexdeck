/**
 * The server decides where the language lands when the pair changes, so the
 * screen follows its answer, not the request.
 */
import i18n from '../i18n'
import { useAuth } from './auth'

vi.mock('../api/client', () => ({
  ApiError: class ApiError extends Error {},
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(async (_path: string, fields: Record<string, unknown>) => ({
    id: 1,
    username: 'ada',
    // Giving the active button another language switches to that language.
    locale: 'de',
    language_pair: fields.language_pair,
    theme: 'dark',
  })),
}))

afterEach(async () => {
  await i18n.changeLanguage('en')
})

it('switches to the language the server answers with after a new pair', async () => {
  expect(i18n.language).toBe('en')
  await useAuth.getState().update({ language_pair: ['de', 'en'] })
  expect(i18n.language).toBe('de')
  expect(useAuth.getState().user?.language_pair).toEqual(['de', 'en'])
})
