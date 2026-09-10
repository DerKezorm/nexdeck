/* The dev server for the end-to-end run, started again when it dies.
 *
 *   node tools/dev-server.mjs --host 127.0.0.1 --port 5799 --strictPort
 *
 * ⚠️ Not a nicety. Measured on 09.09.2026 over eighteen full runs on Windows
 * on ARM64 with Node 25.3.0: the Vite dev server aborts in about one run in
 * five with exit code 3221226505, which is 0xC0000409, Windows' code for a
 * stack overflow. It says nothing at all first: no message, no stack, no
 * diagnostic report, nothing in the event log, and the machine had three
 * gigabytes free every time. It is a known and unsolved problem around
 * Rollup's native binding on Windows (nodejs/help#5119, reported there on
 * Node 22 as well), and nothing in nexdeck can fix it.
 *
 * What nexdeck can decide is what a test run does about it. Until now the run
 * died with the server, and it did not die honestly: the browser was still on
 * the board, so the first test reported "this card is not visible after 15
 * seconds" and every test after it reported that it could not reach the port.
 * Three hours went into that sentence once. So the server comes back, the
 * crash is written down in words, and the run carries on.
 *
 * The restarts are counted and the count is printed at the end, because a
 * crash that heals silently is a crash nobody fixes. Above RESTART_LIMIT the
 * supervisor gives up: at that point something is broken that restarting will
 * not mend, and pretending otherwise would hide it.
 */
import { spawn } from 'node:child_process'

/** How often the server may be brought back before we stop believing in it. */
const RESTART_LIMIT = 5
/** Long enough for the port to be free again, short enough not to fail a wait. */
const RESTART_DELAY_MS = 300

const args = process.argv.slice(2)
const stamp = () => new Date().toTimeString().slice(0, 8)

let child = null
let restarts = 0
let stopping = false

/** Playwright tears the run down by killing this tree; that is not a crash. */
const stop = (signal) => {
  stopping = true
  child?.kill(signal)
}
for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP', 'SIGBREAK']) {
  process.on(signal, () => stop(signal))
}

const start = () => {
  child = spawn('npm', ['run', 'dev', '--', ...args], { stdio: 'inherit', shell: true })
  child.on('error', (error) => {
    console.error(`[dev-server ${stamp()}] could not start: ${error.message}`)
    process.exit(1)
  })
  child.on('exit', (code, signal) => {
    if (stopping) return
    restarts += 1
    if (restarts > RESTART_LIMIT) {
      console.error(`[dev-server ${stamp()}] gave up after ${RESTART_LIMIT} restarts; the last exit was ${code ?? signal}.`)
      process.exit(code ?? 1)
    }
    // ⚠️ Said in words, not as a number. 3221226505 means nothing to anyone
    // reading a test log at midnight.
    const why = code === 3221226505 ? 'it crashed the way Windows reports a stack overflow, saying nothing' : `it ended with ${code ?? signal}`
    console.error(`[dev-server ${stamp()}] The dev server is gone: ${why}. Starting it again (${restarts} of ${RESTART_LIMIT}).`)
    setTimeout(start, RESTART_DELAY_MS)
  })
}

process.on('exit', () => {
  if (restarts) console.error(`[dev-server] The dev server had to be started again ${restarts} time(s) during this run.`)
})

start()
