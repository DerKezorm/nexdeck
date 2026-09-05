/**
 * The step-by-step guides next to the fields of a notification channel.
 *
 * Only where the setting up happens outside nexdeck and takes more than two
 * moves. The steps themselves are texts under ``channels.guide.<kind>.<step>``;
 * here stands only which steps a service has and where they lead.
 */

export interface GuideStep {
  /** Key under ``channels.guide.<kind>.`` */
  key: string
  links?: { href: string; label: string }[]
}

export const GUIDES: Record<string, GuideStep[]> = {
  telegram: [
    { key: 'account', links: [{ href: 'https://web.telegram.org', label: 'web.telegram.org' }] },
    { key: 'botfather', links: [{ href: 'https://t.me/BotFather', label: '@BotFather' }] },
    { key: 'token' },
    { key: 'chat', links: [{ href: 'https://t.me/userinfobot', label: '@userinfobot' }] },
  ],
  discord: [
    { key: 'server' },
    { key: 'webhook' },
    { key: 'paste' },
  ],
  slack: [
    { key: 'app', links: [{ href: 'https://api.slack.com/apps', label: 'api.slack.com/apps' }] },
    { key: 'webhook' },
    { key: 'paste' },
  ],
  ntfy: [
    { key: 'server', links: [{ href: 'https://ntfy.sh', label: 'ntfy.sh' }] },
    { key: 'topic' },
    { key: 'subscribe' },
  ],
  gotify: [
    { key: 'server', links: [{ href: 'https://gotify.net', label: 'gotify.net' }] },
    { key: 'app' },
    { key: 'token' },
  ],
  apprise: [
    { key: 'urls', links: [{ href: 'https://github.com/caronc/apprise/wiki', label: 'Apprise wiki' }] },
    { key: 'paste' },
  ],
  email: [
    { key: 'server' },
    { key: 'addresses' },
  ],
}

/** Which logo stands for a channel kind. Slugs of the icon collections. */
export const KIND_ICONS: Record<string, string> = {
  telegram: 'telegram',
  email: 'lucide:mail',
  webpush: 'lucide:bell-ring',
  ntfy: 'ntfy',
  gotify: 'gotify',
  discord: 'discord',
  slack: 'slack',
  apprise: 'apprise',
}

export function hasGuide(kind: string): boolean {
  return kind in GUIDES
}
