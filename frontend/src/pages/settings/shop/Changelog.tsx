import { useTranslation } from 'react-i18next'

import { changelogSections, newerSections } from '../../../lib/changelog'

/**
 * The CHANGELOG of an entry set as small headings, text and lists; plain text all the way, nothing here makes HTML.
 * With `installed` only the sections newer than that version stand (the update dialog); without it all of them (the detail page).
 */
export function Changelog({ text, installed, testId }: { text: string; installed?: string; testId: string }) {
  const { t } = useTranslation()
  const sections = installed === undefined ? changelogSections(text) : newerSections(text, installed)
  if (sections.length === 0) return <p className="text-sm text-muted">{t('cards.shop.noChanges')}</p>
  return (
    <div className="grid gap-3" data-testid={testId}>
      {sections.map((section, at) => (
        <div key={`${section.heading}-${at}`} className="grid gap-1">
          {section.heading && <h5 className="text-[12px] font-semibold text-muted break-words">{section.heading}</h5>}
          {section.blocks.map((block, index) =>
            block.kind === 'text' ? (
              <p key={index} className="text-sm break-words">
                {block.text}
              </p>
            ) : (
              <ul key={index} className="list-disc pl-5 grid gap-0.5 text-sm break-words">
                {block.items.map((item, place) => (
                  <li key={place}>{item}</li>
                ))}
              </ul>
            ),
          )}
        </div>
      ))}
    </div>
  )
}
