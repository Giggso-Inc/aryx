import { MarkerType, type Node, type Edge } from "@xyflow/react";
import { typeColor } from "@/lib/typeColor";
import { autoLayout } from "@/lib/canvasLayout";
import { OVERVIEW_NODE_WIDTH, clippedLineStyle, hexToRgba } from "./visual-helpers";
import type { OverviewEdge, OverviewNode, TruncatedEdgeData } from "./types";

export function buildOverviewGraph(
  overviewNodes: OverviewNode[],
  overviewEdges: OverviewEdge[],
  typeIndex: Map<string, number>,
): { nodes: Node[]; edges: Edge[] } {
  const nodes: Node[] = overviewNodes.map((node) => {
    const color = typeColor(typeIndex.get(node.type) ?? 0);
    return {
      id: node.id,
      type: "default",
      data: {
        label: (
          <div style={{ textAlign: "center", lineHeight: 1.3, minWidth: 0, overflow: "hidden", width: "100%" }}>
            <div
              title={node.type}
              style={clippedLineStyle({ fontWeight: 700, fontSize: 12, color: "#0F1726" })}
            >
              {node.type}
            </div>
            <div
              title={`${node.count} matched entities`}
              style={clippedLineStyle({ fontSize: 10, color: "#0F9D8B", marginTop: 2 })}
            >
              {node.count} matched entities
            </div>
          </div>
        ),
      },
      position: { x: 0, y: 0 },
      style: {
        background: hexToRgba(color, 0.08),
        border: `2px solid ${color}`,
        borderRadius: 10,
        padding: "8px 12px",
        width: OVERVIEW_NODE_WIDTH,
        overflow: "hidden",
        boxSizing: "border-box",
        boxShadow: "0 8px 24px rgba(15, 23, 38, 0.08)",
      },
    };
  });

  const edges: Edge[] = overviewEdges.map((edge, index) => ({
    id: `overview-edge-${edge.source}-${edge.target}-${index}`,
    source: `overview::${edge.source}`,
    target: `overview::${edge.target}`,
    type: "truncatedSmoothstep",
    style: { stroke: "#0F9D8B", strokeWidth: 2.4 },
    data: {
      label: `${edge.name} (${edge.count})`,
      title: `${edge.name} (${edge.count})`,
      labelColor: "#334155",
      labelFontWeight: 600,
      labelOpacity: 1,
      labelBackground: "#ffffff",
      labelBackgroundOpacity: 0.95,
    } satisfies TruncatedEdgeData,
    markerEnd: {
      type: MarkerType.ArrowClosed,
      color: "#0F9D8B",
      width: 14,
      height: 14,
    },
  }));

  return autoLayout(nodes, edges, "LR");
}
