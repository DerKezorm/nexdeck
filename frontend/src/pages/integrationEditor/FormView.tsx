/**
 * The form of the integration editor (KARTEN-3): one section for each part of the definition, every field writing
 * into the text by path, so that the YAML view shows the same thing and the comments stay.
 *
 * Basics, Fields, Sign-in, Test address, "What nexdeck can ask" and Extras. A part of the definition the form has no field
 * for is left alone; it is in the YAML view.
 */
import { ArrowDown, ArrowUp, Plus, Trash2 } from 'lucide-react'
import { useId, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { IconPicker } from '../../components/IconPicker'
import { Select } from '../../components/ui'
import { CATEGORY_ORDER } from '../../lib/adapterCategories'
import { deleteAt, readAt, setAt, type CardPath } from '../../lib/cardDocument'
import { problemText, type CardProblem } from '../../lib/customCards'
import {
  AUTH_TYPES,
  FIELD_TYPES,
  MAX_FIELDS,
  MAX_READS,
  authDefaults,
  authOf,
  fieldsOf,
  freeName,
  placeholdersIn,
  readsOf,
  shortFrom,
  type AuthType,
  type DefinedField,
} from '../../lib/integrationDocument'
import { currentServerProblems, useIntegrationEditor } from './store'

const asText = (value: unknown): string => (typeof value === 'string' ? value : typeof value === 'number' ? String(value) : '')

/** Problems of the server's check that lie in this part of the definition, each at its field. */
function Problems({ parts }: { parts: string[] }) {
  const { t } = useTranslation()
  const server = useIntegrationEditor(currentServerProblems)
  const goToLine = useIntegrationEditor((state) => state.goToLine)
  const mine = server.filter((problem) => parts.some((part) => problem.path === part || problem.path.startsWith(part + '.') || problem.path.startsWith(part + '[')))
  if (!mine.length) return null
  return (
    <ul className="text-[13px] text-bad space-y-1" role="alert" data-testid="integration-section-problems">
      {mine.map((problem: CardProblem, index) => (
        <li key={index} className="break-words">
          {problem.line !== null && (
            <button type="button" className="text-faint hover:text-accent hover:underline mr-1.5" onClick={() => goToLine(problem.line ?? 1)}>
              {t('cards.line', { line: problem.line })}
            </button>
          )}
          {problemText(t, problem)}
        </li>
      ))}
    </ul>
  )
}

function Section({ id, title, lead, parts, children }: { id: string; title: string; lead?: string; parts: string[]; children: ReactNode }) {
  return (
    <section className="glass rounded-2xl p-4 grid gap-3 min-w-0" aria-labelledby={`ie-${id}`} data-testid={`integration-section-${id}`}>
      <div>
        <h2 id={`ie-${id}`} className="font-semibold text-[15px] break-words">
          {title}
        </h2>
        {lead && <p className="text-[13px] text-muted mt-0.5 break-words hyphens-auto">{lead}</p>}
      </div>
      <Problems parts={parts} />
      {children}
    </section>
  )
}

function Labelled({ label, help, htmlFor, children }: { label: string; help?: string; htmlFor?: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <label htmlFor={htmlFor} className="block text-xs font-medium text-muted mb-1">
        {label}
      </label>
      {children}
      {help && <p className="text-[12px] text-faint mt-1 break-words hyphens-auto">{help}</p>}
    </div>
  )
}

/** A text of the definition at `path`; an empty one removes the key unless it is required. */
function TextAt({ path, label, help, mono, required, disabled, placeholder }: { path: CardPath; label: string; help?: string; mono?: boolean; required?: boolean; disabled?: boolean; placeholder?: string }) {
  const id = useId()
  const card = useIntegrationEditor((state) => state.card)
  const value = card ? asText(readAt(card, path)) : ''
  return (
    <Labelled label={label} help={help} htmlFor={id}>
      <input
        id={id}
        className={`input w-full ${mono ? 'font-mono text-[13px]' : ''}`}
        value={value}
        disabled={disabled}
        placeholder={placeholder}
        onChange={(event) => useIntegrationEditor.getState().change((doc) => (event.target.value === '' && !required ? deleteAt(doc, path) : setAt(doc, path, event.target.value)))}
      />
    </Labelled>
  )
}

/**
 * A text that may name fields in braces. The names come from a choice of the fields (and what the sign-in itself
 * hands over), never from memory; a name that is no field is said at once.
 */
function PlaceholderInput({ value, onChange, names, label, id }: { value: string; onChange: (value: string) => void; names: string[]; label: string; id?: string }) {
  const { t } = useTranslation()
  const unknown = placeholdersIn(value).filter((one) => !names.includes(one))
  return (
    <div className="min-w-0">
      <div className="flex gap-2 min-w-0">
        <input id={id} className="input flex-1 min-w-0 font-mono text-[13px]" value={value} aria-label={label} onChange={(event) => onChange(event.target.value)} />
        <select
          className="input w-auto max-w-[9rem] shrink-0"
          aria-label={t('integrationEditor.insertField', { label })}
          value=""
          onChange={(event) => event.target.value && onChange(value + `{${event.target.value}}`)}
        >
          <option value="">{t('integrationEditor.insert')}</option>
          {names.map((one) => (
            <option key={one} value={one}>{`{${one}}`}</option>
          ))}
        </select>
      </div>
      {unknown.length > 0 && (
        <p className="text-[12px] text-bad mt-1" role="alert">
          {t('integrationEditor.unknownField', { names: unknown.map((one) => `{${one}}`).join(', ') })}
        </p>
      )}
    </div>
  )
}

function PlaceholderAt({ path, label, help, names }: { path: CardPath; label: string; help?: string; names: string[] }) {
  const id = useId()
  const card = useIntegrationEditor((state) => state.card)
  const value = card ? asText(readAt(card, path)) : ''
  return (
    <Labelled label={label} help={help} htmlFor={id}>
      <PlaceholderInput id={id} value={value} names={names} label={label} onChange={(next) => useIntegrationEditor.getState().change((doc) => setAt(doc, path, next))} />
    </Labelled>
  )
}

function SelectAt({ path, label, help, options, fallback, drop, labelOf }: { path: CardPath; label: string; help?: string; options: string[]; fallback: string; drop?: string; labelOf?: (option: string) => string }) {
  const id = useId()
  const { t } = useTranslation()
  const card = useIntegrationEditor((state) => state.card)
  const value = (card && asText(readAt(card, path))) || fallback
  return (
    <Labelled label={label} help={help} htmlFor={id}>
      <Select
        id={id}
        value={value}
        options={options.map((one) => ({ value: one, label: labelOf ? labelOf(one) : t(`integrationEditor.option.${one}`) }))}
        onChange={(next) => useIntegrationEditor.getState().change((doc) => (drop !== undefined && next === drop ? deleteAt(doc, path) : setAt(doc, path, next)))}
      />
    </Labelled>
  )
}

// -- Basics ---------------------------------------------------------------------------------------------------------

function Basics() {
  const { t } = useTranslation()
  const card = useIntegrationEditor((state) => state.card)
  const saved = useIntegrationEditor((state) => state.short !== null)
  const logoId = useId()
  if (!card) return null
  const name = asText(readAt(card, ['name']))
  const short = asText(readAt(card, ['short']))
  return (
    <Section id="basics" title={t('integrationEditor.basics.title')} lead={t('integrationEditor.basics.lead')} parts={['name', 'short', 'logo', 'description', 'category']}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Labelled label={t('integrationEditor.basics.name')} htmlFor="ie-name">
          <input
            id="ie-name"
            className="input w-full"
            value={name}
            onChange={(event) =>
              useIntegrationEditor.getState().change((doc) => {
                setAt(doc, ['name'], event.target.value)
                // A new one takes its short name from the name until somebody writes one of their own.
                if (!saved && (short === '' || short === shortFrom(name))) setAt(doc, ['short'], shortFrom(event.target.value))
              })
            }
          />
        </Labelled>
        <Labelled label={t('integrationEditor.basics.short')} help={saved ? t('integrationEditor.basics.shortFixed') : t('integrationEditor.basics.shortHelp')} htmlFor="ie-short">
          <input
            id="ie-short"
            className="input w-full font-mono text-[13px]"
            value={short}
            disabled={saved}
            onChange={(event) => useIntegrationEditor.getState().change((doc) => setAt(doc, ['short'], event.target.value))}
          />
        </Labelled>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="min-w-0" id={logoId}>
          <IconPicker value={asText(readAt(card, ['logo']))} onChange={(next) => useIntegrationEditor.getState().change((doc) => (next ? setAt(doc, ['logo'], next) : deleteAt(doc, ['logo'])))} label={t('integrationEditor.basics.logo')} />
        </div>
        <SelectAt path={['category']} label={t('integrationEditor.basics.category')} options={CATEGORY_ORDER} fallback="other" drop="other" labelOf={(one) => t(`library.category.${one}`, { defaultValue: one })} />
      </div>
      <TextAt path={['description']} label={t('integrationEditor.basics.description')} />
    </Section>
  )
}

// -- Fields ---------------------------------------------------------------------------------------------------------

function FieldRow({ field, index, last }: { field: DefinedField; index: number; last: boolean }) {
  const { t } = useTranslation()
  const base = ['fields', index] as const
  const set = (key: keyof DefinedField, value: unknown) =>
    useIntegrationEditor.getState().change((doc) => (value === '' || value === false ? (key === 'name' || key === 'type' ? setAt(doc, [...base, key], value) : deleteAt(doc, [...base, key])) : setAt(doc, [...base, key], value)))
  const move = (to: number) =>
    useIntegrationEditor.getState().change((doc) => {
      const list = (doc.toJS() as { fields: unknown[] }).fields
      const [one] = list.splice(index, 1)
      list.splice(to, 0, one)
      setAt(doc, ['fields'], list)
    })
  const remove = () =>
    useIntegrationEditor.getState().change((doc) => {
      const list = (doc.toJS() as { fields: unknown[] }).fields.filter((_, at) => at !== index)
      if (list.length) setAt(doc, ['fields'], list)
      else deleteAt(doc, ['fields'])
    })
  return (
    <li className="rounded-xl border border-line p-3 grid gap-2 min-w-0" data-testid="integration-field">
      <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,9rem)_minmax(0,1.4fr)]">
        <input className="input font-mono text-[13px]" aria-label={t('integrationEditor.fields.name')} placeholder={t('integrationEditor.fields.name')} value={field.name} onChange={(event) => set('name', event.target.value)} />
        <Select
          value={field.type}
          options={FIELD_TYPES.map((one) => ({ value: one, label: t(`integrationEditor.fieldType.${one}`) }))}
          onChange={(next) => set('type', next)}
        />
        <input className="input" aria-label={t('integrationEditor.fields.label')} placeholder={t('integrationEditor.fields.label')} value={field.label} onChange={(event) => set('label', event.target.value)} />
      </div>
      <input className="input" aria-label={t('integrationEditor.fields.help')} placeholder={t('integrationEditor.fields.help')} value={field.help} onChange={(event) => set('help', event.target.value)} />
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2 text-sm mr-auto">
          <input type="checkbox" checked={field.required} onChange={(event) => set('required', event.target.checked)} />
          {t('integrationEditor.fields.required')}
        </label>
        <button type="button" className="btn btn-icon btn-flat" aria-label={t('integrationEditor.fields.up')} title={t('integrationEditor.fields.up')} disabled={index === 0} onClick={() => move(index - 1)}>
          <ArrowUp size={15} />
        </button>
        <button type="button" className="btn btn-icon btn-flat" aria-label={t('integrationEditor.fields.down')} title={t('integrationEditor.fields.down')} disabled={last} onClick={() => move(index + 1)}>
          <ArrowDown size={15} />
        </button>
        <button type="button" className="btn btn-icon btn-flat btn-danger" aria-label={t('integrationEditor.fields.remove')} title={t('integrationEditor.fields.remove')} onClick={remove}>
          <Trash2 size={15} />
        </button>
      </div>
    </li>
  )
}

