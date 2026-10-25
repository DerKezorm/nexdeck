import { useTranslation } from 'react-i18next'

import { readAt } from '../../../lib/cardDocument'
import { slotName } from '../DataTree'
import { pathsOfValue, slotsOf } from '../slots'
import { useCardEditor } from '../store'
import { RulesFields } from './fields'
import { StepFrame } from './StepFrame'

/**
 * Step 3, Rules (KARTEN-9 AC-7): when the whole card, one of its values or a row changes colour. Each rule is a form
 * (what is compared, how, with what, which colour); a field or a formula can be typed instead of picked.
 */
export function RulesStep() {
  const { t } = useTranslation()
  const card = useCardEditor((state) => state.card ?? state.lastValid?.card ?? null)
  if (!card) return <StepFrame step="rules" />
  const form = readAt(card, ['form'])
  const values = slotsOf(card).filter((slot) => !slot.row && readAt(card, slot.path) !== undefined)
  // A rule of the card names what it looks at; the first value the card shows is the likely one.
  const first = values.flatMap((slot) => pathsOfValue(readAt(card, slot.path)))[0]

  return (
    <StepFrame step="rules">
      <RulesFields path={['rules']} own={false} title={t('editor.rules.card')} defaultField={first} />
      {values.map((slot) => (
        <RulesFields key={slot.id} path={[...slot.path, 'rules']} own title={t('editor.rules.ofValue', { place: slotName(t, slot) })} />
      ))}
      {form === 'list' && <RulesFields path={['item', 'status']} own title={t('editor.rules.row')} />}
    </StepFrame>
  )
}
