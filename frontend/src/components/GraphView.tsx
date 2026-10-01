import { useMemo, useRef } from 'react'
import ForceGraph2D, { type NodeObject, type LinkObject, type ForceGraphMethods } from 'react-force-graph-2d'
import type { GraphEdge, GraphNode } from '../api/types'
import { BLAST_RADIUS_COLOR, EDGE_COLOR, HEALTH_RING_COLOR, NODE_TYPE_COLOR } from '../colors'

interface Props {
  nodes: GraphNode[]
  edges: GraphEdge[]
  onNodeClick: (node: GraphNode) => void
  selectedNodeId: string | null
  downstreamIds: Set<string>
  upstreamIds: Set<string>
}

function displayName(node: GraphNode): string {
  return (node.name as string) ?? (node.hostname as string) ?? node.id
}

export function GraphView({ nodes, edges, onNodeClick, selectedNodeId, downstreamIds, upstreamIds }: Props) {
  const fgRef = useRef<ForceGraphMethods<NodeObject<GraphNode>, LinkObject<GraphNode, GraphEdge>>>(undefined)

  // react-force-graph merges new node/link data into its running simulation
  // by matching on `id`, preserving each node's current x/y position. That's
  // why it's safe to hand it a brand-new array on every websocket update
  // instead of mutating one array in place -- nodes that already exist don't
  // jump around, and only genuinely new nodes (like a fresh IncidentEvent)
  // appear somewhere new and animate into place.
  const graphData = useMemo(
    () => ({
      nodes,
      links: edges.map((edge) => ({ ...edge, source: edge.source, target: edge.target })),
    }),
    [nodes, edges],
  )

  const isFocusActive = selectedNodeId !== null

  return (
    <ForceGraph2D
      ref={fgRef}
      graphData={graphData}
      nodeId="id"
      backgroundColor="transparent"
      nodeRelSize={4}
      linkColor={(link) => EDGE_COLOR[(link as unknown as GraphEdge).rel_type] ?? 'rgba(148,163,184,0.4)'}
      linkWidth={(link) => {
        const edge = link as unknown as GraphEdge
        if (edge.rel_type !== 'DEPENDS_ON') return 1
        // Lower-confidence dependency edges (declared but never confirmed,
        // or observed but never declared) are drawn thinner, so a glance at
        // the graph shows which links the system isn't fully sure about.
        return 0.6 + (edge.confidence ?? 1) * 1.8
      }}
      linkDirectionalArrowLength={4}
      linkDirectionalArrowRelPos={1}
      onNodeClick={(node) => onNodeClick(node as unknown as GraphNode)}
      nodeCanvasObject={(nodeObj, ctx, globalScale) => {
        const node = nodeObj as unknown as GraphNode & { x: number; y: number }
        const x = node.x
        const y = node.y
        const baseRadius = 5
        const isSelected = node.id === selectedNodeId
        const isDownstream = downstreamIds.has(node.id)
        const isUpstream = upstreamIds.has(node.id)
        const isDimmed = isFocusActive && !isSelected && !isDownstream && !isUpstream

        ctx.globalAlpha = isDimmed ? 0.25 : 1
        ctx.beginPath()
        ctx.arc(x, y, baseRadius, 0, 2 * Math.PI)
        ctx.fillStyle = NODE_TYPE_COLOR[node.label] ?? '#94a3b8'
        ctx.fill()

        // Blast-radius ring takes priority over the plain health ring so the
        // two states never fight for the same pixels.
        if (isSelected || isDownstream || isUpstream) {
          const ringColor = isSelected
            ? BLAST_RADIUS_COLOR.selected
            : isDownstream
              ? BLAST_RADIUS_COLOR.downstream
              : BLAST_RADIUS_COLOR.upstream
          ctx.lineWidth = 2.5
          ctx.strokeStyle = ringColor
          ctx.beginPath()
          ctx.arc(x, y, baseRadius + 3, 0, 2 * Math.PI)
          ctx.stroke()
        } else {
          const health = node.health as string | undefined
          const ringColor = health ? HEALTH_RING_COLOR[health] : null
          if (ringColor) {
            ctx.lineWidth = 2
            ctx.strokeStyle = ringColor
            ctx.setLineDash(health === 'unhealthy' ? [] : [2, 2])
            ctx.beginPath()
            ctx.arc(x, y, baseRadius + 2.5, 0, 2 * Math.PI)
            ctx.stroke()
            ctx.setLineDash([])
          }
        }

        // Only draw labels once you've zoomed in enough for them to be
        // legible -- at the default zoom, 46 labels on top of each other is
        // just noise.
        if (globalScale > 1.4) {
          const label = displayName(node)
          const fontSize = 11 / globalScale
          ctx.font = `${fontSize}px Inter, system-ui, sans-serif`
          ctx.textAlign = 'center'
          ctx.fillStyle = isDimmed ? 'rgba(148,163,184,0.5)' : '#e2e8f0'
          ctx.fillText(label, x, y + baseRadius + 8)
        }
        ctx.globalAlpha = 1
      }}
    />
  )
}