function Fields() {
  const { t } = useTranslation()
  const card = useIntegrationEditor((state) => state.card)
  if (!card) return null
  const fields = fieldsOf(card)
  const add = () =>
    useIntegrationEditor.getState().change((doc) => {
      const list = ((doc.toJS() as { fields?: unknown[] }).fields ?? []).slice()
      const name = freeName(fields.map((one) => one.name))
      list.push({ name, type: 'text', label: name })
      setAt(doc, ['fields'], list)
    })
  return (
    <Section id="fields" title={t('integrationEditor.fields.title')} lead={t('integrationEditor.fields.lead')} parts={['fields']}>
      {/* The address comes with every integration and is not in the definition. */}
      <div className="rounded-xl border border-line px-3 py-2 flex flex-wrap items-center gap-2 text-sm bg-surface" data-testid="integration-address-field">
        <span className="font-mono text-[13px]">url</span>
        <span className="text-muted">{t('integrationEditor.fields.addressName')}</span>
        <span className="chip !py-0 ml-auto">{t('integrationEditor.fields.fixed')}</span>
      </div>
      {fields.length > 0 && (
        <ul className="grid gap-2">
          {fields.map((one, index) => (
            <FieldRow key={index} field={one} index={index} last={index === fields.length - 1} />
          ))}
        </ul>
      )}
      <div>
        <button type="button" className="btn" onClick={add} disabled={fields.length >= MAX_FIELDS}>
          <Plus size={15} /> {t('integrationEditor.fields.add')}
        </button>
        {fields.length >= MAX_FIELDS && <span className="text-[12px] text-muted ml-2">{t('integrationEditor.fields.most', { count: MAX_FIELDS })}</span>}
      </div>
    </Section>
  )
}

