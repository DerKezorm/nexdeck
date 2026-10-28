/**
 * The colours of YAML in the editors of cards and integrations. The stock style of CodeMirror is made for a white page:
 * its dark blue for keys sat on the dark theme at about 1.5:1 (nearly unreadable). Here every kind of text takes a token
 * of the interface, so it follows the theme, and `src/lib/yamlHighlight.test.ts` holds each of them to 4.5:1 on both.
 */
import { HighlightStyle } from '@codemirror/language'
import { tags } from '@lezer/highlight'

/** The token (a CSS variable of `app.css`) of each kind of text. */
export const YAML_COLORS = {
  key: 'nd-accent',
  string: 'nd-ok',
  special: 'nd-warn',
  comment: 'nd-text-muted',
  invalid: 'nd-bad',
} as const

const colour = (kind: keyof typeof YAML_COLORS) => `var(--${YAML_COLORS[kind]})`

export const yamlHighlight = HighlightStyle.define([
  { tag: [tags.definition(tags.propertyName), tags.propertyName], color: colour('key') },
  { tag: [tags.string, tags.special(tags.string)], color: colour('string') },
  { tag: [tags.labelName, tags.typeName, tags.keyword, tags.atom, tags.number, tags.bool], color: colour('special') },
  { tag: tags.comment, color: colour('comment'), fontStyle: 'italic' },
  { tag: tags.invalid, color: colour('invalid') },
])
