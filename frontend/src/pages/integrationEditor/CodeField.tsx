/**
 * The definition as YAML in a code editor, loaded only when somebody opens this view. The same editor as the card's
 * YAML view, without the suggestions from a schema: what is typed settles for a moment and then goes to the store,
 * problems stand at their lines, and a line asked for is shown.
 */
import { defaultKeymap } from '@codemirror/commands'
import { yaml } from '@codemirror/lang-yaml'
import { bracketMatching, defaultHighlightStyle, indentUnit, syntaxHighlighting } from '@codemirror/language'
import { lintGutter, setDiagnostics, type Diagnostic } from '@codemirror/lint'
import { Annotation, EditorState } from '@codemirror/state'
import { drawSelection, EditorView, highlightActiveLine, keymap, lineNumbers } from '@codemirror/view'
import { useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'

import { localProblemText, serverProblemText } from '../cardEditor/problems'
import { currentServerProblems, useIntegrationEditor } from './store'

/** Typing settles this long before the store reads the text. */
export const SETTLE_MS = 250

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
})

export default function CodeField() {
  const { t } = useTranslation()
  const host = useRef<HTMLDivElement>(null)
  const view = useRef<EditorView | null>(null)
  const text = useIntegrationEditor((state) => state.text)
  const local = useIntegrationEditor((state) => state.problems)
  const server = useIntegrationEditor(currentServerProblems)
  const focusLine = useIntegrationEditor((state) => state.focusLine)

  useEffect(() => {
    if (!host.current) return
    let settle: number | undefined
    const hand = () => {
      window.clearTimeout(settle)
      settle = undefined
      const current = view.current
      if (current) useIntegrationEditor.getState().setText(current.state.doc.toString())
    }
    const created = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: useIntegrationEditor.getState().text,
        extensions: [
          lineNumbers(),
          drawSelection(),
          highlightActiveLine(),
          bracketMatching(),
          EditorState.tabSize.of(2),
          indentUnit.of('  '),
          yaml(),
          syntaxHighlighting(defaultHighlightStyle, { fallback: true }),
          lintGutter(),
          // ⚠️ Tab writes two spaces: YAML refuses tabs for indenting. Escape, then Tab, leaves the field.
          keymap.of([{ key: 'Tab', run: (target) => (target.dispatch(target.state.replaceSelection('  ')), true) }, ...defaultKeymap]),
          EditorView.lineWrapping,
          EditorView.contentAttributes.of({ 'aria-label': t('integrationEditor.yaml.label') }),
          theme,
          EditorView.updateListener.of((update) => {
            if (!update.docChanged || update.transactions.every((one) => one.annotation(external) === true)) return
            window.clearTimeout(settle)
            settle = window.setTimeout(hand, SETTLE_MS)
          }),
          EditorView.domEventHandlers({ blur: () => hand() }),
        ],
      }),
    })
    view.current = created
    useIntegrationEditor.setState({ flusher: hand })
    return () => {
      hand()
      useIntegrationEditor.setState({ flusher: null })
      created.destroy()
      view.current = null
    }
    // The view is made once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // The store changed from elsewhere (a reload, the form): the code editor follows.
  useEffect(
    () =>
      useIntegrationEditor.subscribe((state, before) => {
        const current = view.current
        if (!current || state.text === before.text || current.state.doc.toString() === state.text) return
        const keep = Math.min(current.state.selection.main.head, state.text.length)
        current.dispatch({ changes: { from: 0, to: current.state.doc.length, insert: state.text }, selection: { anchor: keep }, annotations: external.of(true) })
      }),
    [],
  )

  // Every problem at its line.
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

  useEffect(() => {
    const current = view.current
    if (!current || focusLine === null) return
    const line = current.state.doc.line(Math.min(Math.max(focusLine, 1), current.state.doc.lines))
    current.dispatch({ selection: { anchor: line.from }, effects: EditorView.scrollIntoView(line.from, { y: 'center' }) })
    current.focus()
    useIntegrationEditor.getState().lineShown()
  }, [focusLine])

  return <div ref={host} className="min-h-[420px] h-[70vh] rounded-xl border border-line bg-surface p-1 overflow-hidden" data-testid="integration-yaml" />
}
