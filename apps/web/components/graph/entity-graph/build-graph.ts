import type { Node, Edge } from "@xyflow/react";
import { typeColor } from "@/lib/typeColor";
import { autoLayout } from "@/lib/canvasLayout";
import { buildEntityNodes } from "./build-entity-nodes";
import { buildSchemaOnlyNodes } from "./build-schema-nodes";
import { buildGraphEdges } from "./build-graph-edges";
import type { EntityNode, EntityRel, GraphMode } from "./types";

export function resolveFocusSourceEntityIds(
  focusedEntityIds: Set<number> | null,
  domainEntityIds: Set<number>,
): Set<number> | null {
  if (focusedEntityIds && focusedEntityIds.size > 0) return focusedEntityIds;
  return domainEntityIds.size > 0 ? domainEntityIds : null;
}

export function buildGraph(
  entities: EntityNode[],
  rels: EntityRel[],
  typeSet: Set<string>,
  nameFilter: string,
  selectedId: number | null,
  selectedNeighborIds: Set<number>,
  selectedEdgeKeys: Set<string>,
  pathIds: Set<number>,
  typeIndex: Map<string, number>,
  schemaOnlyTypes: string[],
  graphMode: GraphMode,
  focusedEntityIds: Set<number> | null,
  focusedEdgePairs: Set<string>,
  expandedIds: Set<number> = new Set(),
): { nodes: Node[]; edges: Edge[] } {
  const shown = entities.filter((e) =>
    (typeSet.size === 0 || typeSet.has(e.type)) &&
    (nameFilter === "" || e.name.toLowerCase().includes(nameFilter.toLowerCase())),
  );
  const shownIds = new Set(shown.map((e) => e.id));
  const entityById = new Map(entities.map((entity) => [entity.id, entity]));
  const instanceTypeNames = new Set(entities.map((e) => e.type));
  const selectedAccentColor = selectedId == null
    ? "#4068A8"
    : typeColor(typeIndex.get(entityById.get(selectedId)?.type ?? "") ?? 0);

  const nodes = buildEntityNodes(
    shown,
    typeIndex,
    selectedId,
    selectedNeighborIds,
    pathIds,
    expandedIds,
    graphMode,
    focusedEntityIds,
  );

  nodes.push(...buildSchemaOnlyNodes(schemaOnlyTypes, instanceTypeNames, typeSet, nameFilter, typeIndex));

  const edges = buildGraphEdges(
    rels,
    shownIds,
    selectedId,
    selectedEdgeKeys,
    pathIds,
    graphMode,
    focusedEntityIds,
    focusedEdgePairs,
    selectedAccentColor,
  );

  return autoLayout(nodes, edges, "LR");
}
