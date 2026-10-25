import { X } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { pathText } from '../../../lib/cardDocument'
import { problemText } from '../../../lib/customCards'
import { currentServerProblems, useCardEditor } from '../store'
import { languagesOf, OFFERED_LANGUAGES, removeLanguage, textIn, textSpots, writeText, type TextSpot } from '../texts'
import { StepFrame } from './StepFrame'

/** A language by its name in the language on screen: `de` is "Deutsch" to a German, "German" to an English reader. */
function languageName(code: string, uiLanguage: string): string {
  try {
    const name = new Intl.DisplayNames([uiLanguage], { type: 'language' }).of(code)
    return name && name !== code ? name.charAt(0).toLocaleUpperCase(uiLanguage) + name.slice(1) : code
  } catch {
    return code
  }
}

/**
 * Step 4, Texts (KARTEN-9 AC-8): every text of the card, one field per language, English first and required. Another
 * language can be added; a field left empty shows the English text there.
 */
export function TextsStep() {
  const { t, i18n } = useTranslation()
  const card = useCardEditor((state) => state.card ?? state.lastValid?.card ?? null)
  const editable = useCardEditor((state) => state.card !== null)
  const change = useCardEditor((state) => state.change)
  const server = useCardEditor(currentServerProblems)
  const [added, setAdded] = useState<string[]>([])
  const [choosing, setChoosing] = useState('')

  const spots = useMemo(() => (card ? textSpots(card) : []), [card])
  const written = useMemo(() => (card ? languagesOf(card, spots) : ['en']), [card, spots])
  const languages = [...written, ...added.filter((code) => !written.includes(code))]
  const free = OFFERED_LANGUAGES.filter((code) => !languages.includes(code))
  const ui = i18n.language

  if (!card) return <StepFrame step="texts" />

  const label = (spot: TextSpot) => t(spot.label.key, { number: spot.label.number })
  const write = (spot: TextSpot, language: string, text: string) => change((doc) => writeText(doc, spot, language, text), `text:${spot.id}:${language}`)
  const drop = (language: string) => {
    setAdded((now) => now.filter((code) => code !== language))
    change((doc) => removeLanguage(doc, spots, language))
  }

  return (
    <StepFrame step="texts">
      <div className="flex flex-wrap items-center gap-1.5" aria-label={t('editor.texts.languages')} role="group">
        {languages.map((code) => (
          <span key={code} className="chip inline-flex items-center gap-1 break-words hyphens-auto" lang={ui}>
            {code === 'en' ? t('editor.texts.english') : languageName(code, ui)}
            {code !== 'en' && (
              <button type="button" className="text-muted hover:text-ink" onClick={() => drop(code)} disabled={!editable} aria-label={t('editor.texts.removeLanguage', { language: languageName(code, ui) })}>
                <X size={12} />
              </button>
            )}
          </span>
        ))}
        {free.length > 0 && (
          <span className="inline-flex items-center gap-1.5">
            <select className="input !h-8 !py-0 !w-auto text-sm" value={choosing} onChange={(event) => setChoosing(event.target.value)} aria-label={t('editor.texts.chooseLanguage')} disabled={!editable}>
              <option value="">{t('editor.texts.chooseLanguage')}</option>
              {free.map((code) => (
                <option key={code} value={code}>
                  {languageName(code, ui)}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="btn btn-flat !h-8"
              disabled={!choosing || !editable}
              onClick={() => {
                setAdded((now) => [...now, choosing])
                setChoosing('')
              }}
            >
              {t('editor.texts.addLanguage')}
            </button>
          </span>
        )}
      </div>

      {spots.map((spot) => {
        const where = pathText(spot.path)
        const own = server.filter((problem) => problem.path === where || problem.path.startsWith(`${where}.`))
        const english = textIn(card, spot, 'en')
        return (
          <fieldset key={spot.id} className="min-w-0 grid gap-2">
            <legend className="text-sm font-medium mb-1 break-words hyphens-auto" lang={ui}>
              {label(spot)}
            </legend>
            <div className="grid gap-2 sm:grid-cols-[repeat(auto-fit,minmax(200px,1fr))] min-w-0">
              {languages.map((code) => {
                const name = code === 'en' ? t(spot.required ? 'editor.texts.englishRequired' : 'editor.texts.english') : languageName(code, ui)
                const id = `card-text-${spot.id}-${code}`
                const value = textIn(card, spot, code)
                const Input = spot.long ? 'textarea' : 'input'
                return (
                  <label key={code} htmlFor={id} className="grid gap-1 min-w-0">
                    <span className="text-[12px] text-muted break-words hyphens-auto" lang={ui}>
                      {name}
                    </span>
                    <Input
                      id={id}
                      className="input"
                      lang={code}
                      value={value}
                      rows={spot.long ? 3 : undefined}
                      placeholder={code === 'en' ? '' : english ? t('editor.texts.fallback') : ''}
                      aria-label={`${label(spot)}, ${name}`}
                      aria-invalid={spot.required && code === 'en' && !value ? true : undefined}
                      disabled={!editable}
                      onChange={(event) => write(spot, code, event.target.value)}
                    />
                  </label>
                )
              })}
            </div>
            {spot.required && !english && (
              <p className="text-[12px] text-bad" role="alert">
                {t('editor.texts.required')}
              </p>
            )}
            {own.map((problem, index) => (
              <p key={index} className="text-[12px] text-bad" role="alert">
                {problemText(t, problem)}
              </p>
            ))}
          </fieldset>
        )
      })}
    </StepFrame>
  )
}
