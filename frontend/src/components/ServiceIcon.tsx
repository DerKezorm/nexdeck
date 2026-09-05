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
  Monitor,
  Music,
  Network,
  Pause,
  Play,
  Power,
  Printer,
  Radio,
  RotateCw,
  Router,
  Rss,
  Search,
  Server,
  Shield,
  ShieldCheck,
  Square,
  Sun,
  Thermometer,
  Tv,
  Wifi,
  Wrench,
  X,
  Zap,
  type LucideProps,
} from 'lucide-react'
import { useState, type ComponentType } from 'react'

import { iconUrl } from '../lib/format'

interface Props {
  icon?: string | null
  size?: number
  className?: string
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
  monitor: Monitor,
  music: Music,
  network: Network,
  pause: Pause,
  play: Play,
  power: Power,
  printer: Printer,
  radio: Radio,
  'rotate-cw': RotateCw,
  router: Router,
  rss: Rss,
  search: Search,
  server: Server,
  shield: Shield,
  'shield-check': ShieldCheck,
  square: Square,
  sun: Sun,
  thermometer: Thermometer,
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
export function ServiceIcon({ icon, size = 20, className = '' }: Props) {
  // Remember which address failed, not that one did: while a name is being
  // typed, "r" and "ra" fail and "radarr" must still get its chance.
  const [failedUrl, setFailedUrl] = useState<string | null>(null)
  if (icon && icon.startsWith('lucide:')) {
    return <LucideByName name={icon.slice(7)} size={size} className={className} />
  }
  const url = iconUrl(icon)
  if (!url || failedUrl === url) {
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
      onError={() => setFailedUrl(url)}
    />
  )
}

export function LucideByName({ name, size = 16, className = '' }: { name: string; size?: number; className?: string }) {
  const Symbol = SYMBOLS[name] ?? Box
  return <Symbol size={size} className={className} aria-hidden="true" />
}
