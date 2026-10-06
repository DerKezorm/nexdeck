/**
 * The buttons that appear over a card on hover, against what its head shows.
 *
 * ⚠️ Seen on the screenshot in issue #29, 06.10.2026: "reload" and "open"
 * floated over the right corner of the card and lay on the status dot and the
 * beta mark, just when somebody was looking at the card. jsdom measures no
 * layout, so only a real browser can say whether two things overlap.
 *
 * Named to sort after `first-start.spec.ts`, which needs the empty
 * installation.
 */
import { expect, test, type Page } from '@playwright/test'

const ACCOUNT = { username: 'e2e-admin', password: 'A-long-enough-password-1' }
const CSRF = { 'X-Nexdeck-Request': '1' }

async function signIn(page: Page) {
  await page.goto('/')
  await expect(page.getByLabel('User name')).toBeVisible()
  await page.getByLabel('User name').fill(ACCOUNT.username)
  await page.getByLabel('Password', { exact: true }).fill(ACCOUNT.password)
  const confirm = page.getByLabel('Confirm password')
  if (await confirm.isVisible()) {
    await confirm.fill(ACCOUNT.password)
    await page.getByRole('button', { name: 'Next' }).click()
    await page.getByRole('button', { name: 'Next' }).click()
    await page.getByRole('button', { name: 'Finish' }).click()
  } else {
    await page.getByRole('button', { name: 'Sign in' }).click()
  }
  await expect(page).toHaveURL(/\/b\//)
}

/** Whether any of the buttons lies over the dot or the beta mark, in the card's own coordinates. */
function overlaps(page: Page, title: string) {
  return page.locator(`section[aria-label="${title}"]`).evaluate((card) => {
    const box = (element: Element) => element.getBoundingClientRect()
    const marks = [card.querySelector('header .dot'), [...card.querySelectorAll('header .chip')].find((chip) => chip.textContent === 'beta')]
    const buttons = [...card.querySelectorAll('.card-controls :is(button, a)')].filter((button) => box(button).width > 0)
    const hits: string[] = []
    for (const mark of marks) {
      if (!mark) return { buttons: buttons.length, marks: -1, hits }
      const m = box(mark)
      for (const button of buttons) {
        const b = box(button)
        if (b.left < m.right && b.right > m.left && b.top < m.bottom && b.bottom > m.top) hits.push(`${button.getAttribute('aria-label')} over ${mark.className}`)
      }
    }
    return { buttons: buttons.length, marks: marks.length, hits }
  })
}

test('the buttons of a hovered card leave the dot and the beta mark in sight', async ({ page }) => {
  await signIn(page)
  const service = await page.request.post('/api/v1/integrations', { data: { kind: 'nomad', name: 'Nomad here', config: {}, demo: true }, headers: CSRF })
  expect(service.status()).toBe(201)
  const made = await page.request.post('/api/v1/boards', { data: { name: 'Heads', slug: 'heads' }, headers: CSRF })
  expect(made.status()).toBe(201)
  try {
    const pageId = (await made.json()).pages[0].id
    const card = await page.request.post(`/api/v1/pages/${pageId}/widgets`, {
      data: { kind: 'nomad.summary', title: 'Nomad jobs', integration_id: (await service.json()).id, link: 'https://example.com/nomad' },
      headers: CSRF,
    })
    expect(card.status()).toBe(201)
    const id = String((await card.json()).widget.id)
    const placed = await page.request.put(`/api/v1/pages/${pageId}/layouts`, { data: { lg: [{ i: id, x: 0, y: 0, w: 6, h: 2 }] }, headers: CSRF })
    expect(placed.ok()).toBe(true)

    await page.goto('/b/heads')
    const section = page.locator('section[aria-label="Nomad jobs"]')
    await expect(section.getByText('beta', { exact: true })).toBeVisible()

    await section.hover()
    // Both buttons in sight once the card is hovered, and the transition run.
    await expect(section.getByRole('button', { name: 'Refresh now' })).toBeVisible()
    await expect.poll(async () => (await overlaps(page, 'Nomad jobs')).buttons).toBe(2)
    await page.waitForTimeout(300)
    const seen = await overlaps(page, 'Nomad jobs')
    expect(seen.marks, 'the card shows no dot or no beta mark').toBe(2)
    expect(seen.hits, 'a button lies over what the head says').toEqual([])

    // The same in edit mode, where the buttons are always there.
    await page.getByRole('button', { name: 'Edit board' }).click()
    await expect(section.getByRole('button', { name: 'Widget settings' })).toBeVisible()
    await page.waitForTimeout(300)
    const editing = await overlaps(page, 'Nomad jobs')
    expect(editing.buttons, 'no buttons while editing').toBeGreaterThan(0)
    expect(editing.hits, 'a button lies over what the head says while editing').toEqual([])
    await page.getByRole('button', { name: 'Edit board' }).click()
  } finally {
    await page.request.delete('/api/v1/boards/heads', { headers: CSRF })
    await page.request.delete(`/api/v1/integrations/${(await service.json()).id}`, { headers: CSRF })
  }
})
