import { edgePath, type GraphLayout } from "./layout";

export function GraphSvg({ layout }: { layout: GraphLayout }) {
  return (
    <svg
      viewBox={`0 0 ${layout.width} ${layout.height}`}
      className="block"
      style={{ width: `${layout.width}px`, height: `${layout.height}px`, maxWidth: "none" }}
    >
      <defs>
        <marker id="graph-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7"
                markerHeight="7" orient="auto-start-reverse">
          <path d="M0 0L10 5L0 10z" fill="#A5B5D3" />
        </marker>
      </defs>

      {layout.edges.map((edge, index) => (
        <g key={`${edge.source}:${edge.target}:${edge.name}:${index}`}>
          <title>{edge.label}</title>
          <path
            d={edgePath(edge.points)}
            fill="none"
            stroke="#C8D5E8"
            strokeWidth={1.7}
            markerEnd="url(#graph-arrow)"
            opacity={0.95}
          />
          <g transform={`translate(${edge.labelX} ${edge.labelY})`} className="cursor-help">
            <rect
              x={-Math.max(38, edge.shortLabel.length * 3.7)}
              y={-10}
              width={Math.max(76, edge.shortLabel.length * 7.4)}
              height={20}
              rx={10}
              fill="#FFFFFF"
              stroke="#D6E0F0"
            />
            <text
              textAnchor="middle"
              y={4}
              fontSize="9.75"
              fontFamily="JetBrains Mono, monospace"
              fill="#4068A8"
            >
              {edge.shortLabel}
            </text>
          </g>
        </g>
      ))}

      {layout.nodes.map((node) => (
        <g
          key={node.type}
          transform={`translate(${node.x - node.width / 2} ${node.y - node.height / 2})`}
          className="cursor-help"
        >
          <title>{`${node.type} • ${node.count}`}</title>
          <rect
            width={node.width}
            height={node.height}
            rx={20}
            fill={node.color}
            stroke="#FFFFFF"
            strokeWidth={2}
          />
          <text
            x={node.width / 2}
            y={26}
            textAnchor="middle"
            fontSize="14"
            fontWeight="700"
            fill="#FFFFFF"
          >
            {node.shortLabel}
          </text>
          <text
            x={node.width / 2}
            y={45}
            textAnchor="middle"
            fontSize="11.5"
            fontWeight="500"
            fill="rgba(255,255,255,0.92)"
          >
            {node.count} {node.count === 1 ? "record" : "records"}
          </text>
        </g>
      ))}
    </svg>
  );
}
