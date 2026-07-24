"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow, Background, Controls, MiniMap, BaseEdge, EdgeLabelRenderer,
  getSmoothStepPath,
  useNodesState, useEdgesState, MarkerType,
  type Node, type Edge, type EdgeProps, type EdgeTypes, type ReactFlowInstance,
} from "@xyflow/react";
import type { CSSProperties } from "react";
import "@xyflow/react/dist/style.css";
import {
  AlertCircle, GitMerge, Loader2, RefreshCw, Search, X,
} from "lucide-react";
import { api } from "@/lib/api";
import { autoLayout } from "@/lib/canvasLayout";
import { typeColor } from "@/lib/typeColor";
import { cn } from "@/lib/cn";

type EntityNode = {
  id: number; type: string; name: string;
  attributes?: Record<string, unknown>;
};
type EntityRel = { source: number; target: number; name: string };
type OverviewNode = { id: string; type: string; count: number; entity_ids: number[] };
type OverviewEdge = { source: string; target: string; name: string; count: number };
type GraphOverview = {
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
type GraphMode = "overview" | "focused" | "full";
type TruncatedEdgeData = Record<string, unknown> & {
  label: string;
  title: string;
  labelColor: string;
  labelFontWeight: number;
  labelOpacity: number;
  labelBackground: string;
  labelBackgroundOpacity: number;
};
type TruncatedEdge = Edge<TruncatedEdgeData, "truncatedSmoothstep">;
type NeighborNode = {
  id: number;
  type: string;
  name: string;
  attributes?: Record<string, unknown>;
  relationship: string;
  direction: "in" | "out";
};

const NODE_WIDTH = 160;
const OVERVIEW_NODE_WIDTH = 190;
const MAX_EDGE_LABEL_WIDTH = 180;
const clippedTextStyle: CSSProperties = {
  display: "block",
  maxWidth: "100%",
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
};

function clippedLineStyle(style: CSSProperties): CSSProperties {
  return { ...clippedTextStyle, ...style };
}

function TruncatedSmoothStepEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  markerEnd,
  style,
  data,
  pathOptions,
}: EdgeProps<TruncatedEdge>) {
  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
    ...pathOptions,
  });
  const label = data?.label ?? "";

  return (
    <>
      <BaseEdge id={id} path={edgePath} markerEnd={markerEnd} style={style} />
      {label ? (
        <EdgeLabelRenderer>
          <div
            title={data?.title}
            style={{
              position: "absolute",
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
              maxWidth: MAX_EDGE_LABEL_WIDTH,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
              borderRadius: 6,
              background: hexToRgba(data?.labelBackground ?? "#ffffff", data?.labelBackgroundOpacity ?? 1),
              opacity: data?.labelOpacity,
              padding: "2px 4px",
              color: data?.labelColor,
              fontSize: 10,
              fontWeight: data?.labelFontWeight,
              lineHeight: 1.2,
              pointerEvents: "all",
            }}
          >
            {label}
          </div>
        </EdgeLabelRenderer>
      ) : null}
    </>
  );
}

const edgeTypes: EdgeTypes = {
  truncatedSmoothstep: TruncatedSmoothStepEdge,
};

function resolveFocusSourceEntityIds(
  focusedEntityIds: Set<number> | null,
  domainEntityIds: Set<number>,
): Set<number> | null {
  if (focusedEntityIds && focusedEntityIds.size > 0) return focusedEntityIds;
  return domainEntityIds.size > 0 ? domainEntityIds : null;
}

interface DetailPanelProps {
  entity: EntityNode;
  neighbors: NeighborNode[];
  loading: boolean;
  error: string | null;
  onClose: () => void;
  onNavigate: (neighbor: NeighborNode) => void;
  onExpandOnCanvas: (entityId: number, neighbors: NeighborNode[]) => void;
}

