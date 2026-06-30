import dagre from "dagre";
import type { Edge, Node } from "@xyflow/react";

const NODE_W = 160;
const NODE_H = 60;
const GRID_COLS = 6;
const GRID_GAP_X = 180;
const GRID_GAP_Y = 80;
const GRID_MARGIN_TOP = 80;

/**
 * Auto-layout nodes + edges with dagre. Stable: same input → same output.
 * Direction LR (left-right) reads like a schema diagram; switch to TB for
 * inheritance views.
 *
 * Isolated nodes (no edges) are separated from the dagre pass and placed in
 * a grid below the connected subgraph so they don't stack as a vertical train.
 */
export function autoLayout(
  nodes: Node[],
  edges: Edge[],
  direction: "LR" | "TB" = "LR",
): { nodes: Node[]; edges: Edge[] } {
  // Split connected vs isolated nodes.
  const edgeNodeIds = new Set<string>();
  for (const e of edges) {
    edgeNodeIds.add(e.source);
    edgeNodeIds.add(e.target);
  }
  const connected = nodes.filter((n) => edgeNodeIds.has(n.id));
  const isolated = nodes.filter((n) => !edgeNodeIds.has(n.id));

  // Run dagre only on connected nodes.
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: direction, nodesep: 40, ranksep: 120 });
  for (const n of connected) g.setNode(n.id, { width: NODE_W, height: NODE_H });
  for (const e of edges) g.setEdge(e.source, e.target);
  dagre.layout(g);

  const positionedConnected = connected.map((n) => {
    const p = g.node(n.id);
    return { ...n, position: { x: p.x - NODE_W / 2, y: p.y - NODE_H / 2 } };
  });

  // Find the bottom of the dagre bounding box.
  let maxY = 0;
  for (const n of positionedConnected) {
    const bottom = n.position.y + NODE_H;
    if (bottom > maxY) maxY = bottom;
  }
  const gridOriginY = maxY + GRID_MARGIN_TOP;

  // Place isolated nodes in a grid starting below the connected web.
  const positionedIsolated = isolated.map((n, i) => {
    const col = i % GRID_COLS;
    const row = Math.floor(i / GRID_COLS);
    return {
      ...n,
      position: { x: col * GRID_GAP_X, y: gridOriginY + row * GRID_GAP_Y },
    };
  });

  return {
    nodes: [...positionedConnected, ...positionedIsolated],
    edges,
  };
}
