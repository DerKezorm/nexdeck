import type { WidgetView } from './types'

/** Who the maintenance of a card is for: an app tile itself, any other card its connection. */
export function maintenanceTarget(widget: WidgetView): { integration_id: number } | { widget_id: number } | null {
  if (widget.kind === 'core.app') return widget.health ? { widget_id: widget.id } : null
  return widget.integration_id != null ? { integration_id: widget.integration_id } : null
}
