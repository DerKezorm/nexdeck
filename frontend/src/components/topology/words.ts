import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'

import { formatBits, formatSpeed, portName, type PortRef, type TopoLink, type TopoNode } from '../../lib/topology'

/** Numbers and facts of the topology page in the reader's language. */
export function useWords() {
  const { t, i18n } = useTranslation()
  const language = i18n.language
  return useMemo(() => {
    const ago = (seconds: number | null | undefined): string => {
      if (seconds === null || seconds === undefined) return '–'
      const s = Math.max(0, Math.round(seconds))
      if (s < 120) return t('topology.ago.seconds', { count: s })
      if (s < 7200) return t('topology.ago.minutes', { count: Math.round(s / 60) })
      if (s < 172800) return t('topology.ago.hours', { count: Math.round(s / 3600) })
      return t('topology.ago.days', { count: Math.round(s / 86400) })
    }
    const span = (seconds: number): string => {
      if (seconds < 7200) return t('topology.span.minutes', { count: Math.max(1, Math.round(seconds / 60)) })
      if (seconds < 172800) return t('topology.span.hours', { count: Math.round(seconds / 3600) })
      return t('topology.span.days', { count: Math.round(seconds / 86400) })
    }
    const fact = (key: string, value: string | number): string => {
      if (key === 'uptime' && typeof value === 'number') return span(value)
      if (key === 'last_seen_ago' && typeof value === 'number') return ago(value)
      if ((key === 'cpu' || key === 'memory') && typeof value === 'number') return `${value} %`
      if (key === 'temperature' && typeof value === 'number') return `${value} °C`
      return String(value)
    }
    const port = (ref: PortRef | undefined, kind?: TopoLink['kind']): string => {
      if (kind === 'wifi') return t('topology.radio')
      if (ref?.name === 'WAN') return ref.index !== null ? `${t('topology.port')} ${ref.index} · WAN` : 'WAN'
      return portName(ref, t('topology.port'))
    }
    const sub = (node: TopoNode, wired: number): string => {
      if (node.status === 'offline') return `${node.model} · ${t('topology.offline')}`
      if (node.kind === 'ap') return `${node.model} · ${t('topology.wifiClients', { count: node.wifi_clients ?? 0 })}`
      if ((node.kind === 'switch' || node.kind === 'gateway') && wired) return `${node.model} · ${t('topology.wiredCount', { count: wired })}`
      return node.model
    }
    return {
      bits: (value: number | null | undefined) => formatBits(value, language),
      speed: (value: number | null | undefined) => formatSpeed(value, language),
      share: (value: number | null) => (value === null ? '–' : value < 0.01 ? '< 1 %' : `${Math.round(value * 100)} %`),
      ago,
      span,
      fact,
      port,
      sub,
    }
  }, [t, language])
}

export type Words = ReturnType<typeof useWords>
