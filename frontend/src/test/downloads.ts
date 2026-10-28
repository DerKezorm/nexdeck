import { vi } from 'vitest'

/**
 * Catches the files the app hands to the browser: the names they were saved under, in the order they were saved.
 * jsdom has no object addresses and does not follow a click on a link, so both are stood in for.
 */
export function catchDownloads(): { names: string[]; restore: () => void } {
  const names: string[] = []
  const original = { create: URL.createObjectURL, revoke: URL.revokeObjectURL }
  URL.createObjectURL = vi.fn(() => 'blob:export')
  URL.revokeObjectURL = vi.fn()
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    names.push(this.download)
  })
  return {
    names,
    restore: () => {
      click.mockRestore()
      URL.createObjectURL = original.create
      URL.revokeObjectURL = original.revoke
    },
  }
}

/** Lets one address answer with a file, and every other one as before. Returns the stand-in, to see what was asked. */
export function answerWithFile(address: string, body: string, headers: Record<string, string> = {}, status = 200) {
  const before = globalThis.fetch
  const answer = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input).replace(/^.*\/api\/v1/, '') === address) return new Response(body, { status, headers })
    return before(input, init)
  })
  vi.stubGlobal('fetch', answer)
  return answer
}
