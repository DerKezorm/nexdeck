/**
 * The card as YAML (KARTEN-10), in a code editor that is loaded only when somebody opens this view (decision 2).
 *
 * What is typed goes to the editor's store, which reads it as a document: problems of the YAML itself show at once
 * at their lines, what the server's check finds follows a moment later (`POST /cards/check`), and suggestions come
 * from the card's schema (`GET /cards/schema`). Steps back and forward are the store's, so Ctrl Z in here also takes
 * back what was changed in the editor (KARTEN-9 EC-10); the code editor keeps no history of its own.
 */
import { autocompletion, type CompletionContext, type CompletionResult } from '@codemirror/autocomplete'
import { defaultKeymap } from '@codemirror/commands'
import { yaml } from '@codemirror/lang-yaml'
import { bracketMatching, indentUnit, syntaxHighlighting } from '@codemirror/language'
import { lintGutter, setDiagnostics, type Diagnostic } from '@codemirror/lint'
import { Annotation, EditorState, type Transaction } from '@codemirror/state'
import { drawSelection, EditorView, highlightActiveLine, keymap, lineNumbers } from '@codemirror/view'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'

import { get, post } from '../../api/client'
import { suggestionsAt, type SchemaNode } from '../../lib/cardSchemaCompletion'
import type { CardProblem } from '../../lib/customCards'
import { yamlHighlight } from '../../lib/yamlHighlight'
import { localProblemText, serverProblemText } from './problems'
import { currentServerProblems, useCardEditor } from './store'

/** Typing settles this long before the store reads the text: reading 60,000 characters takes a while (KARTEN-10 EC-6). */
export const SETTLE_MS = 250
/** And this long before the server is asked to check it. */
export const CHECK_MS = 700

/** Marks a change that came from the store, so that it is not handed back to the store. */
const external = Annotation.define<boolean>()

const theme = EditorView.theme({
  '&': { color: 'var(--nd-text)', backgroundColor: 'transparent', fontSize: '12.5px', height: '100%' },
  '.cm-content': { fontFamily: 'var(--font-mono, ui-monospace, monospace)', caretColor: 'var(--nd-accent)' },
  '.cm-gutters': { backgroundColor: 'transparent', color: 'var(--nd-text-faint)', border: 'none' },
  '.cm-activeLine': { backgroundColor: 'color-mix(in srgb, var(--nd-text) 5%, transparent)' },
  '.cm-activeLineGutter': { backgroundColor: 'transparent', color: 'var(--nd-text-muted)' },
  '&.cm-focused': { outline: 'none' },
  '.cm-scroller': { overflow: 'auto', lineHeight: '1.6' },
  '.cm-tooltip': { backgroundColor: 'var(--nd-bg-elev)', color: 'var(--nd-text)', border: '1px solid var(--nd-border)' },
  '.cm-tooltip-autocomplete ul li[aria-selected]': { backgroundColor: 'var(--nd-accent-soft)', color: 'var(--nd-text)' },
})

/** Was the whole text replaced by a paste: into an empty field, or over everything selected (KARTEN-10 AC-6)? */
function pastedWhole(transaction: Transaction): boolean {
  if (!transaction.isUserEvent('input.paste')) return false
  const before = transaction.startState
  const { from, to } = before.selection.main
  return before.doc.length === 0 || (from === 0 && to === before.doc.length)
}

/**
 * The server's check of a text (`POST /cards/check`), kept only while the text is still the one on screen. A pasted
 * card that passes is shown in the editor (KARTEN-10 AC-6).
 */
async function checkText(checked: string, pasted: (() => void) | null) {
  try {
    const answer = await post<{ ok: boolean; problems?: CardProblem[] }>('/cards/check', { yaml: checked })
    const editor = useCardEditor.getState()
    if (editor.text !== checked) return
    editor.setServerProblems(answer.ok ? [] : (answer.problems ?? []), checked)
    if (pasted && answer.ok && editor.leaveYaml()) pasted()
  } catch {
    // The check helps while typing; saving checks again and says what is wrong.
  }
}

