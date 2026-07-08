"use client";

import dagre from "dagre";
import { useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/lib/workspace";
import { typeColor } from "@/lib/typeColor";
import type { DataTypeCount, GraphTypeEdge, GraphTypeNode, GraphView } from "@/lib/types";

const MIN_NODE_WIDTH = 132;
const MAX_NODE_WIDTH = 188;
const NODE_HEIGHT = 64;
const MIN_GRAPH_WIDTH = 920;
const MIN_GRAPH_HEIGHT = 540;
const NODE_LABEL_LIMIT = 16;
const EDGE_LABEL_LIMIT = 24;

function truncateLabel(label: string, limit: number): string {
  return label.length <= limit ? label : `${label.slice(0, Math.max(1, limit - 1))}\u2026`;
}

function nodeWidth(label: string): number {
  return Math.max(MIN_NODE_WIDTH, Math.min(MAX_NODE_WIDTH, 64 + label.length * 7.1));
}

function edgeLabel(edge: GraphTypeEdge): string {
  return `${edge.name} (${edge.count})`;
}

function edgePath(points: Array<{ x: number; y: number }>): string {
  if (points.length === 0) return "";
  if (points.length === 1) return `M ${points[0].x} ${points[0].y}`;
  return points.map((point, index) =>
    `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`).join(" ");
}

function buildGraphLayout(nodes: GraphTypeNode[], edges: GraphTypeEdge[], types: DataTypeCount[]) {
  const graph = new dagre.graphlib.Graph({ multigraph: true });
  graph.setGraph({
    rankdir: "LR",
    align: "UL",
    nodesep: 48,
    ranksep: 92,
    marginx: 40,
    marginy: 36,
    ranker: "network-simplex",
  });
  graph.setDefaultEdgeLabel(() => ({}));

  const colorByType = new Map(types.map((type, index) => [type.name, typeColor(index)]));

  nodes.forEach((node, index) => {
    graph.setNode(node.type, {
      width: nodeWidth(node.type),
      height: NODE_HEIGHT,
      color: colorByType.get(node.type) ?? typeColor(index),
    });
  });

  edges.forEach((edge, index) => {
    const label = edgeLabel(edge);
    graph.setEdge(
      edge.source,
      edge.target,
      {
        width: Math.max(84, Math.min(192, 28 + label.length * 6.1)),
        height: 28,
        label,
      },
      `${edge.source}:${edge.target}:${edge.name}:${index}`,
    );
  });

  dagre.layout(graph);

  const laidOutNodes = nodes.map((node, index) => {
    const layoutNode = graph.node(node.type);
    return {
      ...node,
      x: layoutNode.x as number,
      y: layoutNode.y as number,
      width: layoutNode.width as number,
      height: layoutNode.height as number,
      color: (layoutNode.color as string) ?? colorByType.get(node.type) ?? typeColor(index),
      shortLabel: truncateLabel(node.type, NODE_LABEL_LIMIT),
    };
  });

  const laidOutEdges = edges.map((edge, index) => {
    const layoutEdge = graph.edge({
      v: edge.source,
      w: edge.target,
      name: `${edge.source}:${edge.target}:${edge.name}:${index}`,
    });
    const label = edgeLabel(edge);
    return {
      ...edge,
      label,
      shortLabel: truncateLabel(label, EDGE_LABEL_LIMIT),
      points: (layoutEdge.points as Array<{ x: number; y: number }>) ?? [],
      labelX: (layoutEdge.x as number | undefined) ?? 0,
      labelY: (layoutEdge.y as number | undefined) ?? 0,
    };
  });

  const graphMeta = graph.graph();
  return {
    nodes: laidOutNodes,
    edges: laidOutEdges,
    width: Math.max(MIN_GRAPH_WIDTH, Math.ceil((graphMeta.width as number | undefined) ?? 0) + 80),
    height: Math.max(MIN_GRAPH_HEIGHT, Math.ceil((graphMeta.height as number | undefined) ?? 0) + 72),
  };
}

/** Type-level knowledge map: one node per type with a layout that preserves
 *  readable labels and avoids overlap across dense ontologies. */
export function GraphLens({ types }: { types: DataTypeCount[] }) {
  const { workspaceId } = useWorkspace();
  const [g, setG] = useState<GraphView | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const layout = useMemo(
    () => (g ? buildGraphLayout(g.type_nodes, g.type_edges, types) : null),
    [g, types],
  );

  useEffect(() => {
    let live = true;
    setG(null); setErr(null);
    api.dataGraph(workspaceId)
      .then((d) => { if (live) (("error" in d && d.error) ? setErr(d.error!) : setG(d)); })
      .catch((e) => { if (live) setErr(e instanceof Error ? e.message : "failed"); });
    return () => { live = false; };
  }, [workspaceId]);

  if (err) return <Box><span className="text-rose-600">{err}</span></Box>;
  if (!g) return <Box><Loader2 size={16} className="animate-spin" /> building map…</Box>;
  if (!layout) return <Box><Loader2 size={16} className="animate-spin" /> building map…</Box>;

  return (
    <div className="rounded-2xl border border-navy-100 bg-white p-3">
      <div className="mb-1 flex items-center justify-between px-2 pt-1 text-[11px] text-subtle">
        <span>{g.entity_count} entities · {g.relationship_count} relationships</span>
        <span>hover truncated labels to see the full name</span>
      </div>
      {g.relationship_count === 0 ? (
        <p className="px-2 py-6 text-center text-[12.5px] text-subtle">
          Entities exist but no relationships are defined yet — the map shows the
          types; connect them with foreign-key links to see the graph.
        </p>
      ) : null}
      <div className="overflow-auto rounded-xl">
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
      </div>
    </div>
  );
}

function Box({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-center gap-2 rounded-2xl border border-navy-100 bg-white px-4 py-16 text-[13px] text-subtle">
      {children}
    </div>
  );
}