// -- Sign-in --------------------------------------------------------------------------------------------------------

function BodyRows({ names }: { names: string[] }) {
  const { t } = useTranslation()
  const card = useIntegrationEditor((state) => state.card)
  if (!card) return null
  const raw = readAt(card, ['auth', 'body'])
  const rows = raw && typeof raw === 'object' && !Array.isArray(raw) ? Object.entries(raw as Record<string, unknown>).map(([key, value]) => [key, asText(value)] as const) : []
  const write = (next: (readonly [string, string])[]) => useIntegrationEditor.getState().change((doc) => setAt(doc, ['auth', 'body'], Object.fromEntries(next)))
  return (
    <div className="grid gap-2" role="group" aria-label={t('integrationEditor.auth.body')}>
      <div className="text-xs font-medium text-muted">{t('integrationEditor.auth.body')}</div>
      {rows.map(([key, value], index) => (
        <div key={index} className="grid gap-2 sm:grid-cols-[minmax(0,10rem)_minmax(0,1fr)_auto] items-start">
          <input className="input font-mono text-[13px]" aria-label={t('integrationEditor.auth.bodyKey')} value={key} onChange={(event) => write(rows.map((row, at) => (at === index ? ([event.target.value, row[1]] as const) : row)))} />
          <PlaceholderInput value={value} names={names} label={t('integrationEditor.auth.bodyValue', { key })} onChange={(next) => write(rows.map((row, at) => (at === index ? ([row[0], next] as const) : row)))} />
          <button type="button" className="btn btn-icon btn-flat btn-danger" aria-label={t('integrationEditor.auth.bodyRemove')} onClick={() => write(rows.filter((_, at) => at !== index))}>
            <Trash2 size={15} />
          </button>
        </div>
      ))}
      <div>
        <button type="button" className="btn" onClick={() => write([...rows, [freeName(rows.map((row) => row[0]), 'field'), ''] as const])}>
          <Plus size={15} /> {t('integrationEditor.auth.bodyAdd')}
        </button>
      </div>
    </div>
  )
}

