/**
 * The last thing between a mistake and a white page.
 *
 * ⚠️ There was no boundary at all. A render error, or a lazy chunk that is no
 * longer on the server because a deploy happened while a tab sat open,
 * unmounted the whole tree: a blank white page, no message, no button, no hint
 * that reloading would help. On a wall display nobody is standing there to
 * work that out.
 */
import { render, screen } from '@testing-library/react'
import { vi } from 'vitest'

import { ErrorBoundary } from './ErrorBoundary'

function Breaks({ how }: { how: string }): never {
  throw new Error(how)
}

beforeEach(() => {
  // React writes the caught error to the console on purpose; the test knows.
  vi.spyOn(console, 'error').mockImplementation(() => {})
})

it('shows something to read and a way on, instead of nothing', () => {
  render(
    <ErrorBoundary>
      <Breaks how="Cannot read properties of undefined" />
    </ErrorBoundary>,
  )
  expect(screen.getByRole('alert')).toBeTruthy()
  expect(screen.getByText(/Cannot read properties of undefined/)).toBeTruthy()
  expect(screen.getByRole('button', { name: /reload/i })).toBeTruthy()
})

it('names a stale chunk for what it is, because that one has a cure', () => {
  render(
    <ErrorBoundary>
      <Breaks how="Failed to fetch dynamically imported module: /assets/SettingsPage-abc.js" />
    </ErrorBoundary>,
  )
  expect(screen.getByText(/newer version is on the server/i)).toBeTruthy()
  expect(screen.getByRole('button', { name: /reload/i })).toBeTruthy()
  expect(screen.queryByRole('button', { name: /try again/i })).toBeNull()
})

it('draws its children when nothing is wrong', () => {
  render(
    <ErrorBoundary>
      <p>the board</p>
    </ErrorBoundary>,
  )
  expect(screen.getByText('the board')).toBeTruthy()
  expect(screen.queryByRole('alert')).toBeNull()
})
