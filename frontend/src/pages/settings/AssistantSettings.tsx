import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { ApiError, get, post, put } from '../../api/client'
import { Field, PasswordInput, Select, Switch, Toast } from '../../components/ui'
import { useAssistant } from '../../lib/assistant'
import { useAssistantTexts } from '../../lib/assistantTexts'
import { SettingsCard } from './SettingsCard'

const SAID = ['auth', 'rate_limited', 'unreachable', 'model', 'provider', 'no_list']

interface Model {
  id: string
  name: string
}

interface Stored {
  provider: 'off' | 'anthropic' | 'openai'
  base_url: string
  model: string
  has_key: boolean
  ready: boolean
  leaves_the_house: boolean
  /** A model of the OpenAI form that understands pictures (the skin editor shows it its stage). */
  vision?: boolean
}

/**
 * The assistant's provider (roadmap M3), chosen once for the installation.
 *
 * Off by default. Claude goes out to Anthropic; an OpenAI-shaped service can
 * be Ollama or LM Studio on the home network, and then nothing leaves the
 * house. The key is written, never read back: the field only says one is set.
 */
export function AssistantSettings() {
  const ready = useAssistantTexts()
  return ready ? <Setting /> : null
}

function Setting() {
  const { t } = useTranslation()
  const saved = useQuery({ queryKey: ['assistant-setting'], queryFn: () => get<Stored>('/settings/assistant') })
  const reload = useAssistant((s) => s.load)
  const [provider, setProvider] = useState<Stored['provider']>('off')
  const [address, setAddress] = useState('')
  const [model, setModel] = useState('')
  const [key, setKey] = useState('')
  const [hasKey, setHasKey] = useState(false)
  const [vision, setVision] = useState(false)
  const [busy, setBusy] = useState(false)
  const [models, setModels] = useState<Model[] | null>(null)
  const [toast, setToast] = useState<{ text: string; level: 'ok' | 'error' } | null>(null)
  useEffect(() => {
    if (!saved.data) return
    setProvider(saved.data.provider)
    setAddress(saved.data.base_url)
    setModel(saved.data.model)
    setHasKey(saved.data.has_key)
    setVision(saved.data.vision === true)
  }, [saved.data])

  // What the provider said, in the reader's words where nexdeck has them.
  const report = (failure: unknown) => {
    const code = failure instanceof ApiError ? failure.code : ''
    const text = SAID.includes(code) ? t(`assistant.error.${code}`) : failure instanceof ApiError ? failure.message : t('errors.network')
    setToast({ text, level: 'error' })
  }

  /** The models the service offers, asked with what is typed: the list is also the proof that key and address work. */
  const loadModels = async (quiet = false) => {
    try {
      setModels(await post<Model[]>('/settings/assistant/models', { provider, base_url: address, ...(key.trim() ? { key: key.trim() } : {}) }))
    } catch (failure) {
      setModels(null)
      if (!quiet) report(failure)
    }
  }
  // Claude with a stored key: the list is there when the page opens, it costs nothing to ask.
  const firstLoad = saved.data?.provider === 'anthropic' && saved.data.has_key
  useEffect(() => {
    if (firstLoad) void post<Model[]>('/settings/assistant/models', { provider: 'anthropic' }).then(setModels).catch(() => undefined)
  }, [firstLoad])

  const store = async (dropKey = false): Promise<Stored | null> => {
    try {
      const answer = await put<Stored>('/settings/assistant', {
        provider,
        base_url: address,
        model,
        // Only for the OpenAI form: Claude always sees pictures, and the server keeps what was stored.
        ...(provider === 'openai' ? { vision } : {}),
        ...(dropKey ? { key: '' } : key.trim() ? { key: key.trim() } : {}),
      })
      setKey('')
      setHasKey(answer.has_key)
      setModel(answer.model)
      await saved.refetch()
      await reload()
      return answer
    } catch (failure) {
      report(failure)
      return null
    }
  }

  const test = async () => {
    setBusy(true)
    try {
      if (!(await store())) return
      const answer = await post<{ model: string; answer: string }>('/settings/assistant/test')
      setToast({ text: t('settings.assistant.testOk', { model: answer.model }), level: 'ok' })
    } catch (failure) {
      report(failure)
    } finally {
      setBusy(false)
    }
  }

  // Whether questions leave the house, as the server judges the address; a
  // changed address is judged once it is saved.
  const sameAddress = saved.data?.provider === 'openai' && saved.data.base_url === address.trim().replace(/\/+$/, '')
  const where = provider === 'anthropic' ? 'leaves' : sameAddress ? (saved.data?.leaves_the_house ? 'leaves' : 'stays') : 'unknown'

  return (
    <>
      <SettingsCard title={t('settings.assistant.title')} description={t('settings.assistant.help')}>
        <Field label={t('settings.assistant.provider')} htmlFor="assistant-provider">
          <Select
            id="assistant-provider"
            value={provider}
            onChange={(value) => {
              setProvider(value as Stored['provider'])
              setModels(null)
            }}
            options={[
              { value: 'off', label: t('settings.assistant.off') },
              { value: 'anthropic', label: t('settings.assistant.anthropic') },
              { value: 'openai', label: t('settings.assistant.openai') },
            ]}
          />
        </Field>
        {provider === 'openai' && (
          <Field label={t('settings.assistant.address')} help={t('settings.assistant.addressHelp')}>
            <input
              className="input font-mono text-[12.5px]"
              value={address}
              placeholder="http://ollama:11434/v1"
              onChange={(event) => {
                setAddress(event.target.value)
                setModels(null)
              }}
            />
          </Field>
        )}
        {provider === 'openai' && <Switch checked={vision} onChange={setVision} label={t('settings.assistant.vision')} description={t('settings.assistant.visionHelp')} />}
        {provider !== 'off' && (
          <>
            <Field label={t('settings.assistant.key')} help={provider === 'openai' ? t('settings.assistant.keyHelpOpenai') : undefined} htmlFor="assistant-key">
              <PasswordInput id="assistant-key" value={key} onChange={setKey} autoComplete="new-password" placeholder={hasKey ? t('settings.assistant.keyKept') : ''} />
            </Field>
            {hasKey && (
              <button type="button" className="btn btn-flat -mt-1 mb-3 text-[12.5px]" onClick={() => void store(true)}>
                {t('settings.assistant.removeKey')}
              </button>
            )}
            <Field label={t('settings.assistant.model')} help={provider === 'anthropic' ? t('settings.assistant.modelHelpClaude') : t('settings.assistant.modelHelpOpenai')} htmlFor="assistant-model">
              <div className="flex gap-2">
                {models ? (
                  <Select
                    id="assistant-model"
                    className="flex-1"
                    value={model}
                    onChange={setModel}
                    options={[
                      // What is stored stays choosable, even when the service no longer lists it.
                      ...(models.some((entry) => entry.id === model) ? [] : [{ value: model, label: model || '…' }]),
                      ...models.map((entry) => ({ value: entry.id, label: entry.name === entry.id ? entry.id : `${entry.name} (${entry.id})` })),
                    ]}
                  />
                ) : (
                  <input
                    id="assistant-model"
                    className="input flex-1 font-mono text-[12.5px]"
                    value={model}
                    placeholder={provider === 'anthropic' ? 'claude-sonnet-5-5' : 'qwen3:14b'}
                    onChange={(event) => setModel(event.target.value)}
                  />
                )}
                <button type="button" className="btn" onClick={() => void loadModels()}>
                  {t('settings.assistant.loadModels')}
                </button>
              </div>
            </Field>
            <p className={`mb-3 rounded-xl border p-3 text-[12.5px] ${where === 'leaves' ? 'border-warn/50' : 'border-line'}`} data-testid="assistant-where">
              {t(`settings.assistant.${where}`)}
            </p>
          </>
        )}
        <p className="mb-3 text-[12.5px] text-muted">{t('settings.assistant.who')}</p>
        <div className="flex flex-wrap items-center gap-2">
          {provider !== 'off' && (
            <button type="button" className="btn" disabled={busy} onClick={() => void test()}>
              {t('settings.assistant.test')}
            </button>
          )}
          {provider === 'anthropic' && <span className="text-[11.5px] text-faint">{t('settings.assistant.testCosts')}</span>}
          <button type="button" className="btn btn-accent ml-auto" disabled={busy} onClick={() => void store().then((answer) => answer && setToast({ text: t('common.saved'), level: 'ok' }))}>
            {t('common.save')}
          </button>
        </div>
      </SettingsCard>
      {toast && (
        <Toast level={toast.level} onClose={() => setToast(null)}>
          {toast.text}
        </Toast>
      )}
    </>
  )
}
