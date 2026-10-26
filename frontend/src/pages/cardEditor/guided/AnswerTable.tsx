import { useTranslation } from 'react-i18next'

import type { Condition } from '../../../lib/cardSuggestions'
import { rowMatches, type AnswerTable as Table, type Cell } from './guided'

const cellText = (value: Cell | undefined) => (value === null || value === undefined ? '' : String(value))

/**
 * The answer of the service as a table (U5): the first entries of a list with their plain fields as columns, the
 * field names on top, and how many more there are; any other answer as Field | Value. With `highlight` the entries
 * the conditions keep are marked; only those shown, the number itself is the server's.
 *
 * It scrolls sideways in its own box on a narrow screen (U11).
 */
export function AnswerTable({ table, highlight }: { table: Table; highlight?: Condition[] | null }) {
  const { t, i18n } = useTranslation()
  const number = (value: number) => value.toLocaleString(i18n.language)
  const hits = table.kind === 'rows' && highlight ? table.rows.filter((row) => rowMatches(row, highlight)).length : 0

  return (
    <section className="rounded-2xl border border-line overflow-hidden min-w-0" aria-label={t('editor.guided.table.answer')} data-testid="card-answer-table">
      <div className="flex flex-wrap items-center justify-between gap-2 px-3.5 py-2.5 border-b border-line">
        <h3 className="text-sm font-semibold">{t('editor.guided.table.answer')}</h3>
        {table.kind === 'rows' && (
          <span className="text-[12.5px] text-muted">
            {t('editor.guided.table.entries', { count: table.total, number: number(table.total) })}
            {highlight && (
              <>
                {' · '}
                <strong className="text-accent">{t('editor.guided.table.matching', { count: hits, number: number(hits) })}</strong>
              </>
            )}
          </span>
        )}
      </div>
      <div className="overflow-x-auto">
        {table.kind === 'rows' && table.total === 0 ? (
          <p className="px-3.5 py-3 text-[12.5px] text-muted" data-testid="card-answer-none">
            {t('editor.guided.table.noEntries')}
          </p>
        ) : table.kind === 'rows' ? (
          <table className="w-full border-collapse text-[12.5px]">
            <thead>
              <tr>
                {table.columns.map((column) => (
                  <th key={column} scope="col" className="text-left font-semibold text-muted bg-surface-hover px-3 py-1.5 border-b border-line whitespace-nowrap font-mono text-[11.5px]">
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((row, index) => {
                const hit = highlight ? rowMatches(row, highlight) : null
                return (
                  <tr key={index} data-hit={hit === null ? undefined : String(hit)} className={hit === true ? 'bg-accent-soft' : hit === false ? 'text-faint' : ''}>
                    {table.columns.map((column) => (
                      <td key={column} className="px-3 py-1.5 border-b border-line whitespace-nowrap tabular-nums max-w-[24rem] overflow-hidden text-ellipsis">
                        {cellText(row[column])}
                      </td>
                    ))}
                  </tr>
                )
              })}
            </tbody>
          </table>
        ) : table.fields.length ? (
          <table className="w-full border-collapse text-[12.5px]">
            <thead>
              <tr>
                <th scope="col" className="text-left font-semibold text-muted bg-surface-hover px-3 py-1.5 border-b border-line">
                  {t('editor.guided.table.field')}
                </th>
                <th scope="col" className="text-left font-semibold text-muted bg-surface-hover px-3 py-1.5 border-b border-line">
                  {t('editor.guided.table.value')}
                </th>
              </tr>
            </thead>
            <tbody>
              {table.fields.map((field) => (
                <tr key={field.path}>
                  <td className="px-3 py-1.5 border-b border-line whitespace-nowrap font-mono text-[11.5px]">{field.path}</td>
                  <td className="px-3 py-1.5 border-b border-line whitespace-nowrap tabular-nums max-w-[24rem] overflow-hidden text-ellipsis">{cellText(field.value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="px-3.5 py-3 text-[12.5px] text-muted">{t('editor.guided.table.empty')}</p>
        )}
      </div>
      {table.kind === 'rows' && table.total > table.rows.length && (
        <p className="px-3.5 py-2 text-[12px] text-faint">{t('editor.guided.table.more', { count: table.total - table.rows.length, number: number(table.total - table.rows.length) })}</p>
      )}
    </section>
  )
}
