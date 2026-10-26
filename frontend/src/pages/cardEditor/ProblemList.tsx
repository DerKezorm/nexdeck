import { useTranslation } from 'react-i18next'

import { localProblemText, partOfProblem, serverProblemText } from './problems'
import { currentServerProblems, useCardEditor } from './store'

/**
 * Every problem of the card at its line with its reason (KARTEN-10 AC-2, AC-5; KARTEN-9 AC-13): those of the YAML
 * itself, found in this browser, and those the server found on saving or on checking. A line opens in the YAML view.
 * In the guided way a problem names the part of the card in its words ("The number"), never the path of a field.
 */
export function ProblemList() {
  const { t } = useTranslation()
  const local = useCardEditor((state) => state.problems)
  const server = useCardEditor(currentServerProblems)
  const goToLine = useCardEditor((state) => state.goToLine)
  const view = useCardEditor((state) => state.view)
  if (!local.length && !server.length) return null
  const rows = [
    ...local.map((problem) => ({ line: problem.line, path: '', text: localProblemText(t, problem) })),
    ...server.map((problem) => ({ line: problem.line, path: view === 'guided' ? (partOfProblem(t, problem.path) ?? '') : problem.path, text: serverProblemText(t, problem) })),
  ]
  return (
    <div className="rounded-xl border border-bad/40 px-3 py-2 min-w-0" role="alert" data-testid="card-problems">
      <div className="text-sm font-medium text-bad mb-1 break-words hyphens-auto">{t('cards.problems')}</div>
      <ul className="text-[13px] space-y-1">
        {rows.map((row, index) => (
          <li key={index} className="break-words">
            {row.line !== null ? (
              <button type="button" className="text-faint hover:text-accent hover:underline" onClick={() => goToLine(row.line ?? 1)} aria-label={view === 'yaml' ? t('editor.problems.showLine', { line: row.line }) : t('editor.problems.openLine', { line: row.line })}>
                {t('cards.line', { line: row.line })}
              </button>
            ) : null}
            {row.path ? <span className="text-faint">{row.line !== null ? ' · ' : ''}{row.path}</span> : null}
            {row.line !== null || row.path ? ' · ' : ''}
            <span>{row.text}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
