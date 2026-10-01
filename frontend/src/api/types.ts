// These shapes mirror what the FastAPI backend actually returns
// (see backend/app/graph_queries.py and backend/app/ingest/reconciler.py).
// Keeping them in one file means a backend field rename shows up here as a
// compile error instead of a silent runtime bug in the dashboard.

export type NodeLabel = 'Region' | 'DataCenter' | 'Host' | 'Service' | 'IncidentEvent'

export type HealthStatus = 'healthy' | 'unhealthy' | 'unknown (no recent heartbeat)'

export interface GraphNode {
  id: string
  label: NodeLabel
  // Everything else is label-specific (hostname, name, health, latency_ms,
  // region_id, etc.) and varies by node type, so we keep it loose here and
  // read individual fields defensively where we render them.
  [key: string]: unknown
}

export interface GraphEdge {
  source: string
  target: string
  rel_type: 'CONTAINS' | 'RUNS_ON' | 'DEPENDS_ON' | 'CONNECTS_TO' | 'AFFECTS'
  state?: string
  confidence?: number
  source_label?: string
  [key: string]: unknown
}

export interface GraphSnapshot {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface RelationshipRef {
  rel_type: string
  target_id?: string
  target_label?: string
  source_id?: string
  source_label?: string
  props: Record<string, unknown>
}

export interface NodeDetail {
  id: string
  label: NodeLabel
  properties: Record<string, unknown>
  outgoing_relationships: RelationshipRef[]
  incoming_relationships: RelationshipRef[]
}

export interface ImpactResult {
  node_id: string
  downstream_impact: { id: string; label: NodeLabel }[]
  upstream_dependencies: { id: string; label: NodeLabel }[]
}

// What arrives over the /ws/graph-updates socket every reconciliation cycle.
export interface GraphDeltaMessage {
  type: 'graph_delta'
  timestamp: string
  updated_nodes: { id: string; label: NodeLabel; health: HealthStatus; latency_ms: number }[]
  updated_edges: {
    from: string
    to: string
    rel_type: string
    state?: string
    confidence?: number
    source_label?: string
  }[]
  new_incidents: { id: string; affects: string; started_at: string }[]
}