function SignIn() {
  const { t } = useTranslation()
  const card = useIntegrationEditor((state) => state.card)
  const typeId = useId()
  if (!card) return null
  const names = fieldsOf(card)
    .map((one) => one.name)
    .filter(Boolean)
  const { type } = authOf(card)
  const from = asText(readAt(card, ['auth', 'ticket', 'from'])) || 'json'
  const passAs = asText(readAt(card, ['auth', 'pass', 'as'])) || 'header'
  const afterSignIn = [...names, 'ticket']
  return (
    <Section id="auth" title={t('integrationEditor.auth.title')} lead={t('integrationEditor.auth.lead')} parts={['auth']}>
      <Labelled label={t('integrationEditor.auth.type')} htmlFor={typeId}>
        <Select
          id={typeId}
          value={type}
          options={AUTH_TYPES.map((one) => ({ value: one, label: t(`integrationEditor.authType.${one}`) }))}
          onChange={(next) => useIntegrationEditor.getState().change((doc) => setAt(doc, ['auth'], authDefaults(next as AuthType, names)))}
        />
      </Labelled>
      <p className="text-[13px] text-muted break-words hyphens-auto" data-testid="integration-auth-explained">
        {t(`integrationEditor.authExplained.${type}`)}
      </p>
      {type === 'header' && (
        <div className="grid gap-3 sm:grid-cols-2">
          <TextAt path={['auth', 'header']} label={t('integrationEditor.auth.header')} mono required />
          <PlaceholderAt path={['auth', 'value']} label={t('integrationEditor.auth.headerValue')} help={t('integrationEditor.auth.valueHelp')} names={names} />
        </div>
      )}
      {type === 'basic' && (
        <div className="grid gap-3 sm:grid-cols-2">
          <PlaceholderAt path={['auth', 'user']} label={t('integrationEditor.auth.user')} names={names} />
          <PlaceholderAt path={['auth', 'password']} label={t('integrationEditor.auth.password')} names={names} />
        </div>
      )}
      {type === 'query' && (
        <div className="grid gap-3 sm:grid-cols-2">
          <TextAt path={['auth', 'param']} label={t('integrationEditor.auth.param')} mono required />
          <PlaceholderAt path={['auth', 'value']} label={t('integrationEditor.auth.queryValue')} help={t('integrationEditor.auth.queryHelp')} names={names} />
        </div>
      )}
      {type === 'session' && (
        <div className="grid gap-3">
          <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,10rem)]">
            <TextAt path={['auth', 'login']} label={t('integrationEditor.auth.login')} help={t('integrationEditor.auth.loginHelp')} mono required />
            <SelectAt path={['auth', 'send']} label={t('integrationEditor.auth.send')} options={['json', 'form']} fallback="json" />
          </div>
          <BodyRows names={names} />
          <div className="grid gap-3 sm:grid-cols-2">
            <SelectAt path={['auth', 'ticket', 'from']} label={t('integrationEditor.auth.ticketFrom')} help={t('integrationEditor.auth.ticketHelp')} options={['json', 'cookie']} fallback="json" />
            {from === 'cookie' ? (
              <TextAt path={['auth', 'ticket', 'name']} label={t('integrationEditor.auth.cookieName')} mono required />
            ) : (
              <TextAt path={['auth', 'ticket', 'at']} label={t('integrationEditor.auth.ticketAt')} help={t('integrationEditor.auth.ticketAtHelp')} mono required />
            )}
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <SelectAt path={['auth', 'pass', 'as']} label={t('integrationEditor.auth.passAs')} help={t('integrationEditor.auth.passHelp')} options={['header', 'cookie', 'query']} fallback="header" />
            {passAs === 'cookie' && <TextAt path={['auth', 'pass', 'name']} label={t('integrationEditor.auth.cookieName')} mono />}
            {passAs === 'query' && <TextAt path={['auth', 'pass', 'param']} label={t('integrationEditor.auth.param')} mono required />}
            {passAs === 'header' && <TextAt path={['auth', 'pass', 'header']} label={t('integrationEditor.auth.header')} mono required />}
          </div>
          {passAs !== 'cookie' && <PlaceholderAt path={['auth', 'pass', 'value']} label={t('integrationEditor.auth.passValue')} help={t('integrationEditor.auth.passValueHelp')} names={afterSignIn} />}
        </div>
      )}
    </Section>
  )
}

