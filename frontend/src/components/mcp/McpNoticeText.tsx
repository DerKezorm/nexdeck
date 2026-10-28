import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import type { Notice } from '../../api/types'
import { noticeFacts, noticeWords, requestIdOf } from '../../lib/mcp'
import { useMcpTexts } from '../../lib/mcpTexts'
import { useRequest } from './RequestParts'

/**
 * The title and body of a notice about MCP, in the language on screen.
 *
 * The server writes these notices in English, because a channel (push, mail)
 * gets the same lines; here they are said again from the fields it sends with
 * them. Until the words are loaded, and for a notice without fields, the
 * server's lines stand.
 */
export default function McpNoticeText({ notice, render }: { notice: Notice; render: (title: string, body: string) => ReactNode }) {
  const { t } = useTranslation()
  const ready = useMcpTexts()
  // Only a notice from before the fields were sent asks the server; the query is the one Allow and Decline use.
  const id = notice.facts || notice.event !== 'mcp_request' ? null : requestIdOf(notice.link)
  const request = useRequest(id)
  const facts = ready ? noticeFacts(notice, request.data) : null
  if (!facts) return <>{render(notice.title, notice.body)}</>
  const words = noticeWords(t, facts)
  return <>{render(words.title, words.body ?? notice.body)}</>
}
