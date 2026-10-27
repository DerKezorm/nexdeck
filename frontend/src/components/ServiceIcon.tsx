import {
  Activity,
  AlarmClock,
  Archive,
  BarChart3,
  Bell,
  Book,
  BookOpen,
  Box,
  Calendar,
  CalendarDays,
  Camera,
  Check,
  ChevronsUpDown,
  Clapperboard,
  Clock,
  Cloud,
  CloudSun,
  Cpu,
  Database,
  Download,
  Film,
  Flame,
  Gauge,
  Globe,
  HardDrive,
  Home,
  Image,
  Lamp,
  Laptop,
  LayoutDashboard,
  Link,
  Lock,
  Mail,
  MessageSquare,
  Minus,
  Monitor,
  Music,
  Network,
  Pause,
  Play,
  Plus,
  Power,
  Printer,
  Radio,
  RefreshCw,
  RotateCw,
  Router,
  Rss,
  Search,
  Server,
  Shield,
  ShieldCheck,
  Speaker,
  Square,
  Sun,
  Thermometer,
  Trash2,
  Tv,
  Wifi,
  Wrench,
  X,
  Zap,
  type LucideProps,
} from 'lucide-react'
import { useState, type ComponentType } from 'react'

import { iconUrl } from '../lib/format'
import { judge, useGround, verdictFor } from '../lib/ground'

interface Props {
  icon?: string | null
  size?: number
  className?: string
  /**
   * The service's own logo, asked of the server when there is no icon or no
   * collection has the one named (`/api/v1/widgets/{id}/favicon`). Tried
   * once, then the grey box.
   */
  fallback?: string | null
}

/**
 * The symbols available as ``lucide:<name>``. A fixed set on purpose: the
 * full icon library would put a megabyte into the first load for the handful
 * a board uses. Unknown names fall back to a box.
 */
export const SYMBOLS: Record<string, ComponentType<LucideProps>> = {
  activity: Activity,
  'alarm-clock': AlarmClock,
  archive: Archive,
  'bar-chart-3': BarChart3,
  bell: Bell,
  book: Book,
  'book-open': BookOpen,
  box: Box,
  calendar: Calendar,
  'calendar-days': CalendarDays,
  camera: Camera,
  check: Check,
  'chevrons-up-down': ChevronsUpDown,
  clapperboard: Clapperboard,
  clock: Clock,
  cloud: Cloud,
  'cloud-sun': CloudSun,
  cpu: Cpu,
  database: Database,
  download: Download,
  film: Film,
  flame: Flame,
  gauge: Gauge,
  globe: Globe,
  'hard-drive': HardDrive,
  home: Home,
  image: Image,
  lamp: Lamp,
  laptop: Laptop,
  'layout-dashboard': LayoutDashboard,
  link: Link,
  lock: Lock,
  mail: Mail,
  'message-square': MessageSquare,
  minus: Minus,
  monitor: Monitor,
  music: Music,
  network: Network,
  pause: Pause,
  play: Play,
  plus: Plus,
  power: Power,
  printer: Printer,
  radio: Radio,
  'refresh-cw': RefreshCw,
  'rotate-cw': RotateCw,
  router: Router,
  rss: Rss,
  search: Search,
  server: Server,
  shield: Shield,
  'shield-check': ShieldCheck,
  speaker: Speaker,
  square: Square,
  sun: Sun,
  thermometer: Thermometer,
  'trash-2': Trash2,
  tv: Tv,
  wifi: Wifi,
  wrench: Wrench,
  x: X,
  zap: Zap,
}

/**
 * A service logo (dashboard-icons name, URL or upload) or, with the
 * ``lucide:`` prefix, a symbol from the set above.
 */
export function ServiceIcon({ icon, size = 20, className = '', fallback = null }: Props) {
  // Remember which address failed, not that one did: while a name is being
  // typed, "r" and "ra" fail and "radarr" must still get its chance.
  const [failedUrl, setFailedUrl] = useState<string | null>(null)
  const [failedFallback, setFailedFallback] = useState<string | null>(null)
  const ground = useGround((state) => state.mode)
  // Set once a logo turned out to vanish on this ground; it then asks for its variant.
  const [, looked] = useState(0)
  if (icon && icon.startsWith('lucide:')) {
    return <LucideByName name={icon.slice(7)} size={size} className={className} />
  }
  // A drawn symbol written without the prefix. Nothing is fetched for it, and
  // the two the bookmarks card shipped with used to answer 404 on every load.
  if (icon && icon in SYMBOLS) {
    return <LucideByName name={icon} size={size} className={className} />
  }
  // A name the server serves can have a variant for the ground; an address or an upload cannot.
  const plain = iconUrl(icon)
  const named = Boolean(plain && icon && !/^(https?:|\/|data:)/.test(icon))
  const own = named && plain && verdictFor(plain, ground) ? iconUrl(icon, ground) : plain
  // Without an icon, or with one nobody has, the service's own logo; after that, the box.
  const fromService = Boolean(fallback) && (!own || failedUrl === own) && failedFallback !== fallback
  const url = fromService ? fallback : own
  if (!url || (!fromService && failedUrl === url)) {
    return <Box size={size} className={`${className} text-muted`} aria-hidden="true" />
  }
  return (
    <img
      src={url}
      width={size}
      height={size}
      alt=""
      className={`${className} object-contain`}
      style={{ width: size, height: size }}
      loading="lazy"
      onLoad={(event) => {
        if (!fromService && named && plain && url === plain && verdictFor(plain, ground) === undefined && judge(event.currentTarget, plain, ground)) looked((n) => n + 1)
      }}
      onError={() => (fromService ? setFailedFallback(url) : setFailedUrl(url))}
    />
  )
}

export function LucideByName({ name, size = 16, className = '' }: { name: string; size?: number; className?: string }) {
  const Symbol = SYMBOLS[name] ?? Box
  return <Symbol size={size} className={className} aria-hidden="true" />
}
