import { NODE_TYPE_COLOR, BLAST_RADIUS_COLOR } from '../colors'

export function Legend() {
  return (
    <div className="legend">
      <div className="legend-group">
        <h3>Node type</h3>
        {Object.entries(NODE_TYPE_COLOR).map(([label, color]) => (
          <div className="legend-row" key={label}>
            <span className="swatch" style={{ backgroundColor: color }} />
            <span>{label}</span>
          </div>
        ))}
      </div>
      <div className="legend-group">
        <h3>Health ring</h3>
        <div className="legend-row">
          <span className="ring" style={{ borderColor: '#dc2626' }} />
          <span>Unhealthy</span>
        </div>
        <div className="legend-row">
          <span className="ring dashed" style={{ borderColor: '#9ca3af' }} />
          <span>No recent heartbeat</span>
        </div>
      </div>
      <div className="legend-group">
        <h3>Blast radius</h3>
        <div className="legend-row">
          <span className="ring" style={{ borderColor: BLAST_RADIUS_COLOR.selected }} />
          <span>Selected node</span>
        </div>
        <div className="legend-row">
          <span className="ring" style={{ borderColor: BLAST_RADIUS_COLOR.downstream }} />
          <span>Would be affected (downstream)</span>
        </div>
        <div className="legend-row">
          <span className="ring" style={{ borderColor: BLAST_RADIUS_COLOR.upstream }} />
          <span>Required by selection (upstream)</span>
        </div>
      </div>
    </div>
  )
}
