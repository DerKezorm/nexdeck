import { addDays, byDay, colourOf, dayOf, firstWeekday, inRange, isoOf, monthWeeks, pageBy, timeText, titleOf, weekOf } from './calendarGrid'

const days = (dates: Date[]) => dates.map(isoOf)

describe('the first day of the week follows the language', () => {
  it('begins on Monday in German, Spanish, French and Italian, whatever the browser says', () => {
    for (const language of ['de', 'es', 'fr', 'it']) expect(firstWeekday(language, 'en-US')).toBe(1)
  })

  it('asks the browser for English: Sunday in the United States, Monday in Britain', () => {
    expect(firstWeekday('en', 'en-US')).toBe(0)
    expect(firstWeekday('en', 'en-GB')).toBe(1)
  })

  it('takes the ISO week, Monday, for a tag it cannot read', () => {
    expect(firstWeekday('en', 'not a locale!')).toBe(1)
    expect(firstWeekday('', '')).toBe(1)
  })
})

describe('the days of a month and a week', () => {
  it('cover October 2026 in whole weeks from either first weekday', () => {
    const monday = monthWeeks(new Date(2026, 9, 15), 1)
    expect(monday).toHaveLength(5)
    expect([isoOf(monday[0][0]), isoOf(monday[4][6])]).toEqual(['2026-09-28', '2026-11-01'])
    const sunday = monthWeeks(new Date(2026, 9, 15), 0)
    expect([isoOf(sunday[0][0]), isoOf(sunday[sunday.length - 1][6])]).toEqual(['2026-09-27', '2026-10-31'])
  })

  it('needs four rows for a February that starts on the first day, and six for a long month that starts late', () => {
    expect(monthWeeks(new Date(2026, 1, 10), 0)).toHaveLength(4)
    expect(monthWeeks(new Date(2026, 7, 10), 1)).toHaveLength(6)
  })

  it('has seven consecutive days in a week, also across the night the clocks change', () => {
    expect(days(weekOf(new Date(2026, 9, 27), 1))).toEqual(['2026-10-26', '2026-10-27', '2026-10-28', '2026-10-29', '2026-10-30', '2026-10-31', '2026-11-01'])
    expect(days(weekOf(new Date(2026, 9, 27), 0))[0]).toBe('2026-10-25')
    // The last Sunday of March and of October, when a day is 23 or 25 hours long.
    for (const start of [new Date(2026, 2, 23), new Date(2026, 9, 19)]) {
      const week = weekOf(start, 1)
      expect(week.map((day) => day.getHours())).toEqual([0, 0, 0, 0, 0, 0, 0])
      expect(days(week)[6]).toBe(isoOf(addDays(start, 6)))
    }
  })

  it('turns a page by a month from the first, so the end of January does not skip February', () => {
    expect(isoOf(pageBy('month', new Date(2026, 0, 31), 1))).toBe('2026-02-01')
    expect(isoOf(pageBy('month', new Date(2026, 0, 31), -1))).toBe('2025-12-01')
    expect(isoOf(pageBy('week', new Date(2026, 9, 27), 1))).toBe('2026-11-03')
    expect(isoOf(pageBy('week', new Date(2026, 9, 27), -1))).toBe('2026-10-20')
  })

  it('reads a written day and refuses what is not one', () => {
    expect(dayOf('2026-10-27')?.getDate()).toBe(27)
    expect(dayOf('2026-10-27T08:00')?.getMonth()).toBe(9)
    expect(dayOf('soon')).toBeNull()
  })
})

describe('how far the arrows may go', () => {
  const range = { from: '2026-08-26', to: '2027-02-28' }

  it('allows the pages that touch what was fetched and no others', () => {
    expect(inRange('month', new Date(2026, 7, 1), 1, range)).toBe(true)
    expect(inRange('month', new Date(2026, 6, 1), 1, range)).toBe(false)
    expect(inRange('month', new Date(2027, 1, 1), 1, range)).toBe(true)
    expect(inRange('month', new Date(2027, 2, 1), 1, range)).toBe(false)
    expect(inRange('week', new Date(2026, 7, 25), 1, range)).toBe(true)
    expect(inRange('week', new Date(2026, 7, 10), 1, range)).toBe(false)
  })

  it('allows everything when the server did not say', () => {
    expect(inRange('month', new Date(2030, 0, 1), 1, undefined)).toBe(true)
  })
})

describe('the entries of a day', () => {
  it('sit on their day, all-day entries before the timed ones, those by the clock', () => {
    const grouped = byDay([
      { date: '2026-10-27', title: 'Lunch', time: '12:00' },
      { date: '2026-10-28', title: 'Other' },
      { date: '2026-10-27', title: 'Standup', time: '09:30' },
      { date: '2026-10-27', title: 'Holiday' },
    ])
    expect([...grouped.keys()]).toEqual(['2026-10-27', '2026-10-28'])
    expect(grouped.get('2026-10-27')?.map((entry) => entry.title)).toEqual(['Holiday', 'Standup', 'Lunch'])
  })

  it('wear the colour of the place their source has in the card, and one when it has none', () => {
    const colours = [0, 1, 2, 3, 4, 5].map((slot) => colourOf({ date: 'x', slot }))
    expect(new Set(colours).size).toBe(6)
    expect(colourOf({ date: 'x', slot: 6 })).toBe(colours[0])
    expect(colourOf({ date: 'x' })).toBe(colours[0])
    expect(colourOf({ date: 'x', slot: -1 })).toBe(colours[0])
  })
})

describe('the words of a page', () => {
  it('writes the month and the week in the language it is given', () => {
    expect(titleOf('month', new Date(2026, 9, 1), 1, 'de')).toBe('Oktober 2026')
    expect(titleOf('month', new Date(2026, 9, 1), 1, 'en')).toBe('October 2026')
    const week = titleOf('week', new Date(2026, 9, 27), 1, 'de')
    expect(week).toContain('26.')
    expect(week).toContain('2026')
  })

  it('writes a time the way the language does', () => {
    expect(timeText('18:30', 'de')).toBe('18:30')
    expect(timeText('18:30', 'en')).toMatch(/^6:30\s?PM$/)
    expect(timeText('soon', 'en')).toBe('soon')
  })
})
