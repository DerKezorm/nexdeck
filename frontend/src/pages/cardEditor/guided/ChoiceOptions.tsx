import { useTranslation } from 'react-i18next'

import type { Choice } from './columns'

/** The options of a field choice: the important fields first, the others in a group "More fields". */
export function ChoiceOptions({ choices }: { choices: Choice[] }) {
  const { t } = useTranslation()
  const first = choices.filter((one) => !one.more)
  const more = choices.filter((one) => one.more)
  const option = (one: Choice) => (
    <option key={one.value} value={one.value}>
      {one.label}
    </option>
  )
  return (
    <>
      {first.map(option)}
      {first.length && more.length ? <optgroup label={t('editor.guided.display.moreFields')}>{more.map(option)}</optgroup> : more.map(option)}
    </>
  )
}
