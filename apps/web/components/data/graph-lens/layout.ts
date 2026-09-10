import dagre from "dagre";
import { typeColor } from "@/lib/typeColor";
import type { DataTypeCount, GraphTypeEdge, GraphTypeNode } from "@/lib/types";

const MIN_NODE_WIDTH = 132;
const MAX_NODE_WIDTH = 188;
const NODE_HEIGHT = 64;
export const MIN_GRAPH_WIDTH = 920;
export const MIN_GRAPH_HEIGHT = 540;
const NODE_LABEL_LIMIT = 16;
const EDGE_LABEL_LIMIT = 24;

interface GraphLayoutNodeData {
  color: string;
}

function truncateLabel(label: string, limit: number): string {
  return label.length <= limit ? label : `${label.slice(0, Math.max(1, limit - 1))}…`;
}

function nodeWidth(label: string): number {
  return Math.max(MIN_NODE_WIDTH, Math.min(MAX_NODE_WIDTH, 64 + label.length * 7.1));
}

function edgeLabel(edge: GraphTypeEdge): string {
  return `${edge.name} (${edge.count})`;
}

export function edgePath(points: Array<{ x: number; y: number }>): string {
  if (points.length === 0) return "";
  if (points.length === 1) return `M ${points[0].x} ${points[0].y}`;
  return points.map((point, index) =>
    `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`).join(" ");
}

export function buildGraphLayout(nodes: GraphTypeNode[], edges: GraphTypeEdge[], types: DataTypeCount[]) {
  const graph = new dagre.graphlib.Graph<GraphLayoutNodeData>({ multigraph: true });
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

export type GraphLayout = ReturnType<typeof buildGraphLayout>;
