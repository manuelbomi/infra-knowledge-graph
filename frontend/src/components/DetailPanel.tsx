import type { ImpactResult, NodeDetail } from '../api/types'

interface Props {
  detail: NodeDetail | null
  impact: ImpactResult | null
  loading: boolean
  onRunImpact: () => void
  onSelectNode: (id: string) => void
  onClose: () => void
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(1)
  return String(value)
}

export function DetailPanel({ detail, impact, loading, onRunImpact, onSelectNode, onClose }: Props) {
  if (!detail) {
    return (
      <div className="detail-panel empty">
        <p>Click a node in the graph to see its properties and run a blast-radius check.</p>
      </div>
    )
  }

  return (
    <div className="detail-panel">
      <div className="detail-header">
        <span className="detail-label-tag">{detail.label}</span>
        <button className="close-button" onClick={onClose} aria-label="Close detail panel">
          ×
        </button>
      </div>
      <h2>{(detail.properties.name as string) ?? (detail.properties.hostname as string) ?? detail.id}</h2>

      <table className="property-table">
        <tbody>
          {Object.entries(detail.properties).map(([key, value]) => (
            <tr key={key}>
              <td className="property-key">{key}</td>
              <td>{formatValue(value)}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <button className="primary-button" onClick={onRunImpact} disabled={loading}>
        {loading ? 'Checking blast radius…' : 'What breaks if this goes down?'}
      </button>

      {impact && (
        <div className="impact-results">
          <h3>Downstream impact ({impact.downstream_impact.length})</h3>
          {impact.downstream_impact.length === 0 ? (
            <p className="muted">Nothing depends on this directly or transitively.</p>
          ) : (
            <ul>
              {impact.downstream_impact.map((n) => (
                <li key={n.id}>
                  <button className="link-button" onClick={() => onSelectNode(n.id)}>
                    {n.id}
                  </button>{' '}
                  <span className="muted">({n.label})</span>
                </li>
              ))}
            </ul>
          )}

          <h3>Upstream dependencies ({impact.upstream_dependencies.length})</h3>
          {impact.upstream_dependencies.length === 0 ? (
            <p className="muted">This doesn't depend on anything else.</p>
          ) : (
            <ul>
              {impact.upstream_dependencies.map((n) => (
                <li key={n.id}>
                  <button className="link-button" onClick={() => onSelectNode(n.id)}>
                    {n.id}
                  </button>{' '}
                  <span className="muted">({n.label})</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <h3>Relationships</h3>
      <ul className="relationship-list">
        {detail.outgoing_relationships.map((rel, idx) => (
          <li key={`out-${idx}`}>
            <span className="rel-type">{detail.id} —{rel.rel_type}→</span>{' '}
            <button className="link-button" onClick={() => rel.target_id && onSelectNode(rel.target_id)}>
              {rel.target_id}
            </button>
          </li>
        ))}
        {detail.incoming_relationships.map((rel, idx) => (
          <li key={`in-${idx}`}>
            <button className="link-button" onClick={() => rel.source_id && onSelectNode(rel.source_id)}>
              {rel.source_id}
            </button>{' '}
            <span className="rel-type">—{rel.rel_type}→ {detail.id}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
