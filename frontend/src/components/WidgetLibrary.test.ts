/** New widgets get a readable default title, without the service name doubled. */
import { defaultTitle } from './WidgetLibrary'

describe('defaultTitle', () => {
  it('joins service and widget, but never repeats a word', () => {
    expect(defaultTitle({ kind: 'unifi', label: 'UniFi Network' }, { label: 'Network' })).toBe('UniFi Network')
    expect(defaultTitle({ kind: 'unifi', label: 'UniFi Network' }, { label: 'Devices' })).toBe('UniFi Network Devices')
    expect(defaultTitle({ kind: 'nexview', label: 'Nexview' }, { label: 'Requests' })).toBe('Nexview Requests')
    expect(defaultTitle({ kind: 'docker', label: 'Docker' }, { label: 'Docker load' })).toBe('Docker load')
    expect(defaultTitle({ kind: 'core', label: 'Basics' }, { label: 'Clock' })).toBe('Clock')
  })
})
