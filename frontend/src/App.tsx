import { useEffect, useMemo, useRef, useState } from 'react'
import './App.css'
import { fetchGraph, fetchImpact, fetchNodeDetail, graphUpdatesSocketUrl } from './api/client'
import type { GraphDeltaMessage, GraphEdge, GraphNode, ImpactResult, NodeDetail } from './api/types'
import { GraphView } from './components/GraphView'
import { DetailPanel } from './components/DetailPanel'
import { Legend } from './components/Legend'

function edgeKey(source: string, target: string, relType: string): string {
  return `${source}|${relType}|${target}`
}

interface IncidentLogEntry {
  id: string
  affects: string
  startedAt: string
}

export default function App() {
  const [nodesById, setNodesById] = useState<Map<string, GraphNode>>(new Map())
  const [edgesByKey, setEdgesByKey] = useState<Map<string, GraphEdge>>(new Map())
  const [wsConnected, setWsConnected] = useState(false)
  const [incidentLog, setIncidentLog] = useState<IncidentLogEntry[]>([])

  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [detail, setDetail] = useState<NodeDetail | null>(null)
  const [impact, setImpact] = useState<ImpactResult | null>(null)
  const [impactLoading, setImpactLoading] = useState(false)

  const socketRef = useRef<WebSocket | null>(null)

  // Initial full snapshot, once, on load.
  useEffect(() => {
    fetchGraph().then((snapshot) => {
      setNodesById(new Map(snapshot.nodes.map((n) => [n.id, n])))
      setEdgesByKey(
        new Map(snapshot.edges.map((e) => [edgeKey(e.source, e.target, e.rel_type), e])),
      )
    })
  }, [])

  // Live updates. Runs once; all the state it touches is updated through
  // functional setState so it never needs to be re-subscribed.
  useEffect(() => {
    const socket = new WebSocket(graphUpdatesSocketUrl())
    socketRef.current = socket

    socket.onopen = () => setWsConnected(true)
    socket.onclose = () => setWsConnected(false)
    socket.onerror = () => setWsConnected(false)

    socket.onmessage = (event) => {
      const message: GraphDeltaMessage = JSON.parse(event.data)

      setNodesById((prev) => {
        const next = new Map(prev)
        for (const update of message.updated_nodes) {
          const existing = next.get(update.id)
          next.set(update.id, { ...(existing ?? { id: update.id, label: update.label }), ...update })
        }
        for (const incident of message.new_incidents) {
          next.set(incident.id, {
            id: incident.id,
            label: 'IncidentEvent',
            started_at: incident.started_at,
            affected_entity_id: incident.affects,
          })
        }
        return next
      })

      setEdgesByKey((prev) => {
        const next = new Map(prev)
        for (const update of message.updated_edges) {
          const key = edgeKey(update.from, update.to, update.rel_type)
          const existing = next.get(key)
          next.set(key, {
            ...existing,
            ...update,
            source: update.from,
            target: update.to,
            rel_type: update.rel_type as GraphEdge['rel_type'],
          })
        }
        for (const removed of message.removed_edges) {
          next.delete(edgeKey(removed.from, removed.to, removed.rel_type))
        }
        for (const incident of message.new_incidents) {
          const key = edgeKey(incident.id, incident.affects, 'AFFECTS')
          next.set(key, { source: incident.id, target: incident.affects, rel_type: 'AFFECTS' })
        }
        return next
      })

      if (message.new_incidents.length > 0) {
        setIncidentLog((prev) =>
          [
            ...message.new_incidents.map((i) => ({ id: i.id, affects: i.affects, startedAt: i.started_at })),
            ...prev,
          ].slice(0, 6),
        )
      }
    }

    return () => socket.close()
  }, [])

  const nodes = useMemo(() => Array.from(nodesById.values()), [nodesById])
  const edges = useMemo(() => Array.from(edgesByKey.values()), [edgesByKey])
  const unhealthyCount = useMemo(() => nodes.filter((n) => n.health === 'unhealthy').length, [nodes])

  const downstreamIds = useMemo(
    () => new Set(impact?.downstream_impact.map((n) => n.id) ?? []),
    [impact],
  )
  const upstreamIds = useMemo(
    () => new Set(impact?.upstream_dependencies.map((n) => n.id) ?? []),
    [impact],
  )

  function selectNode(id: string) {
    setSelectedNodeId(id)
    setImpact(null)
    fetchNodeDetail(id).then(setDetail)
  }

  function runImpact() {
    if (!selectedNodeId) return
    setImpactLoading(true)
    fetchImpact(selectedNodeId)
      .then(setImpact)
      .finally(() => setImpactLoading(false))
  }

  function closeDetail() {
    setSelectedNodeId(null)
    setDetail(null)
    setImpact(null)
  }

  return (
    <div className="app-shell">
      <header className="top-bar">
        <h1>Infrastructure Knowledge Graph</h1>
        <div className="top-bar-stats">
          <span className={`status-dot ${wsConnected ? 'connected' : 'disconnected'}`} />
          <span>{wsConnected ? 'Live' : 'Disconnected'}</span>
          <span className="stat-sep">·</span>
          <span>{nodes.length} nodes</span>
          <span className="stat-sep">·</span>
          <span className={unhealthyCount > 0 ? 'stat-warning' : ''}>{unhealthyCount} unhealthy</span>
        </div>
      </header>

      <div className="main-layout">
        <aside className="left-rail">
          <Legend />
          <div className="incident-feed">
            <h3>Recent incidents</h3>
            {incidentLog.length === 0 ? (
              <p className="muted">No incidents yet this session.</p>
            ) : (
              <ul>
                {incidentLog.map((entry) => (
                  <li key={entry.id}>
                    <button className="link-button" onClick={() => selectNode(entry.affects)}>
                      {entry.affects}
                    </button>
                    <span className="muted"> went down</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>

        <main className="graph-area">
          <GraphView
            nodes={nodes}
            edges={edges}
            onNodeClick={(node) => selectNode(node.id)}
            selectedNodeId={selectedNodeId}
            downstreamIds={downstreamIds}
            upstreamIds={upstreamIds}
          />
        </main>

        <aside className="right-rail">
          <DetailPanel
            detail={detail}
            impact={impact}
            loading={impactLoading}
            onRunImpact={runImpact}
            onSelectNode={selectNode}
            onClose={closeDetail}
          />
        </aside>
      </div>
    </div>
  )
}
