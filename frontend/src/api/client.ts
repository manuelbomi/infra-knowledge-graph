import type { GraphSnapshot, ImpactResult, NodeDetail } from './types'

async function getJSON<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) {
    throw new Error(`Request to ${path} failed with status ${response.status}`)
  }
  return response.json() as Promise<T>
}

export function fetchGraph(): Promise<GraphSnapshot> {
  return getJSON<GraphSnapshot>('/api/graph')
}

export function fetchNodeDetail(nodeId: string): Promise<NodeDetail> {
  return getJSON<NodeDetail>(`/api/nodes/${encodeURIComponent(nodeId)}`)
}

export function fetchImpact(nodeId: string): Promise<ImpactResult> {
  return getJSON<ImpactResult>(`/api/impact/${encodeURIComponent(nodeId)}`)
}

// Builds the websocket URL relative to whatever host/port the page is
// served from, so this works both in local dev (via the Vite proxy) and in
// a production deployment without hardcoding a host.
export function graphUpdatesSocketUrl(): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/ws/graph-updates`
}
