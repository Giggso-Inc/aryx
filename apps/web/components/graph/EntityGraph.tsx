"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow, Background, Controls, MiniMap,
  useNodesState, useEdgesState, MarkerType,
  type Node, type Edge, type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { AlertCircle, Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { edgeTypes } from "./entity-graph/TruncatedEdge";
import { DetailPanel } from "./entity-graph/DetailPanel";
import { GraphSidebar } from "./entity-graph/GraphSidebar";
import { buildGraph, resolveFocusSourceEntityIds } from "./entity-graph/build-graph";
import { buildOverviewGraph } from "./entity-graph/build-overview-graph";
import { edgeKey, edgePairKey } from "./entity-graph/build-graph-edges";
import type {
  EntityNode, EntityRel, GraphMode, GraphOverview, NeighborNode,
} from "./entity-graph/types";

export function EntityGraph({ workspaceId }: { workspaceId: number }) {
  const rfInstance = useRef<ReactFlowInstance | null>(null);
  const fitOnNextRender = useRef(true); // true only after a full load or reload
  const detailRequestId = useRef(0);
  const [allEntities, setAllEntities] = useState<EntityNode[]>([]);
  const [allRels, setAllRels] = useState<EntityRel[]>([]);
  const [graphOverview, setGraphOverview] = useState<GraphOverview | null>(null);
  const [schemaTypes, setSchemaTypes] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [graphMode, setGraphMode] = useState<GraphMode>("overview");
  const [focusedEntityIds, setFocusedEntityIds] = useState<Set<number> | null>(null);
  const [typeFilter, setTypeFilter] = useState<Set<string>>(new Set());
  const [nameFilter, setNameFilter] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [selectedEntity, setSelectedEntity] = useState<EntityNode | null>(null);
  const [selectedNeighbors, setSelectedNeighbors] = useState<NeighborNode[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [pathIds, setPathIds] = useState<Set<number>>(new Set());
  const [showPath, setShowPath] = useState(false);
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  const clearSelection = useCallback(() => {
    detailRequestId.current += 1;
    setSelectedId(null);
    setSelectedEntity(null);
    setSelectedNeighbors([]);
    setDetailLoading(false);
    setDetailError(null);
  }, []);

  const focusOverviewSelection = useCallback((entityIds: number[]) => {
    fitOnNextRender.current = true;
    setFocusedEntityIds(new Set(entityIds));
    setGraphMode("focused");
    clearSelection();
    setPathIds(new Set());
  }, [clearSelection]);

  const resetToOverview = useCallback(() => {
    fitOnNextRender.current = true;
    setGraphMode("overview");
    setFocusedEntityIds(null);
    setPathIds(new Set());
    clearSelection();
  }, [clearSelection]);

  const mergeEntities = useCallback((entitiesToMerge: EntityNode[]) => {
    if (entitiesToMerge.length === 0) return;
    setAllEntities((prev) => {
      const next = [...prev];
      const indexById = new Map(next.map((entity, index) => [entity.id, index]));
      for (const entity of entitiesToMerge) {
        const existingIndex = indexById.get(entity.id);
        if (existingIndex == null) {
          indexById.set(entity.id, next.length);
          next.push(entity);
          continue;
        }
        const existing = next[existingIndex];
        next[existingIndex] = {
          ...existing,
          ...entity,
          attributes: entity.attributes ?? existing.attributes,
        };
      }
      return next;
    });
  }, []);

  const appendRelationship = useCallback((relationship: EntityRel) => {
    setAllRels((prev) => (
      prev.some((existing) => (
        existing.source === relationship.source &&
        existing.target === relationship.target &&
        existing.name === relationship.name
      ))
        ? prev
        : [...prev, relationship]
    ));
  }, []);

  // allTypes includes entity instance types; schema-only types are included
  // only when the workspace has at least one ingested entity so that a fresh
  // empty workspace shows nothing instead of ontology placeholder nodes.
  const allTypes = useMemo(() => {
    const s = new Set([
      ...allEntities.map((e) => e.type),
      ...(allEntities.length > 0 ? schemaTypes : []),
    ]);
    return [...s].sort();
  }, [allEntities, schemaTypes]);

  const typeIndex = useMemo(() => {
    const m = new Map<string, number>();
    allTypes.forEach((t, i) => m.set(t, i));
    return m;
  }, [allTypes]);

  const selectedSummary = useMemo(() => (
    selectedId == null
      ? null
      : allEntities.find((entity) => entity.id === selectedId) ?? null
  ), [allEntities, selectedId]);

  const panelEntity = selectedEntity ?? selectedSummary;

  const selectedNeighborIds = useMemo(() => (
    new Set(selectedNeighbors.map((neighbor) => neighbor.id))
  ), [selectedNeighbors]);

  const selectedEdgeKeys = useMemo(() => {
    if (selectedId == null) return new Set<string>();
    return new Set(selectedNeighbors.map((neighbor) => (
      neighbor.direction === "out"
        ? edgeKey(selectedId, neighbor.id, neighbor.relationship)
        : edgeKey(neighbor.id, selectedId, neighbor.relationship)
    )));
  }, [selectedId, selectedNeighbors]);

  const overviewNodeById = useMemo(() => (
    new Map((graphOverview?.overview_nodes ?? []).map((node) => [node.id, node]))
  ), [graphOverview]);

  const domainEntityIds = useMemo(() => (
    new Set(graphOverview?.matched_entity_ids ?? [])
  ), [graphOverview]);

  const domainEdgePairs = useMemo(() => (
    new Set((graphOverview?.matched_edge_pairs ?? []).map((edge) => edgePairKey(edge.source, edge.target)))
  ), [graphOverview]);

  const focusSourceEntityIds = useMemo(() => (
    resolveFocusSourceEntityIds(focusedEntityIds, domainEntityIds)
  ), [domainEntityIds, focusedEntityIds]);

  const load = useCallback(async () => {
    fitOnNextRender.current = true; // full reload → fit the new graph
    setLoading(true); setError(null);
    try {
      const [g, onto, overview] = await Promise.all([
        api.getEntityGraph(workspaceId),
        api.getOntology(workspaceId).catch(() => ({ types: [], relationships: [] })),
        api.getEntityGraphOverview(workspaceId),
      ]);
      setAllEntities(g.entities);
      setAllRels(g.relationships);
      setGraphOverview(overview);
      // Collect approved ontology type names to show as schema nodes when no instances exist
      const approvedNames = (onto.types ?? [])
        .filter((t) => !t.status || t.status === "approved")
        .map((t) => t.name);
      setSchemaTypes(approvedNames);
      setGraphMode("overview");
      setFocusedEntityIds(null);
      setPathIds(new Set());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load graph");
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    clearSelection();
    setGraphMode("overview");
    setFocusedEntityIds(null);
  }, [clearSelection, workspaceId]);

  const selectEntity = useCallback(async (id: number, preloadedEntity?: EntityNode) => {
    const requestId = detailRequestId.current + 1;
    detailRequestId.current = requestId;
    const summary = preloadedEntity ?? allEntities.find((entity) => entity.id === id) ?? null;

    setSelectedId(id);
    setSelectedEntity(summary);
    setSelectedNeighbors([]);
    setDetailError(null);
    setDetailLoading(true);
    setPathIds(new Set());

    try {
      const [entity, neighbors] = await Promise.all([
        preloadedEntity ? Promise.resolve(preloadedEntity) : api.getEntity(id, workspaceId),
        api.getEntityNeighbors(id, workspaceId),
      ]);

      if (detailRequestId.current !== requestId) return;

      mergeEntities([
        entity,
        ...neighbors.map((neighbor) => ({
          id: neighbor.id,
          type: neighbor.type,
          name: neighbor.name,
          attributes: neighbor.attributes,
        })),
      ]);
      setSelectedEntity(entity);
      setSelectedNeighbors(neighbors);
    } catch (e) {
      if (detailRequestId.current !== requestId) return;
      setSelectedEntity(summary);
      setSelectedNeighbors([]);
      setDetailError(e instanceof Error ? e.message : "Failed to load node details.");
    } finally {
      if (detailRequestId.current === requestId) {
        setDetailLoading(false);
      }
    }
  }, [allEntities, mergeEntities, workspaceId]);

  // Rebuild graph whenever filters or data changes, then fit view
  useEffect(() => {
    if (loading) return;
    if (allEntities.length === 0) return;
    const effectiveFocusedEntityIds = graphMode === "focused"
      ? focusSourceEntityIds
      : null;
    const graphData = graphMode === "overview" && graphOverview
      ? buildOverviewGraph(graphOverview.overview_nodes, graphOverview.overview_edges, typeIndex)
      : buildGraph(
        allEntities,
        allRels,
        typeFilter,
        nameFilter,
        selectedId,
        selectedNeighborIds,
        selectedEdgeKeys,
        pathIds,
        typeIndex,
        [],
        graphMode,
        effectiveFocusedEntityIds,
        domainEdgePairs,
        expandedIds,
      );
    const { nodes: n, edges: e } = graphData;
    setNodes(n);
    setEdges(e);
    // fitView only on full load/reload — not on incremental expand or filter changes.
    if (fitOnNextRender.current) {
      fitOnNextRender.current = false;
      setTimeout(() => {
        rfInstance.current?.fitView({ padding: 0.15, duration: 300 });
      }, 80);
    }
  }, [
    allEntities,
    allRels,
    schemaTypes,
    typeFilter,
    nameFilter,
    selectedId,
    selectedNeighborIds,
    selectedEdgeKeys,
    pathIds,
    typeIndex,
    graphMode,
    graphOverview,
    domainEntityIds,
    domainEdgePairs,
    focusSourceEntityIds,
    expandedIds,
    loading,
    setNodes,
    setEdges,
  ]);

  const onNodeClick = useCallback((_: unknown, node: Node) => {
    if (node.id.startsWith("overview::")) {
      const overviewNode = overviewNodeById.get(node.id);
      if (overviewNode && overviewNode.entity_ids.length > 0) {
        focusOverviewSelection(overviewNode.entity_ids);
      }
      return;
    }
    // schema:: nodes are type placeholders — not selectable entity instances
    if (node.id.startsWith("schema::")) return;
    void selectEntity(Number(node.id));
  }, [focusOverviewSelection, overviewNodeById, selectEntity]);

  // Expand a node's 1-hop neighbors onto the canvas — adds missing entities and edges.
  // Called from the "Expand" button in the sidebar so there's no double-click race condition.
  const expandOnCanvas = useCallback((
    entityId: number,
    neighbors: NeighborNode[],
  ) => {
    setExpandedIds((prev) => new Set([...prev, entityId]));
    mergeEntities(neighbors.map((neighbor) => ({
      id: neighbor.id,
      type: neighbor.type,
      name: neighbor.name,
      attributes: neighbor.attributes,
    })));
    neighbors.forEach((neighbor) => {
      appendRelationship(
        neighbor.direction === "out"
          ? { source: entityId, target: neighbor.id, name: neighbor.relationship }
          : { source: neighbor.id, target: entityId, name: neighbor.relationship },
      );
    });
  }, [appendRelationship, mergeEntities]);

  const navigateTo = useCallback(async (neighbor: NeighborNode) => {
    let resolvedEntity: EntityNode | undefined;
    const isOnCanvas = allEntities.some((entity) => entity.id === neighbor.id);

    if (!isOnCanvas) {
      try {
        resolvedEntity = await api.getEntity(neighbor.id, workspaceId);
      } catch {
        resolvedEntity = {
          id: neighbor.id,
          type: neighbor.type,
          name: neighbor.name,
          attributes: neighbor.attributes,
        };
      }

      mergeEntities([resolvedEntity]);
      if (selectedId != null) {
        appendRelationship(
          neighbor.direction === "out"
            ? { source: selectedId, target: neighbor.id, name: neighbor.relationship }
            : { source: neighbor.id, target: selectedId, name: neighbor.relationship },
        );
      }
    }

    await selectEntity(neighbor.id, resolvedEntity);
  }, [allEntities, appendRelationship, mergeEntities, selectEntity, selectedId, workspaceId]);

  const toggleType = (t: string) => {
    setTypeFilter((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t); else next.add(t);
      return next;
    });
  };

  if (loading) return (
    <div className="flex flex-1 items-center justify-center gap-2 text-[13px] text-subtle">
      <Loader2 size={14} className="animate-spin" /> Loading entity graph…
    </div>
  );

  if (error) return (
    <div className="flex flex-1 items-center justify-center">
      <div className="flex items-center gap-2 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-[13px] text-rose-700">
        <AlertCircle size={14} /> {error}
        <button type="button" onClick={load} className="ml-2 underline">Retry</button>
      </div>
    </div>
  );

  if (allEntities.length === 0) return (
    <div className="flex flex-1 items-center justify-center text-[13px] text-subtle">
      No entities in this workspace yet. Ingest some data first.
    </div>
  );

  const visibleCount = nodes.length;
  const showPathTools = graphMode !== "overview";
  const hasFocusSource = focusSourceEntityIds !== null;

  return (
    <div className="relative flex flex-1 overflow-hidden">
      <GraphSidebar
        graphMode={graphMode}
        hasFocusSource={hasFocusSource}
        onResetOverview={resetToOverview}
        onSetFocused={() => {
          if (!hasFocusSource) return;
          fitOnNextRender.current = true;
          setGraphMode("focused");
          clearSelection();
        }}
        onSetFull={() => {
          fitOnNextRender.current = true;
          setGraphMode("full");
        }}
        panelEntity={panelEntity}
        nameFilter={nameFilter}
        onNameFilterChange={(value) => { setNameFilter(value); clearSelection(); }}
        allTypes={allTypes}
        allEntities={allEntities}
        typeFilter={typeFilter}
        onToggleType={toggleType}
        onClearTypeFilter={() => setTypeFilter(new Set())}
        visibleCount={visibleCount}
        edgesCount={edges.length}
        onReload={load}
        showPathTools={showPathTools}
        showPath={showPath}
        onTogglePath={() => { setShowPath((v) => !v); setPathIds(new Set()); }}
        pathIds={pathIds}
        onClearPath={() => setPathIds(new Set())}
        workspaceId={workspaceId}
        onPath={(ids) => setPathIds(new Set(ids))}
      />

      <div className={cn("flex-1", graphMode !== "overview" && panelEntity ? "mr-72" : "")}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={onNodeClick}
          onInit={(instance) => { rfInstance.current = instance; }}
          edgeTypes={edgeTypes}
          minZoom={0.05}
          maxZoom={3}
          proOptions={{ hideAttribution: true }}
          className="bg-canvas"
          defaultEdgeOptions={{
            type: "smoothstep",
            style: { stroke: "#4068A8", strokeWidth: 1.5 },
            markerEnd: { type: MarkerType.ArrowClosed, color: "#4068A8", width: 14, height: 14 },
          }}
        >
          <Background color="#CBD5E1" gap={20} size={1} />
          <Controls showInteractive={false} />
          <MiniMap
            nodeColor={(n) => {
              const borderStyle = n.style?.border as string | undefined;
              return borderStyle?.match(/(#[0-9A-Fa-f]{6})/)?.[1] ?? "#4068A8";
            }}
            maskColor="rgba(248,249,252,0.8)"
            className="!bottom-3 !right-3"
          />
        </ReactFlow>
      </div>

      {graphMode !== "overview" && panelEntity && (
        <DetailPanel
          entity={panelEntity}
          neighbors={selectedNeighbors}
          loading={detailLoading}
          error={detailError}
          onClose={clearSelection}
          onNavigate={navigateTo}
          onExpandOnCanvas={expandOnCanvas}
        />
      )}
    </div>
  );
}
