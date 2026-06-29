"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ReactFlow, Background, Controls, MiniMap,
  useNodesState, useEdgesState, MarkerType,
  type Node, type Edge, type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  AlertCircle, ChevronDown, Loader2, RefreshCw, Search, X,
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

interface DetailPanelProps {
  entity: EntityNode;
  workspaceId: number;
  onClose: () => void;
  onNavigate: (id: number) => void;
}

function DetailPanel({ entity, workspaceId, onClose, onNavigate }: DetailPanelProps) {
  const [neighbors, setNeighbors] = useState<Array<{ id: number; type: string; name: string; relationship: string }>>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.getEntityNeighbors(entity.id, workspaceId)
      .then(setNeighbors)
      .catch(() => setNeighbors([]))
      .finally(() => setLoading(false));
  }, [entity.id, workspaceId]);

  return (
    <div className="absolute right-0 top-0 bottom-0 z-10 w-72 border-l border-navy-100 bg-white shadow-soft flex flex-col">
      <div className="flex items-start justify-between gap-2 border-b border-navy-100 px-4 py-3">
        <div className="min-w-0">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-steel-500">{entity.type}</div>
          <h3 className="truncate font-semibold text-navy-900">{entity.name}</h3>
          <div className="text-[10px] text-subtle">id:{entity.id}</div>
        </div>
        <button type="button" onClick={onClose}
          className="focus-ring rounded-md p-1 text-subtle hover:bg-navy-50">
          <X size={14} />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
        {entity.attributes && Object.keys(entity.attributes).length > 0 && (
          <div>
            <div className="mb-2 text-[10px] font-bold uppercase tracking-wider text-navy-500">Attributes</div>
            <div className="space-y-1">
              {Object.entries(entity.attributes).map(([k, v]) => (
                <div key={k} className="rounded-lg bg-navy-50 px-2.5 py-1.5">
                  <div className="text-[10px] text-subtle">{k}</div>
                  <div className="truncate text-[12px] text-navy-800">{String(v)}</div>
                </div>
              ))}
            </div>
          </div>
        )}
        <div>
          <div className="mb-2 text-[10px] font-bold uppercase tracking-wider text-navy-500">
            Neighbors {loading ? "…" : `(${neighbors.length})`}
          </div>
          {loading ? (
            <div className="flex items-center gap-1 text-[12px] text-subtle">
              <Loader2 size={11} className="animate-spin" />Loading…
            </div>
          ) : neighbors.length === 0 ? (
            <div className="text-[12px] text-subtle italic">No connections</div>
          ) : (
            <ul className="space-y-1">
              {neighbors.map((n) => (
                <li key={n.id}>
                  <button
                    type="button"
                    onClick={() => onNavigate(n.id)}
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

function buildGraph(
  entities: EntityNode[],
  rels: EntityRel[],
  typeSet: Set<string>,
  nameFilter: string,
  pathIds: Set<number>,
  typeIndex: Map<string, number>,
  schemaOnlyTypes: string[],
): { nodes: Node[]; edges: Edge[] } {
  const shown = entities.filter((e) =>
    (typeSet.size === 0 || typeSet.has(e.type)) &&
    (nameFilter === "" || e.name.toLowerCase().includes(nameFilter.toLowerCase())),
  );
  const shownIds = new Set(shown.map((e) => e.id));
  const instanceTypeNames = new Set(entities.map((e) => e.type));

  const nodes: Node[] = shown.map((e) => {
    const idx = typeIndex.get(e.type) ?? 0;
    const color = typeColor(idx);
    const highlighted = pathIds.size > 0 && pathIds.has(e.id);
    return {
      id: String(e.id),
      type: "default",
      data: {
        label: (
          <div style={{ textAlign: "center", lineHeight: 1.3 }}>
            <div style={{ fontWeight: highlighted ? 700 : 600, fontSize: 11, color: "#0F1726" }}>
              {e.name}
            </div>
            <div style={{ fontSize: 10, color: color, marginTop: 1 }}>
              {e.type}
            </div>
          </div>
        ),
      },
      position: { x: 0, y: 0 },
      style: {
        background: highlighted ? "#fef3c7" : "#ffffff",
        border: `2px solid ${color}`,
        borderRadius: 8,
        padding: "6px 10px",
        width: 160,
        boxShadow: highlighted
          ? `0 0 0 3px ${color}55, 0 2px 8px rgba(0,0,0,0.12)`
          : "0 1px 4px rgba(0,0,0,0.08)",
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
          <div style={{ textAlign: "center", lineHeight: 1.3 }}>
            <div style={{ fontWeight: 500, fontSize: 11, color: "#64748b", fontStyle: "italic" }}>
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
        width: 160,
        boxShadow: "none",
        opacity: 0.75,
      },
    });
  }

  const edges: Edge[] = rels
    .filter((r) => shownIds.has(r.source) && shownIds.has(r.target))
    .map((r, i) => {
      const highlighted = pathIds.has(r.source) && pathIds.has(r.target);
      return {
        id: `e${r.source}-${r.target}-${i}`,
        source: String(r.source),
        target: String(r.target),
        label: r.name,
        type: "smoothstep",
        animated: highlighted,
        style: {
          stroke: highlighted ? "#D97706" : "#4068A8",
          strokeWidth: highlighted ? 2.5 : 1.5,
        },
        labelStyle: { fill: "#334155", fontSize: 10, fontWeight: 500 },
        labelBgStyle: { fill: "#f8fafc", fillOpacity: 0.9 },
        labelBgPadding: [4, 2] as [number, number],
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: highlighted ? "#D97706" : "#4068A8",
          width: 14,
          height: 14,
        },
      };
    });

  return autoLayout(nodes, edges, "LR");
}

// ── Main component ─────────────────────────────────────────────────────────────

export function EntityGraph({ workspaceId }: { workspaceId: number }) {
  const rfInstance = useRef<ReactFlowInstance | null>(null);
  const [allEntities, setAllEntities] = useState<EntityNode[]>([]);
  const [allRels, setAllRels] = useState<EntityRel[]>([]);
  const [schemaTypes, setSchemaTypes] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState<Set<string>>(new Set());
  const [nameFilter, setNameFilter] = useState("");
  const [selected, setSelected] = useState<EntityNode | null>(null);
  const [pathIds, setPathIds] = useState<Set<number>>(new Set());
  const [showPath, setShowPath] = useState(false);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

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

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [g, onto] = await Promise.all([
        api.getEntityGraph(workspaceId),
        api.getOntology(workspaceId).catch(() => ({ types: [], relationships: [] })),
      ]);
      setAllEntities(g.entities);
      setAllRels(g.relationships);
      // Collect approved ontology type names to show as schema nodes when no instances exist
      const approvedNames = (onto.types ?? [])
        .filter((t) => !t.status || t.status === "approved")
        .map((t) => t.name);
      setSchemaTypes(approvedNames);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load graph");
    } finally {
      setLoading(false);
    }
  }, [workspaceId]);

  useEffect(() => { load(); }, [load]);

  // Rebuild graph whenever filters or data changes, then fit view
  useEffect(() => {
    if (loading) return;
    if (allEntities.length === 0) return;
    // Schema-only placeholder nodes only make sense in empty workspaces; suppress
    // them when real entity instances exist so they don't clutter the canvas.
    const { nodes: n, edges: e } = buildGraph(
      allEntities, allRels, typeFilter, nameFilter, pathIds, typeIndex, [],
    );
    setNodes(n);
    setEdges(e);
    // Fit view after React has had a chance to render the new nodes
    setTimeout(() => {
      rfInstance.current?.fitView({ padding: 0.15, duration: 300 });
    }, 80);
  }, [allEntities, allRels, schemaTypes, typeFilter, nameFilter, pathIds, typeIndex, loading, setNodes, setEdges]);

  const onNodeClick = useCallback((_: unknown, node: Node) => {
    // schema:: nodes are type placeholders — not selectable entity instances
    if (node.id.startsWith("schema::")) return;
    const entity = allEntities.find((e) => String(e.id) === node.id);
    if (entity) { setSelected(entity); setPathIds(new Set()); }
  }, [allEntities]);

  const navigateTo = (id: number) => {
    const entity = allEntities.find((e) => e.id === id);
    if (entity) setSelected(entity);
  };

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

  return (
    <div className="relative flex flex-1 overflow-hidden">
      {/* Toolbar */}
      <div className="absolute top-3 left-3 z-10 flex flex-col gap-2">
        {/* Search */}
        <div className="flex items-center gap-2 rounded-xl border border-navy-100 bg-white/90 px-3 py-2 shadow-soft backdrop-blur-sm">
          <Search size={13} className="text-subtle" />
          <input
            value={nameFilter}
            onChange={(e) => { setNameFilter(e.target.value); setSelected(null); }}
            placeholder="Search entities…"
            className="w-40 bg-transparent text-[12px] text-navy-800 outline-none placeholder:text-subtle"
          />
          {nameFilter && (
            <button type="button" onClick={() => setNameFilter("")}
              className="text-subtle hover:text-navy-700"><X size={11} /></button>
          )}
        </div>

        {/* Type filter */}
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

        {/* Stats */}
        <div className="rounded-xl border border-navy-100 bg-white/90 px-3 py-2 shadow-soft backdrop-blur-sm text-[11px] text-subtle">
          {visibleCount} / {allEntities.length} entities · {edges.length} rel{edges.length !== 1 ? "s" : ""}
        </div>

        {/* Controls */}
        <div className="flex gap-1">
          <button type="button" onClick={load}
            className="focus-ring flex items-center gap-1 rounded-lg border border-navy-100 bg-white/90 px-2 py-1.5 text-[11px] text-navy-700 hover:bg-navy-50 shadow-soft backdrop-blur-sm">
            <RefreshCw size={11} /> Reload
          </button>
          <button type="button" onClick={() => { setShowPath((v) => !v); setPathIds(new Set()); }}
            className={cn(
              "focus-ring flex items-center gap-1 rounded-lg border px-2 py-1.5 text-[11px] shadow-soft backdrop-blur-sm",
              showPath ? "border-steel-200 bg-steel-50 text-steel-700" : "border-navy-100 bg-white/90 text-navy-700 hover:bg-navy-50",
            )}>
            Path finder
          </button>
        </div>

        {showPath && (
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

      {/* ReactFlow canvas */}
      <div className={cn("flex-1", selected ? "mr-72" : "")}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={onNodeClick}
          onInit={(instance) => {
            rfInstance.current = instance;
            setTimeout(() => instance.fitView({ padding: 0.15 }), 50);
          }}
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
              return borderStyle?.replace("2px solid ", "")?.replace("2px dashed ", "") || "#4068A8";
            }}
            maskColor="rgba(248,249,252,0.8)"
            className="!bottom-3 !right-3"
          />
        </ReactFlow>
      </div>

      {/* Detail panel */}
      {selected && (
        <DetailPanel
          entity={selected}
          workspaceId={workspaceId}
          onClose={() => setSelected(null)}
          onNavigate={navigateTo}
        />
      )}
    </div>
  );
}
