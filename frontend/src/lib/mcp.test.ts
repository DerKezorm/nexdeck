/** The small rules the MCP pages share: what a right row offers, what is stored, the lines to copy. */
import { describe, expect, it } from 'vitest'

import { key, request, TOOLS } from '../test/mcpServer'
import { addCommand, expiredKey, jsonConfig, openRequest, ownerOf, requestIdOf, resultText, rightsToStore, settingOf } from './mcp'

const [attention, , press, diagnosis, log] = TOOLS

describe('settingOf', () => {
  it('never offers ask for a reading tool', () => {
    expect(settingOf(attention, key(), {}, false).options).toEqual(['allow', 'deny'])
    expect(settingOf(press, key({ level: 'act' }), {}, false).options).toEqual(['allow', 'ask', 'deny'])
  })

  it('falls back to the default, and ignores a stored ask on a reading tool', () => {
    expect(settingOf(press, key({ level: 'act' }), {}, false).value).toBe('ask')
    expect(settingOf(attention, key(), { needs_attention: 'ask' }, false).value).toBe('allow')
    expect(settingOf(attention, key(), { needs_attention: 'deny' }, false).value).toBe('deny')
  })

  it('gives the reason a row is greyed out', () => {
    expect(settingOf(log, key(), {}, true).reason).toBe('blocked')
    expect(settingOf(diagnosis, key(), {}, false).reason).toBe('adminOnly')
    expect(settingOf(diagnosis, key(), {}, true).reason).toBe('')
    expect(settingOf(press, key({ level: 'read' }), {}, false).reason).toBe('level')
    expect(settingOf(press, key({ level: 'act' }), {}, false).reason).toBe('')
  })
})

describe('rightsToStore', () => {
  it('keeps only what differs from the defaults', () => {
    const own = key({ level: 'act' })
    expect(rightsToStore(TOOLS, own, { needs_attention: 'allow', press_button: 'ask' }, false)).toEqual({})
    expect(rightsToStore(TOOLS, own, { needs_attention: 'deny', press_button: 'allow' }, false)).toEqual({ needs_attention: 'deny', press_button: 'allow' })
  })

  it('leaves a greyed-out row as the key already had it', () => {
    const own = key({ level: 'read', tool_rights: { press_button: 'allow' } })
    expect(rightsToStore(TOOLS, own, { press_button: 'deny' }, false)).toEqual({ press_button: 'allow' })
  })
})

describe('the lines to copy', () => {
  it('builds the command for Claude Code', () => {
    expect(addCommand('https://deck.example.com/api/mcp', 'ndm_abc')).toBe('claude mcp add --transport http nexdeck https://deck.example.com/api/mcp --header "Authorization: Bearer ndm_abc"')
  })

  it('builds the JSON with the key in the header and nowhere else', () => {
    const text = jsonConfig('https://deck.example.com/api/mcp', 'ndm_abc')
    expect(JSON.parse(text).mcpServers.nexdeck.headers.Authorization).toBe('Bearer ndm_abc')
    expect(text.match(/ndm_abc/g)).toHaveLength(1)
  })
})

describe('requests', () => {
  it('reads the request id from a notice link and nothing else', () => {
    expect(requestIdOf('/mcp/requests/12')).toBe(12)
    expect(requestIdOf('/mcp/requests/12/x')).toBeNull()
    expect(requestIdOf('/mcp/requests/abc')).toBeNull()
    expect(requestIdOf('/b/lab')).toBeNull()
  })

  it('can be answered only while it waits and its time is not over', () => {
    expect(openRequest(request())).toBe(true)
    expect(openRequest(request({ status: 'approved' }))).toBe(false)
    expect(openRequest(request({ expires_at: new Date(Date.now() - 1).toISOString() }))).toBe(false)
  })

  it('words the result, whatever shape it comes in', () => {
    expect(resultText(null)).toBe('')
    expect(resultText('done')).toBe('done')
    expect(resultText({ message: 'Restarted' })).toBe('Restarted')
    expect(resultText({ ok: true })).toBe('{\n  "ok": true\n}')
  })
})

describe('keys', () => {
  it('knows when a key has run out', () => {
    expect(expiredKey(key({ expires_at: null }))).toBe(false)
    expect(expiredKey(key({ expires_at: '2020-01-01T00:00:00Z' }))).toBe(true)
    expect(expiredKey(key({ expires_at: '2099-01-01T00:00:00Z' }))).toBe(false)
  })

  it('names the owner in the administrator list whichever shape arrives', () => {
    expect(ownerOf(key({ user: 'sam' }))).toBe('sam')
    expect(ownerOf(key({ user: { username: 'kim' } }))).toBe('kim')
    expect(ownerOf(key())).toBe('')
  })
})