// -- Test address ---------------------------------------------------------------------------------------------------

function TestAddress() {
  const { t } = useTranslation()
  return (
    <Section id="test" title={t('integrationEditor.test.title')} lead={t('integrationEditor.test.lead')} parts={['test', 'test_expects']}>
      <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,14rem)]">
        <TextAt path={['test']} label={t('integrationEditor.test.path')} help={t('integrationEditor.test.pathHelp')} mono required placeholder="/api/status" />
        <SelectAt path={['test_expects']} label={t('integrationEditor.test.expects')} options={['any', 'json']} fallback="any" drop="any" />
      </div>
    </Section>
  )
}

// -- What nexdeck can ask --------------------------------------------------------------------------------------------

function Reads() {
  const { t } = useTranslation()
  const card = useIntegrationEditor((state) => state.card)
  if (!card) return null
  const reads = readsOf(card)
  const write = (next: { path: string; label: string }[]) =>
    useIntegrationEditor.getState().change((doc) => (next.length ? setAt(doc, ['reads'], next) : deleteAt(doc, ['reads'])))
  return (
    <Section id="reads" title={t('integrationEditor.reads.title')} lead={t('integrationEditor.reads.lead')} parts={['reads']}>
      {reads.map((one, index) => (
        <div key={index} className="grid gap-2 sm:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_auto] items-center" data-testid="integration-read">
          <input className="input font-mono text-[13px]" aria-label={t('integrationEditor.reads.path')} placeholder="/api/v1/items?limit=10" value={one.path} onChange={(event) => write(reads.map((row, at) => (at === index ? { ...row, path: event.target.value } : row)))} />
          <input className="input" aria-label={t('integrationEditor.reads.label')} placeholder={t('integrationEditor.reads.label')} value={one.label} onChange={(event) => write(reads.map((row, at) => (at === index ? { ...row, label: event.target.value } : row)))} />
          <button type="button" className="btn btn-icon btn-flat btn-danger" aria-label={t('integrationEditor.reads.remove')} onClick={() => write(reads.filter((_, at) => at !== index))}>
            <Trash2 size={15} />
          </button>
        </div>
      ))}
      <div>
        <button type="button" className="btn" disabled={reads.length >= MAX_READS} onClick={() => write([...reads, { path: '/', label: '' }])}>
          <Plus size={15} /> {t('integrationEditor.reads.add')}
        </button>
        {reads.length >= MAX_READS && <span className="text-[12px] text-muted ml-2">{t('integrationEditor.reads.most', { count: MAX_READS })}</span>}
      </div>
    </Section>
  )
}