function formatAttributeValue(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function DetailPanel({
  entity,
  neighbors,
  loading,
  error,
  onClose,
  onNavigate,
  onExpandOnCanvas,
}: DetailPanelProps) {
  const attributes = entity.attributes ?? {};
  const hasAttributes = Object.keys(attributes).length > 0;

  return (
    <div className="absolute right-0 top-0 bottom-0 z-10 w-72 border-l border-navy-100 bg-white shadow-soft flex flex-col">
      <div className="flex items-start justify-between gap-2 border-b border-navy-100 px-4 py-3">
        <div className="min-w-0">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-steel-500">{entity.type}</div>
          <h3 className="truncate font-semibold text-navy-900">{entity.name}</h3>
          <div className="text-[10px] text-subtle">id:{entity.id}</div>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {!loading && neighbors.length > 0 && (
            <button
              type="button"
              title="Show all connections for this node on the canvas"
              onClick={() => onExpandOnCanvas(entity.id, neighbors)}
              className="focus-ring flex items-center gap-1 rounded-md border border-steel-200 bg-steel-50 px-2 py-1 text-[10px] font-medium text-steel-700 hover:bg-steel-100"
            >
              <GitMerge size={10} />
              Expand
            </button>
          )}
          <button type="button" onClick={onClose}
            className="focus-ring rounded-md p-1 text-subtle hover:bg-navy-50">
            <X size={14} />
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
        <div>
          <div className="mb-2 text-[10px] font-bold uppercase tracking-wider text-navy-500">Attributes</div>
          {loading && !hasAttributes ? (
            <div className="flex items-center gap-1 text-[12px] text-subtle">
              <Loader2 size={11} className="animate-spin" />Loading details…
            </div>
          ) : hasAttributes ? (
            <div className="space-y-1">
              {Object.entries(attributes).map(([k, v]) => (
                <div key={k} className="rounded-lg bg-navy-50 px-2.5 py-1.5">
                  <div className="text-[10px] text-subtle">{k}</div>
                  <div className="whitespace-pre-wrap break-words text-[12px] text-navy-800">
                    {formatAttributeValue(v)}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="rounded-lg border border-dashed border-navy-100 bg-navy-50/50 px-2.5 py-2 text-[12px] italic text-subtle">
              No attributes available for this node.
            </div>
          )}
        </div>
        <div>
          <div className="mb-2 text-[10px] font-bold uppercase tracking-wider text-navy-500">
            Neighbors {loading ? "…" : `(${neighbors.length})`}
          </div>
          {loading ? (
            <div className="flex items-center gap-1 text-[12px] text-subtle">
              <Loader2 size={11} className="animate-spin" />Loading…
            </div>
          ) : error ? (
            <div className="rounded-lg border border-rose-100 bg-rose-50 px-2.5 py-2 text-[12px] text-rose-700">
              {error}
            </div>
          ) : neighbors.length === 0 ? (
            <div className="text-[12px] text-subtle italic">No connections</div>
          ) : (
            <ul className="space-y-1">
              {neighbors.map((n) => (
                <li key={`${n.id}-${n.relationship}-${n.direction}`}>
                  <button
                    type="button"
                    onClick={() => onNavigate(n)}
                    className="focus-ring w-full rounded-lg border border-navy-100 px-2.5 py-1.5 text-left hover:bg-navy-50"
                  >
                    <div className="text-[10px] text-steel-500">{n.type} · {n.relationship}</div>
                    <div className="truncate text-[12px] font-medium text-navy-800">{n.name}</div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}

interface PathFinderProps {
  entities: EntityNode[];
  workspaceId: number;
  onPath: (ids: number[]) => void;
}

function PathFinder({ entities, workspaceId, onPath }: PathFinderProps) {
  const [from, setFrom] = useState<number | null>(null);
  const [to, setTo] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const find = async () => {
    if (!from || !to) return;
    setLoading(true); setError(null);
    try {
      const path = await api.getEntityPath(from, to, workspaceId);
      onPath(path.map((e) => e.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "No path found");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex items-end gap-2">
      <div>
        <label className="mb-0.5 block text-[10px] font-medium text-navy-600">From</label>
        <select
          value={from ?? ""}
          onChange={(e) => setFrom(Number(e.target.value) || null)}
          className="focus-ring w-40 rounded-lg border border-navy-100 bg-white px-2 py-1.5 text-[12px]"
        >
          <option value="">Select…</option>
          {entities.map((e) => (
            <option key={e.id} value={e.id}>{e.name} ({e.type})</option>
          ))}
        </select>
      </div>
      <div>
        <label className="mb-0.5 block text-[10px] font-medium text-navy-600">To</label>
        <select
          value={to ?? ""}
          onChange={(e) => setTo(Number(e.target.value) || null)}
          className="focus-ring w-40 rounded-lg border border-navy-100 bg-white px-2 py-1.5 text-[12px]"
        >
          <option value="">Select…</option>
          {entities.map((e) => (
            <option key={e.id} value={e.id}>{e.name} ({e.type})</option>
          ))}
        </select>
      </div>
      <button
        type="button"
        onClick={find}
        disabled={!from || !to || loading}
        className="focus-ring inline-flex items-center gap-1 rounded-lg bg-steel-500 px-3 py-1.5 text-[12px] font-medium text-white hover:bg-steel-600 disabled:opacity-50"
      >
        {loading ? <Loader2 size={11} className="animate-spin" /> : null}
        Find path
      </button>
      {error && <span className="text-[11px] text-rose-600">{error}</span>}
    </div>
  );
}

// ── Build ReactFlow nodes / edges ─────────────────────────────────────────────

function edgeKey(source: number, target: number, name: string): string {
  return `${source}->${target}:${name}`;
}

function edgePairKey(source: number, target: number): string {
  return `${Math.min(source, target)}::${Math.max(source, target)}`;
}

function hexToRgba(hex: string, alpha: number): string {
  const normalized = hex.replace("#", "");
  const safeHex = normalized.length === 3
    ? normalized.split("").map((char) => `${char}${char}`).join("")
    : normalized;
  const int = Number.parseInt(safeHex, 16);
  const r = (int >> 16) & 255;
  const g = (int >> 8) & 255;
  const b = int & 255;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function buildGraph(
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
  const hasSelection = selectedId !== null;
  const selectionContextActive = hasSelection;
  const focusActive = graphMode === "focused" && focusedEntityIds !== null && focusedEntityIds.size > 0;
  const selectedAccentColor = selectedId == null
    ? "#4068A8"
    : typeColor(typeIndex.get(entityById.get(selectedId)?.type ?? "") ?? 0);

  const nodes: Node[] = shown.map((e) => {
    const idx = typeIndex.get(e.type) ?? 0;
    const color = typeColor(idx);
    const isSelected = selectedId === e.id;
    const isNeighbor = !isSelected && selectedNeighborIds.has(e.id);
    const pathHighlighted = !hasSelection && pathIds.size > 0 && pathIds.has(e.id);
    const isExpanded = expandedIds.has(e.id);
    const isContextNode = isSelected || isNeighbor;
    const isFocusMatched = focusActive && focusedEntityIds.has(e.id);
    const isDimmed = selectionContextActive
      ? !isContextNode
      : focusActive && !isFocusMatched;
    const background = isSelected
      ? hexToRgba(color, 0.18)
      : isNeighbor
        ? hexToRgba(color, 0.08)
        : pathHighlighted
          ? "#fef3c7"
          : isFocusMatched
            ? hexToRgba(color, 0.08)
            : "#ffffff";
    const borderWidth = isSelected ? 4 : isNeighbor ? 3 : isExpanded ? 3 : 2;
    const typeLabelColor = isSelected ? "#0F1726" : isContextNode ? "#334155" : color;
    const nodeOpacity = selectionContextActive
      ? isSelected ? 1 : isNeighbor ? 0.96 : isDimmed ? 0.12 : 0.72
      : focusActive && !isFocusMatched ? 0.42 : 1;
    const boxShadow = isSelected
      ? `0 0 0 6px ${hexToRgba(color, 0.28)}, 0 14px 30px rgba(15, 23, 38, 0.18)`
      : isNeighbor
        ? `0 0 0 4px ${hexToRgba(color, 0.18)}, 0 8px 18px rgba(15, 23, 38, 0.12)`
        : pathHighlighted
          ? `0 0 0 3px ${hexToRgba(color, 0.18)}, 0 2px 8px rgba(0,0,0,0.12)`
          : isFocusMatched
            ? `0 0 0 3px rgba(45, 212, 191, 0.18), 0 4px 12px rgba(15, 23, 38, 0.08)`
          : isExpanded
            ? `0 0 0 3px ${hexToRgba(color, 0.16)}, 0 2px 8px rgba(0,0,0,0.10)`
            : "0 1px 4px rgba(0,0,0,0.08)";
    return {
      id: String(e.id),
      type: "default",
      data: {
        label: (
          <div style={{ textAlign: "center", lineHeight: 1.3, minWidth: 0, overflow: "hidden", width: "100%" }}>
            <div
              title={e.name}
              style={clippedLineStyle({
                fontWeight: isSelected || pathHighlighted ? 700 : 600,
                fontSize: 11,
                color: "#0F1726",
              })}
            >
              {e.name}
            </div>
            <div
              title={e.type}
              style={clippedLineStyle({ fontSize: 10, color: typeLabelColor, marginTop: 1 })}
            >
              {e.type}
            </div>
            {isExpanded && (
              <div style={{ fontSize: 9, color: "#64748b", marginTop: 2 }}>expanded</div>
            )}
          </div>
        ),
      },
      position: { x: 0, y: 0 },
      style: {
        background,
        border: `${borderWidth}px solid ${color}`,
        borderRadius: 8,
        padding: "6px 10px",
        width: NODE_WIDTH,
        overflow: "hidden",
        boxSizing: "border-box",
        boxShadow,
        opacity: nodeOpacity,
      },
    };
  });

  // Add schema-only type nodes for ontology types that have no entity instances
  for (const typeName of schemaOnlyTypes) {
    if (instanceTypeNames.has(typeName)) continue;
    if (typeSet.size > 0 && !typeSet.has(typeName)) continue;
    if (nameFilter !== "" && !typeName.toLowerCase().includes(nameFilter.toLowerCase())) continue;
    const idx = typeIndex.get(typeName) ?? 0;
    const color = typeColor(idx);
    nodes.push({
      id: `schema::${typeName}`,
      type: "default",
      data: {
        label: (
          <div style={{ textAlign: "center", lineHeight: 1.3, minWidth: 0, overflow: "hidden", width: "100%" }}>
            <div
              title={typeName}
              style={clippedLineStyle({
                fontWeight: 500,
                fontSize: 11,
                color: "#64748b",
                fontStyle: "italic",
              })}
            >
              {typeName}
            </div>
            <div style={{ fontSize: 9, color, marginTop: 1, opacity: 0.7 }}>
              no instances yet
            </div>
          </div>
        ),
      },
      position: { x: 0, y: 0 },
      style: {
        background: "#f8fafc",
        border: `2px dashed ${color}`,
        borderRadius: 8,
        padding: "6px 10px",
        width: NODE_WIDTH,
        overflow: "hidden",
        boxSizing: "border-box",
        boxShadow: "none",
        opacity: 0.75,
      },
    });
  }

  const edges: Edge[] = rels
    .filter((r) => shownIds.has(r.source) && shownIds.has(r.target))
    .map((r, i) => {
      const selectedEdge = hasSelection && selectedEdgeKeys.has(edgeKey(r.source, r.target, r.name));
      const highlighted = !hasSelection && pathIds.has(r.source) && pathIds.has(r.target);
      const focusHighlighted = focusActive &&
        focusedEntityIds.has(r.source) &&
        focusedEntityIds.has(r.target) &&
        focusedEdgePairs.has(edgePairKey(r.source, r.target));
      const stroke = selectedEdge
        ? selectedAccentColor
        : highlighted
          ? "#D97706"
          : focusHighlighted
            ? "#0F9D8B"
            : "#4068A8";
      return {
        id: `e${r.source}-${r.target}-${i}`,
        source: String(r.source),
        target: String(r.target),
        type: "truncatedSmoothstep",
        animated: selectedEdge || highlighted || focusHighlighted,
        style: {
          stroke,
          strokeWidth: selectedEdge ? 3.8 : highlighted ? 2.5 : focusHighlighted ? 2.3 : 1.5,
          opacity: selectionContextActive ? (selectedEdge ? 1 : 0.1) : focusActive && !focusHighlighted ? 0.18 : 1,
        },
        data: {
          label: r.name,
          title: r.name,
          labelColor: selectedEdge ? "#0F1726" : "#334155",
          labelFontWeight: selectedEdge ? 700 : 500,
          labelOpacity: selectionContextActive ? (selectedEdge ? 1 : 0.18) : focusActive && !focusHighlighted ? 0.38 : 1,
          labelBackground: selectedEdge ? "#ffffff" : "#f8fafc",
          labelBackgroundOpacity: selectionContextActive ? (selectedEdge ? 0.98 : 0.18) : focusActive && !focusHighlighted ? 0.4 : 0.9,
        } satisfies TruncatedEdgeData,
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: stroke,
          width: 14,
          height: 14,
        },
      };
    });

  return autoLayout(nodes, edges, "LR");
}

function buildOverviewGraph(
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
// ── Main component ─────────────────────────────────────────────────────────────

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
  const modeButtonClass = (mode: GraphMode) => cn(
    "focus-ring rounded-lg border px-2.5 py-1.5 text-[11px] font-medium shadow-soft backdrop-blur-sm transition-colors",
    graphMode === mode
      ? "border-teal-200 bg-teal-50 text-teal-800"
      : "border-navy-100 bg-white/90 text-navy-700 hover:bg-navy-50",
  );

  return (
    <div className="relative flex flex-1 overflow-hidden">
      <div className="absolute top-3 left-3 z-10 flex w-[248px] flex-col gap-2">
        <div className="rounded-xl border border-navy-100 bg-white/90 p-2 shadow-soft backdrop-blur-sm">
          <div className="mb-2 px-1 text-[10px] font-bold uppercase tracking-wider text-navy-500">Graph mode</div>
          <div className="flex flex-wrap gap-1">
            <button type="button" onClick={resetToOverview} className={modeButtonClass("overview")}>
              Overview
            </button>
            <button
              type="button"
              onClick={() => {
                if (!hasFocusSource) return;
                fitOnNextRender.current = true;
                setGraphMode("focused");
                clearSelection();
              }}
              disabled={!hasFocusSource}
              className={cn(modeButtonClass("focused"), !hasFocusSource && "opacity-50")}
            >
              Focused
            </button>
            <button
              type="button"
              onClick={() => {
                fitOnNextRender.current = true;
                setGraphMode("full");
              }}
              className={modeButtonClass("full")}
            >
              Full View
            </button>
          </div>
        </div>

        {!panelEntity && graphMode !== "overview" && (
          <div className="flex items-center gap-2 rounded-xl border border-navy-100 bg-white/90 px-3 py-2 shadow-soft backdrop-blur-sm">
            <Search size={13} className="text-subtle" />
            <input
              value={nameFilter}
              onChange={(e) => { setNameFilter(e.target.value); clearSelection(); }}
              placeholder="Search entities…"
              className="min-w-0 flex-1 bg-transparent text-[12px] text-navy-800 outline-none placeholder:text-subtle"
            />
            {nameFilter && (
              <button type="button" onClick={() => setNameFilter("")}
                className="text-subtle hover:text-navy-700"><X size={11} /></button>
            )}
          </div>
        )}

        {!panelEntity && graphMode !== "overview" && (
          <div className="rounded-xl border border-navy-100 bg-white/90 p-2 shadow-soft backdrop-blur-sm max-h-52 overflow-y-auto">
            <div className="mb-1 px-1 text-[10px] font-bold uppercase tracking-wider text-navy-500">Filter by type</div>
            {allTypes.map((t, i) => {
              const isSchemaOnly = !allEntities.some((e) => e.type === t);
              return (
                <button
                  key={t}
                  type="button"
                  onClick={() => toggleType(t)}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-lg px-2 py-1 text-[11px] font-medium transition-colors",
                    typeFilter.size > 0 && !typeFilter.has(t) ? "text-subtle" : "text-navy-800",
                  )}
                >
                  <span className="size-2.5 rounded-full shrink-0"
                    style={{ background: isSchemaOnly ? "transparent" : typeColor(i), border: `2px ${isSchemaOnly ? "dashed" : "solid"} ${typeColor(i)}` }} />
                  <span className={isSchemaOnly ? "italic text-subtle" : ""}>{t}</span>
                </button>
              );
            })}
            {typeFilter.size > 0 && (
              <button type="button" onClick={() => setTypeFilter(new Set())}
                className="mt-1 w-full rounded-lg px-2 py-1 text-[10px] text-steel-600 hover:bg-steel-50">
                Clear filter
              </button>
            )}
          </div>
        )}

        {!panelEntity && (
          <div className="rounded-xl border border-navy-100 bg-white/90 px-3 py-2 shadow-soft backdrop-blur-sm text-[11px] text-subtle">
            {graphMode === "overview"
            ? `${visibleCount} overview node${visibleCount !== 1 ? "s" : ""} · ${edges.length} overview rel${edges.length !== 1 ? "s" : ""}`
            : `${visibleCount} / ${allEntities.length} entities · ${edges.length} rel${edges.length !== 1 ? "s" : ""}`}
          </div>
        )}

        {!panelEntity && (
          <div className="flex gap-1">
            <button type="button" onClick={load}
              className="focus-ring flex items-center gap-1 rounded-lg border border-navy-100 bg-white/90 px-2 py-1.5 text-[11px] text-navy-700 hover:bg-navy-50 shadow-soft backdrop-blur-sm">
              <RefreshCw size={11} /> Reload
            </button>
            {showPathTools && (
              <button type="button" onClick={() => { setShowPath((v) => !v); setPathIds(new Set()); }}
                className={cn(
                  "focus-ring flex items-center gap-1 rounded-lg border px-2 py-1.5 text-[11px] shadow-soft backdrop-blur-sm",
                  showPath ? "border-steel-200 bg-steel-50 text-steel-700" : "border-navy-100 bg-white/90 text-navy-700 hover:bg-navy-50",
                )}>
                Path finder
              </button>
            )}
          </div>
        )}

        {!panelEntity && showPathTools && showPath && (
          <div className="rounded-xl border border-navy-100 bg-white/90 p-3 shadow-soft backdrop-blur-sm">
            <PathFinder
              entities={allEntities}
              workspaceId={workspaceId}
              onPath={(ids) => setPathIds(new Set(ids))}
            />
            {pathIds.size > 0 && (
              <button type="button" onClick={() => setPathIds(new Set())}
                className="mt-2 text-[10px] text-subtle hover:text-navy-700">
                Clear path
              </button>
            )}
          </div>
        )}
      </div>

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
