/**
 * One reading of a failed answer, whatever shape it arrives in.
 *
 * ⚠️ There were four separate ones, and none of them knew what FastAPI sends
 * for a body it rejects: a 422 carries `detail` as a **list** of field errors,
 * so all four fell through to their fallback and the person saw "HTTP 422"
 * instead of which field was wrong.
 */
import { readFailure } from './client'

describe('readFailure', () => {
  it("reads nexdeck's own shape", () => {
    const seen = readFailure({ detail: { code: 'quota_full', message: 'The limit is 200 MB.', hint: 'Delete a file.' } }, 413)
    expect(seen.code).toBe('quota_full')
    expect(seen.message).toBe('The limit is 200 MB.')
    expect(seen.hint).toBe('Delete a file.')
  })

  it('reads the flat shape the 404 handler sends', () => {
    const seen = readFailure({ code: 'not_found', message: 'There is no such address.' }, 404)
    expect(seen.code).toBe('not_found')
    expect(seen.message).toBe('There is no such address.')
  })

  it('says which field FastAPI rejected instead of the number 422', () => {
    const seen = readFailure(
      {
        detail: [
          { loc: ['body', 'refresh_seconds'], msg: 'Input should be greater than or equal to 5', type: 'greater_than_equal' },
          { loc: ['body', 'title'], msg: 'Field required', type: 'missing' },
        ],
      },
      422,
    )
    expect(seen.code).toBe('invalid')
    expect(seen.message).toContain('refresh_seconds')
    expect(seen.message).toContain('title')
    expect(seen.message).not.toContain('HTTP 422')
  })

  it('passes a plain string detail through', () => {
    expect(readFailure({ detail: 'Not authenticated' }, 401).message).toBe('Not authenticated')
  })

  it('falls back to the status when there is nothing to read', () => {
    expect(readFailure(null, 500).message).toBe('HTTP 500')
    expect(readFailure({}, 502).message).toBe('HTTP 502')
  })
})