// -- Extras (KARTEN-4) ----------------------------------------------------------------------------------------------

/** Where the version stands: the path to ask and the place in the answer. Both or none; one alone is the server's to say. */
function VersionAt() {
  const { t } = useTranslation()
  const pathId = useId()
  const atId = useId()
  const card = useIntegrationEditor((state) => state.card)
  const raw = card ? readAt(card, ['version']) : undefined
  const place = raw && typeof raw === 'object' && !Array.isArray(raw) ? (raw as Record<string, unknown>) : {}
  const path = asText(place.path)
  const at = asText(place.at)
  const write = (next: { path: string; at: string }) =>
    useIntegrationEditor.getState().change((doc) => (next.path === '' && next.at === '' ? deleteAt(doc, ['version']) : setAt(doc, ['version'], next)))
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <Labelled label={t('integrationEditor.extras.versionPath')} help={t('integrationEditor.extras.versionPathHelp')} htmlFor={pathId}>
        <input id={pathId} className="input w-full font-mono text-[13px]" value={path} placeholder="/api/v1/status" onChange={(event) => write({ path: event.target.value, at })} />
      </Labelled>
      <Labelled label={t('integrationEditor.extras.versionAt')} help={t('integrationEditor.extras.versionAtHelp')} htmlFor={atId}>
        <input id={atId} className="input w-full font-mono text-[13px]" value={at} placeholder="version" onChange={(event) => write({ path, at: event.target.value })} />
      </Labelled>
    </div>
  )
}

