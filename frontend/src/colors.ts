// One place for every color used in the graph view, so the legend and the
// canvas renderer can never drift out of sync with each other.
import type { NodeLabel } from './api/types'

export const NODE_TYPE_COLOR: Record<NodeLabel, string> = {
  Region: '#8b5cf6', // violet
  DataCenter: '#3b82f6', // blue
  Host: '#14b8a6', // teal
  Service: '#f59e0b', // amber
  IncidentEvent: '#ef4444', // red
}

export const EDGE_COLOR: Record<string, string> = {
  CONTAINS: 'rgba(148, 163, 184, 0.55)', // slate, structural
  RUNS_ON: 'rgba(20, 184, 166, 0.75)', // teal, matches Host
  DEPENDS_ON: 'rgba(245, 158, 11, 0.8)', // amber, matches Service
  CONNECTS_TO: 'rgba(148, 163, 184, 0.4)',
  AFFECTS: 'rgba(239, 68, 68, 0.85)', // red, matches IncidentEvent
}

export const HEALTH_RING_COLOR: Record<string, string | null> = {
  healthy: null, // no ring -- the default type color already communicates "normal"
  unhealthy: '#dc2626',
  'unknown (no recent heartbeat)': '#9ca3af',
}

export const BLAST_RADIUS_COLOR = {
  selected: '#facc15', // yellow -- the node you clicked
  downstream: '#fb923c', // orange -- would break if the selected node fails
  upstream: '#60a5fa', // blue -- what the selected node itself depends on
}
