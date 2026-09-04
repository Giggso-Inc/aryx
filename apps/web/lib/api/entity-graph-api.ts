import { fetchJSON } from "./core";

export const entityGraphApi = {
  getEntity: (entityId: number, workspaceId: number) =>
    fetchJSON<{
      id: number;
      type: string;
      name: string;
      attributes?: Record<string, unknown>;
    }>(`/entities/${entityId}?workspace_id=${workspaceId}`),

  getEntityGraph: (workspaceId: number) =>
    fetchJSON<{
      entities: Array<{ id: number; type: string; name: string; attributes?: Record<string, unknown> }>;
      relationships: Array<{ source: number; target: number; name: string }>;
    }>(`/graph?workspace_id=${workspaceId}`),

  getEntityGraphOverview: (workspaceId: number) =>
    fetchJSON<{
      domain: string;
      overview_nodes: Array<{ id: string; type: string; count: number; entity_ids: number[] }>;
      overview_edges: Array<{ source: string; target: string; name: string; count: number }>;
      matched_entity_ids: number[];
      matched_edge_pairs: Array<{ source: number; target: number }>;
      matched_types: string[];
      fallback_used: boolean;
      entity_count: number;
      relationship_count: number;
    }>(`/graph/overview?workspace_id=${workspaceId}`),

  getEntityNeighbors: (entityId: number, workspaceId: number) =>
    fetchJSON<Array<{
      id: number;
      type: string;
      name: string;
      attributes?: Record<string, unknown>;
      relationship: string;
      direction: "in" | "out";
    }>>(
      `/entities/${entityId}/neighbors?workspace_id=${workspaceId}`,
    ),

  getEntityPath: (srcId: number, dstId: number, workspaceId: number) =>
    fetchJSON<Array<{ id: number; type: string; name: string }>>(
      `/entities/${srcId}/path/${dstId}?workspace_id=${workspaceId}`,
    ),
};