function Extras() {
  const { t } = useTranslation()
  return (
    <Section id="extras" title={t('integrationEditor.extras.title')} lead={t('integrationEditor.extras.lead')} parts={['check', 'version', 'github']}>
      <TextAt path={['check']} label={t('integrationEditor.extras.check')} help={t('integrationEditor.extras.checkHelp')} mono placeholder="/healthz" />
      <VersionAt />
      <TextAt path={['github']} label={t('integrationEditor.extras.github')} help={t('integrationEditor.extras.githubHelp')} mono placeholder="owner/name" />
    </Section>
  )
}

// -- What whoever sets it up sees ------------------------------------------------------------------------------------

/** The form for adding a connection of this kind, as the definition will make it (the address first, then the fields). */
export function SetupPreview() {
  const { t } = useTranslation()
  const card = useIntegrationEditor((state) => state.card ?? state.lastValid)
  if (!card) return null
  const name = asText(readAt(card, ['name'])) || t('integrationEditor.preview.untitled')
  const fields = fieldsOf(card)
  return (
    <aside className="glass rounded-2xl p-4 grid gap-3 content-start min-w-0" aria-label={t('integrationEditor.preview.title')} data-testid="integration-preview">
      <div>
        <h2 className="font-semibold text-[15px]">{t('integrationEditor.preview.title')}</h2>
        <p className="text-[13px] text-muted">{t('integrationEditor.preview.lead', { name })}</p>
      </div>
      <PreviewField label={t('integrationEditor.fields.addressName')} required type="text" />
      {fields.map((one, index) => (
        <PreviewField key={index} label={one.label || one.name} help={one.help} required={one.required} type={one.type} />
      ))}
      <PreviewField label={t('integrationEditor.preview.tls')} type="switch" />
    </aside>
  )
}

function PreviewField({ label, help, required, type }: { label: string; help?: string; required?: boolean; type: string }) {
  return (
    <div className="min-w-0">
      <div className="text-xs font-medium text-muted mb-1 break-words">
        {label}
        {required && <span className="text-bad ml-0.5">*</span>}
      </div>
      {type === 'switch' ? (
        <span className="inline-block w-10 h-6 rounded-full bg-[color-mix(in_srgb,var(--nd-text)_18%,transparent)]" aria-hidden="true" />
      ) : (
        <input className="input w-full" disabled type={type === 'secret' ? 'password' : type === 'number' ? 'number' : 'text'} aria-label={label} />
      )}
      {help && <p className="text-[12px] text-faint mt-1 break-words">{help}</p>}
    </div>
  )
}

export function FormView() {
  return (
    <div className="grid gap-4 min-w-0" data-testid="integration-form">
      <Basics />
      <Fields />
      <SignIn />
      <TestAddress />
      <Reads />
      <Extras />
    </div>
  )
}