export default function YamlView({ onPastedValid }: { onPastedValid?: () => void }) {
  const { t } = useTranslation()
  const host = useRef<HTMLDivElement>(null)
  const view = useRef<EditorView | null>(null)
  const text = useCardEditor((state) => state.text)
  const valid = useCardEditor((state) => state.card !== null)
  const local = useCardEditor((state) => state.problems)
  const server = useCardEditor(currentServerProblems)
  const focusLine = useCardEditor((state) => state.focusLine)
  const schema = useQuery({ queryKey: ['cards-schema'], queryFn: () => get<SchemaNode>('/cards/schema'), staleTime: Infinity })
  const schemaRef = useRef<SchemaNode | null>(null)
  const pastedRef = useRef(onPastedValid)
  useEffect(() => {
    schemaRef.current = schema.data ?? null
    pastedRef.current = onPastedValid
  })

  // One code editor for the life of this view.
  useEffect(() => {
    if (!host.current) return
    let settle: number | undefined
    let pasted = false
    const hand = () => {
      window.clearTimeout(settle)
      settle = undefined
      const current = view.current
      if (!current) return
      const typed = current.state.doc.toString()
      const editor = useCardEditor.getState()
      editor.setText(typed, 'yaml')
      if (pasted) {
        pasted = false
        if (useCardEditor.getState().card) void checkText(typed, () => pastedRef.current?.())
      }
    }
    const complete = (context: CompletionContext): CompletionResult | null => {
      const known = schemaRef.current
      if (!known) return null
      const found = suggestionsAt(known, context.state.doc.toString(), context.pos)
      if (!found) return null
      if (found.from === context.pos && !context.explicit) {
        // Nothing typed yet: offer keys only at the start of a line, not after every space.
        const line = context.state.doc.lineAt(context.pos)
        if (line.text.trim() !== '' && !/:\s+$/.test(line.text.slice(0, context.pos - line.from))) return null
      }
      return {
        from: found.from,
        options: found.options.map((one) => ({ label: one.label, type: one.kind === 'key' ? 'property' : 'enum', detail: one.detail, apply: one.kind === 'key' ? `${one.label}: ` : one.label })),
        validFor: /^[\w.-]*$/,
      }
    }
    const created = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: useCardEditor.getState().text,
        extensions: [
          lineNumbers(),
          drawSelection(),
          highlightActiveLine(),
          bracketMatching(),
          EditorState.tabSize.of(2),
          indentUnit.of('  '),
          yaml(),
          syntaxHighlighting(yamlHighlight),
          lintGutter(),
          autocompletion({ override: [complete], activateOnTyping: true }),
          // ⚠️ Tab writes two spaces: YAML refuses tabs for indenting (KARTEN-10 EC-7). Escape, then Tab, leaves the field.
          keymap.of([{ key: 'Tab', run: (target) => (target.dispatch(target.state.replaceSelection('  ')), true) }, ...defaultKeymap]),
          EditorView.lineWrapping,
          EditorView.contentAttributes.of({ 'aria-label': t('editor.yaml.label') }),
          theme,
          EditorView.updateListener.of((update) => {
            if (!update.docChanged || update.transactions.every((one) => one.annotation(external) === true)) return
            if (update.transactions.some(pastedWhole)) pasted = true
            window.clearTimeout(settle)
            settle = window.setTimeout(hand, pasted ? 0 : SETTLE_MS)
          }),
          EditorView.domEventHandlers({ blur: () => hand() }),
        ],
      }),
    })
    view.current = created
    useCardEditor.setState({ flusher: hand })
    return () => {
      hand()
      useCardEditor.setState({ flusher: null })
      created.destroy()
      view.current = null
    }
    // The view is made once; texts and schema are read through refs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // The store changed from elsewhere (a step back, a reload): the code editor follows.
  // ⚠️ Through the store's own subscription, not through the rendered `text`: a step back right after typing hands the
  // typing over and takes it back within one render, so the text on screen never differs from the one rendered before
  // and an effect on it would leave the typing in the code editor.
  useEffect(
    () =>
      useCardEditor.subscribe((state, before) => {
        const current = view.current
        if (!current || state.text === before.text || current.state.doc.toString() === state.text) return
        const keep = Math.min(current.state.selection.main.head, state.text.length)
        current.dispatch({ changes: { from: 0, to: current.state.doc.length, insert: state.text }, selection: { anchor: keep }, annotations: external.of(true) })
      }),
    [],
  )

  // Every problem at its line: the YAML's own at once, the server's once it has checked this text.
  useEffect(() => {
    const current = view.current
    if (!current) return
    const doc = current.state.doc
    const at = (line: number | null) => {
      const one = doc.line(Math.min(Math.max(line ?? 1, 1), doc.lines))
      return { from: one.from, to: Math.max(one.to, one.from) }
    }
    const diagnostics: Diagnostic[] = [
      ...local.map((problem) => ({ ...at(problem.line), severity: 'error' as const, message: localProblemText(t, problem) })),
      ...server.map((problem) => ({ ...at(problem.line), severity: 'error' as const, message: serverProblemText(t, problem) })),
    ]
    current.dispatch(setDiagnostics(current.state, diagnostics))
  }, [local, server, t, text])

  // "Open in YAML" or a problem clicked: show that line and put the cursor there.
  useEffect(() => {
    const current = view.current
    if (!current || focusLine === null) return
    const line = current.state.doc.line(Math.min(Math.max(focusLine, 1), current.state.doc.lines))
    current.dispatch({ selection: { anchor: line.from }, effects: EditorView.scrollIntoView(line.from, { y: 'center' }) })
    current.focus()
    useCardEditor.getState().lineShown()
  }, [focusLine])

  // The server's check of a valid text, a moment after typing stops.
  useEffect(() => {
    if (!valid) return
    const timer = window.setTimeout(() => void checkText(text, null), CHECK_MS)
    return () => window.clearTimeout(timer)
  }, [text, valid])

  return <div ref={host} className="min-h-[420px] h-[70vh] rounded-xl border border-line bg-surface p-1 overflow-hidden" data-testid="card-yaml" />
}
