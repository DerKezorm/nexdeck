/**
 * The built project needs `dist/`. CI builds the frontend in the same job
 * before it runs the end-to-end test, so there is nothing to do there; on a
 * developer's machine there may be no build at all, and a missing `dist/`
 * would show up as a server that answers 503 rather than as "you have not
 * built it".
 *
 * An existing `dist/` is left alone on purpose. Rebuilding it on every run
 * would add a minute to a test suite that mostly does not need it.
 */
import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

export default function build(): void {
  const here = path.dirname(fileURLToPath(import.meta.url))
  const frontend = path.resolve(here, '..')
  if (existsSync(path.join(frontend, 'dist', 'index.html'))) return
  process.stdout.write('No dist/ yet, building the frontend once for the built project.\n')
  execFileSync(process.platform === 'win32' ? 'npm.cmd' : 'npm', ['run', 'build'], {
    cwd: frontend,
    stdio: 'inherit',
  })
}
