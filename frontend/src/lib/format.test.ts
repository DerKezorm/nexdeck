import { formatValue, iconUrl, timeAgo } from './format'

describe('formatValue', () => {
  it('formats numbers with units', () => {
    // Ten and above lose their decimals; the cards stay calm.
    expect(formatValue(38.24, '%')).toBe('38%')
    expect(formatValue(3.84, '%')).toBe('3.8%')
    // Thousands follow the browser's locale; the test must not assume one.
    expect(formatValue(1284)).toBe((1284).toLocaleString())
    expect(formatValue(7, '/ 10')).toBe('7 / 10')
    expect(formatValue(null)).toBe('—')
    expect(formatValue('closed')).toBe('closed')
  })

  it('shows as many decimals as the card was set to (#78)', () => {
    expect(formatValue(0.07, '', 2)).toBe('0.07')
    expect(formatValue(5.04, '', 2)).toBe('5.04')
    expect(formatValue(0.1, '', 2)).toBe('0.10')
    expect(formatValue(12.5, '°C', 1)).toBe('12.5°C')
    expect(formatValue(12.46, '', 0)).toBe('12')
    // A whole number stays whole, and without the setting nothing changes.
    expect(formatValue(5, '', 2)).toBe('5')
    expect(formatValue(0.07)).toBe('0.1')
    expect(formatValue(1284.5, '', 1)).toBe((1284.5).toLocaleString(undefined, { maximumFractionDigits: 1 }))
  })
})

describe('timeAgo', () => {
  it('rounds to the readable unit', () => {
    const now = 1_000_000
    expect(timeAgo(now - 30, now)).toBe('30s')
    expect(timeAgo(now - 7200, now)).toBe('2h')
    expect(timeAgo(now - 3 * 86400, now)).toBe('3d')
    expect(timeAgo(null, now)).toBe('')
  })
})

describe('iconUrl', () => {
  it('routes names through the server proxy and leaves URLs alone', () => {
    expect(iconUrl('radarr')).toBe('/api/v1/icons/radarr.svg')
    expect(iconUrl('https://example.com/x.png')).toBe('https://example.com/x.png')
    expect(iconUrl('')).toBeNull()
  })
})
