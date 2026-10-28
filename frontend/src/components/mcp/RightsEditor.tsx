import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, put } from '../../api/client'
import { GROUPS, rightsToStore, settingOf, type McpKey, type McpRight, type McpTool } from '../../lib/mcp'
import { Select } from '../ui'

/**
 * "Rights per tool" of one key: allow, ask or deny for each tool.
 *
 * A tool that cannot be set says why instead of vanishing: blocked by the
 * administrator for every key, above the level of this key, or for
 * administrators only. Reading tools never ask; there is nothing to approve
 * about looking.
 */
export function RightsEditor({ keyRow, tools, admin, onSaved }: { keyRow: McpKey; tools: McpTool[]; admin: boolean; onSaved: () => void }) {
  const { t } = useTranslation()
  const [chosen, setChosen] = useState<Record<string, McpRight>>(keyRow.tool_rights)
  const [failure, setFailure] = useState('')
  const [busy, setBusy] = useState(false)
  const next = rightsToStore(tools, keyRow, chosen, admin)
  const changed = JSON.stringify(Object.entries(next).sort()) !== JSON.stringify(Object.entries(keyRow.tool_rights).sort())
  const save = async () => {
    setBusy(true)
    setFailure('')
    try {
      await put(`/mcp/keys/${keyRow.id}/rights`, { tool_rights: next })
      onSaved()
    } catch (error) {
      setFailure(error instanceof ApiError ? error.message : t('errors.network'))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="mt-2 border-t border-line pt-3" data-testid={`rights-${keyRow.id}`}>
      {GROUPS.map((group) => {
        const rows = tools.filter((tool) => tool.group === group)
        if (!rows.length) return null
        return (
          <section key={group} className="mb-3">
            <h4 className="text-[11px] font-semibold uppercase tracking-wide text-faint mb-1.5">{t(`mcp.group.${group}`)}</h4>
            <ul className="space-y-1.5">
              {rows.map((tool) => {
                const setting = settingOf(tool, keyRow, chosen, admin)
                const id = `right-${keyRow.id}-${tool.name}`
                return (
                  <li key={tool.name} className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <div className="min-w-0 flex-[1_1_220px]">
                      <code className="num text-xs">{tool.name}</code>
                      <p className="text-[11.5px] text-muted">{tool.description}</p>
                      {setting.reason && (
                        <p className="text-[11.5px] text-warn" data-testid={`why-${tool.name}`}>
                          {t(`mcp.rights.why.${setting.reason}`)}
                        </p>
                      )}
                    </div>
                    <label htmlFor={id} className="sr-only">
                      {t('mcp.rights.for', { tool: tool.name })}
                    </label>
                    <Select
                      id={id}
                      className="w-40 flex-none"
                      value={setting.value}
                      disabled={!!setting.reason}
                      onChange={(value) => setChosen((current) => ({ ...current, [tool.name]: value as McpRight }))}
                      options={setting.options.map((right) => ({ value: right, label: t(`mcp.rights.${right}`) }))}
                    />
                  </li>
                )
              })}
            </ul>
          </section>
        )
      })}
      {failure && <p className="text-xs text-bad mb-2">{failure}</p>}
      <button className="btn btn-accent" disabled={!changed || busy} onClick={() => void save()}>
        {t('mcp.rights.save')}
      </button>
    </div>
  )
}
