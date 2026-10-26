/**
 * What a new card starts as (U3, in place of decision 5): one request and nothing chosen yet. The guided way fills it
 * in: the service tile sets the kind, a suggestion the request, the answer the display, the Finish step the name and
 * from it the short name.
 */

/** A card that reads nothing yet; its name stays empty until the Finish step or a suggestion gives it one. */
export const NEW_CARD = `nexdeck-card: 1
slug: new-card
name: ""
version: "1.0.0"
requires: []
requests:
  - id: main
    path: /
form: value
value: "@"
`

/** A short name from a name: lower case letters, digits and hyphens, at most 60 (the rule of `slug`). */
export function slugFrom(name: string): string {
  return name
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/ß/g, 'ss')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60)
    .replace(/-+$/, '')
}
