import type { Edge } from "@xyflow/react";

export type EntityNode = {
  id: number; type: string; name: string;
  attributes?: Record<string, unknown>;
};
export type EntityRel = { source: number; target: number; name: string };
export type OverviewNode = { id: string; type: string; count: number; entity_ids: number[] };
export type OverviewEdge = { source: string; target: string; name: string; count: number };
export type GraphOverview = {
  domain: string;
  overview_nodes: OverviewNode[];
  overview_edges: OverviewEdge[];
  matched_entity_ids: number[];
  matched_edge_pairs: Array<{ source: number; target: number }>;
  matched_types: string[];
  fallback_used: boolean;
  entity_count: number;
  relationship_count: number;
};
export type GraphMode = "overview" | "focused" | "full";
export type TruncatedEdgeData = Record<string, unknown> & {
  label: string;
  title: string;
  labelColor: string;
  labelFontWeight: number;
  labelOpacity: number;
  labelBackground: string;
  labelBackgroundOpacity: number;
};
export type TruncatedEdge = Edge<TruncatedEdgeData, "truncatedSmoothstep">;
export type NeighborNode = {
  id: number;
  type: string;
  name: string;
  attributes?: Record<string, unknown>;
  relationship: string;
  direction: "in" | "out";
};
