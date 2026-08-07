"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Loader2, Maximize2, Minimize2, X, ArrowRight, ArrowLeft, Search,
  Layers, Route, Waypoints,
} from "lucide-react";
import {
  ReactFlow, Background, Controls, MiniMap, MarkerType, Position,
  useNodesState, useEdgesState,
  type Node, type Edge, type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import dagre from "dagre";
import { api } from "@/lib/api";
import { typeColor } from "@/lib/typeColor";
import type {
  EntityGraphView, EntityDetail, GraphView, GraphEntityNode,
  GraphEntityEdge, GraphNeighbor,
} from "@/lib/types";

// ── Layout (copied from GraphLens.tsx — same dagre/cluster core, not
//    reinvented; kept local since GraphLens doesn't export these helpers). ──

const NODE_W = 156;
const NODE_H = 42;
const RING = "0 0 0 3px rgba(45,75,138,.9)";
const PATH_RING = "0 0 0 3px rgba(217,119,6,.9)";
const BASE_SHADOW = "0 1px 2px rgba(20,40,80,.16)";

function dagreLayout(nodes: Node[], edges: Edge[]): Node[] {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 44, ranksep: 160, marginx: 24, marginy: 24 });
  g.setDefaultEdgeLabel(() => ({}));
  nodes.forEach((n) => g.setNode(n.id, { width: NODE_W, height: NODE_H }));
  edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);
  return nodes.map((n) => {
    const p = g.node(n.id);
    return { ...n, position: { x: p.x - NODE_W / 2, y: p.y - NODE_H / 2 } };
  });
}

function clusterLayout(nodes: Node[], edges: Edge[]): Node[] {
  const HUB_GAP = 230, ROW = 52, PAD = 80, MAX_ROW = 5200, SPOKE_W = NODE_W;
  const adj = new Map<string, string[]>();
  const deg = new Map<string, number>();
  nodes.forEach((n) => { adj.set(n.id, []); deg.set(n.id, 0); });
  edges.forEach((e) => {
    if (adj.has(e.source) && adj.has(e.target)) {
      adj.get(e.source)!.push(e.target);
      adj.get(e.target)!.push(e.source);
      deg.set(e.source, deg.get(e.source)! + 1);
      deg.set(e.target, deg.get(e.target)! + 1);
    }
  });
  const seen = new Set<string>();
  const comps: string[][] = [];
  for (const n of nodes) {
    if (seen.has(n.id)) continue;
    const q = [n.id]; seen.add(n.id); const c: string[] = [];
    while (q.length) {
      const id = q.pop()!; c.push(id);
      for (const m of adj.get(id) || []) if (!seen.has(m)) { seen.add(m); q.push(m); }
    }
    comps.push(c);
  }
  const clusters = comps.filter((c) => c.length > 1);
  const singles = comps.filter((c) => c.length === 1).map((c) => c[0]);
  const pos = new Map<string, { x: number; y: number }>();

  let cx = 0, cy = 0, rowH = 0;
  for (const c of clusters) {
    const hub = c.reduce((a, b) => (deg.get(b)! > deg.get(a)! ? b : a));
    const spokes = c.filter((id) => id !== hub);
    const clusterH = Math.max(1, spokes.length) * ROW;
    const clusterW = NODE_W + HUB_GAP + SPOKE_W;
    if (cx > 0 && cx + clusterW > MAX_ROW) { cx = 0; cy += rowH + PAD; rowH = 0; }
    pos.set(hub, { x: cx, y: cy + clusterH / 2 - NODE_H / 2 });
    spokes.forEach((s, i) => pos.set(s, { x: cx + NODE_W + HUB_GAP, y: cy + i * ROW }));
    cx += clusterW + PAD;
    rowH = Math.max(rowH, clusterH);
  }
  if (singles.length) {
    cx = 0; cy += rowH + PAD * 1.5;
    const perRow = Math.max(1, Math.floor(MAX_ROW / (NODE_W + 28)));
    singles.forEach((id, i) => {
      pos.set(id, {
        x: (i % perRow) * (NODE_W + 28),
        y: cy + Math.floor(i / perRow) * (NODE_H + 16),
      });
    });
  }
  return nodes.map((n) => ({ ...n, position: pos.get(n.id) || { x: 0, y: 0 } }));
}

function laidOut(nodes: Node[], edges: Edge[]): Node[] {
  return nodes.length > 60 ? clusterLayout(nodes, edges) : dagreLayout(nodes, edges);
}

// ── Overview layout: one bubble per entity type, sized by count. ───────────

function overviewLayout(nodes: Node[]): Node[] {
  const perRow = Math.max(1, Math.ceil(Math.sqrt(nodes.length)));
  const GAP = 210;
  return nodes.map((n, i) => ({
    ...n,
    position: { x: (i % perRow) * GAP, y: Math.floor(i / perRow) * GAP },
  }));
}

type ViewMode = "overview" | "focused" | "full";

/** Standalone /graph explorer: overview (types) -> focused (one type's real
 *  entities) -> full (everything), with neighbor expand-on-canvas and a
 *  shortest-path finder layered on top of GraphLens's rendering core. */
export function EntityGraph({ workspaceId }: { workspaceId: number }) {
  const [overview, setOverview] = useState<GraphView | null>(null);
  const [g, setG] = useState<EntityGraphView | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [full, setFull] = useState(false);
  const [mode, setMode] = useState<ViewMode>("overview");
  const [focusType, setFocusType] = useState<string | null>(null);

  const [sel, setSel] = useState<string | null>(null);
  const [detail, setDetail] = useState<EntityDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [query, setQuery] = useState("");
  const [hiddenTypes, setHiddenTypes] = useState<Set<string>>(new Set());
  const [focusId, setFocusId] = useState<string | null>(null);

  // Extra nodes/edges merged onto the canvas from neighbor expansion / path
  // finding, keyed by id so repeats are idempotent (no duplicate nodes).
  const [extraNodes, setExtraNodes] = useState<Map<string, GraphEntityNode>>(new Map());
  const [extraEdges, setExtraEdges] = useState<Map<string, GraphEntityEdge>>(new Map());
  const [highlightIds, setHighlightIds] = useState<Set<string>>(new Set());
  const [highlightEdgeKeys, setHighlightEdgeKeys] = useState<Set<string>>(new Set());

  const [pathOpen, setPathOpen] = useState(false);
  const [pathFrom, setPathFrom] = useState<{ id: number; name: string } | null>(null);
  const [pathTo, setPathTo] = useState<{ id: number; name: string } | null>(null);
  const [pathFromQuery, setPathFromQuery] = useState("");
  const [pathToQuery, setPathToQuery] = useState("");
  const [pathBusy, setPathBusy] = useState(false);
  const [pathErr, setPathErr] = useState<string | null>(null);

  // Load overview + full entity graph once per workspace. The full graph is
  // the source of truth for "focused" (client-side type filter) and "full".
  useEffect(() => {
    let live = true;
    setOverview(null); setG(null); setErr(null); setSel(null); setQuery("");
    setHiddenTypes(new Set()); setMode("overview"); setFocusType(null);
    setExtraNodes(new Map()); setExtraEdges(new Map());
    setHighlightIds(new Set()); setHighlightEdgeKeys(new Set());
    api.getGraphOverview(workspaceId)
      .then((d) => { if (live) (("error" in d && d.error) ? setErr(d.error!) : setOverview(d)); });
    api.dataGraphEntity(workspaceId)
      .then((d) => { if (live) (("error" in d && d.error) ? setErr(d.error!) : setG(d)); })
      .catch((e) => { if (live) setErr(e instanceof Error ? e.message : "failed"); });
    return () => { live = false; };
  }, [workspaceId]);

  // Detail panel for the selected node (reuses GraphLens's fetch pattern).
  useEffect(() => {
    if (!sel) { setDetail(null); return; }
    let live = true;
    setDetailLoading(true); setDetail(null);
    api.dataEntityDetail(workspaceId, Number(sel))
      .then((d) => { if (live && !("error" in d && d.error)) setDetail(d); })
      .finally(() => { if (live) setDetailLoading(false); });
    return () => { live = false; };
  }, [sel, workspaceId]);

  // Merge neighbors onto the canvas whenever a real entity node is selected,
  // so exploring never triggers a full reload of the graph.
  useEffect(() => {
    if (!sel) return;
    let live = true;
    api.getEntityNeighbors(workspaceId, Number(sel))
      .then((rows: GraphNeighbor[]) => {
        if (!live) return;
        setExtraNodes((prev) => {
          const next = new Map(prev);
          for (const r of rows) {
            const id = String(r.id);
            if (!next.has(id)) next.set(id, { id: r.id, type: r.type, name: r.name });
          }
          return next;
        });
        setExtraEdges((prev) => {
          const next = new Map(prev);
          for (const r of rows) {
            const source = r.direction === "out" ? Number(sel) : r.id;
            const target = r.direction === "out" ? r.id : Number(sel);
            const key = `${source}-${target}-${r.relationship}`;
            if (!next.has(key)) {
              next.set(key, { source, target, name: r.relationship });
            }
          }
          return next;
        });
      })
      .catch(() => { /* neighbors are best-effort — detail panel still works */ });
    return () => { live = false; };
  }, [sel, workspaceId]);

  useEffect(() => {
    if (!full) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { setSel(null); setFull(false); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [full]);

  const runPathFind = async () => {
    if (!pathFrom || !pathTo) return;
    setPathBusy(true); setPathErr(null);
    try {
      const steps = await api.getEntityPath(workspaceId, pathFrom.id, pathTo.id);
      if (!steps.length) {
        setPathErr("No path found between these entities.");
        setHighlightIds(new Set()); setHighlightEdgeKeys(new Set());
        return;
      }
      setExtraNodes((prev) => {
        const next = new Map(prev);
        for (const s of steps) {
          const id = String(s.id);
          if (!next.has(id)) next.set(id, { id: s.id, type: s.type, name: s.name });
        }
        return next;
      });
      setExtraEdges((prev) => {
        const next = new Map(prev);
        for (let i = 1; i < steps.length; i++) {
          const a = steps[i - 1], b = steps[i];
          const key = `${a.id}-${b.id}-${b.relationship}`;
          if (!next.has(key)) {
            next.set(key, { source: a.id, target: b.id, name: b.relationship || "" });
          }
        }
        return next;
      });
      const ids = new Set(steps.map((s) => String(s.id)));
      const edgeKeys = new Set<string>();
      for (let i = 1; i < steps.length; i++) {
        const a = steps[i - 1], b = steps[i];
        edgeKeys.add(`${a.id}-${b.id}`);
        edgeKeys.add(`${b.id}-${a.id}`);
      }
      setHighlightIds(ids);
      setHighlightEdgeKeys(edgeKeys);
      if (mode === "overview") setMode("full");
      setFocusId(String(pathFrom.id));
    } catch (e) {
      setPathErr(e instanceof Error ? e.message : "path lookup failed");
    } finally {
      setPathBusy(false);
    }
  };

  if (err) return <Box><span className="text-rose-600">{err}</span></Box>;
  if (!g || !overview) return <Box><Loader2 size={16} className="animate-spin" /> building map…</Box>;
  if (g.entity_count === 0) {
    return <Box>No entities yet — ingest a source from the Onboard tab.</Box>;
  }

  const shell = full
    ? "fixed inset-0 z-[60] flex flex-col bg-white p-4"
    : "relative flex min-h-0 flex-1 flex-col rounded-2xl border border-navy-100 bg-white p-3";

  const types = Array.from(new Set(g.nodes.map((n) => n.type)));

  // Effective node/edge set for the current view mode, plus merged extras.
  const baseNodes: GraphEntityNode[] = mode === "focused" && focusType
    ? g.nodes.filter((n) => n.type === focusType)
    : g.nodes;
  const baseIds = new Set(baseNodes.map((n) => n.id));
  const baseEdges: GraphEntityEdge[] = mode === "focused" && focusType
    ? g.edges.filter((e) => baseIds.has(e.source) && baseIds.has(e.target))
    : g.edges;

  const mergedNodeMap = new Map<string, GraphEntityNode>();
  baseNodes.forEach((n) => mergedNodeMap.set(String(n.id), n));
  if (mode !== "overview") extraNodes.forEach((n, id) => { if (!mergedNodeMap.has(id)) mergedNodeMap.set(id, n); });
  const effNodes = Array.from(mergedNodeMap.values());

  const mergedEdgeMap = new Map<string, GraphEntityEdge>();
  baseEdges.forEach((e) => mergedEdgeMap.set(`${e.source}-${e.target}-${e.name}`, e));
  if (mode !== "overview") extraEdges.forEach((e, key) => { if (!mergedEdgeMap.has(key)) mergedEdgeMap.set(key, e); });
  const effEdges = Array.from(mergedEdgeMap.values())
    .filter((e) => mergedNodeMap.has(String(e.source)) && mergedNodeMap.has(String(e.target)));

  const q = query.trim().toLowerCase();
  const matches = q
    ? effNodes.filter((n) => n.name.toLowerCase().includes(q)).slice(0, 8)
    : [];
  const pick = (id: number) => { setSel(String(id)); setFocusId(String(id)); setQuery(""); };
  const toggleType = (t: string) => setHiddenTypes((prev) => {
    const s = new Set(prev); s.has(t) ? s.delete(t) : s.add(t); return s;
  });

  const pathCandidates = (needle: string) => {
    const n = needle.trim().toLowerCase();
    if (!n) return [];
    return g.nodes.filter((e) => e.name.toLowerCase().includes(n)).slice(0, 8);
  };

  return (
    <div className={shell}>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-3 px-2 pt-1 text-[11px] text-subtle">
        <div className="flex items-center gap-3">
          <span className="whitespace-nowrap">{g.entity_count} entities · {g.relationship_count} relationships</span>
          <ModeToggle mode={mode} onChange={(m) => {
            setMode(m);
            setSel(null);
            if (m !== "focused") setFocusType(null);
          }} />
          {mode !== "overview" && (
            <span className="flex items-center gap-1.5">
              {types.map((t, i) => {
                const off = hiddenTypes.has(t);
                return (
                  <button key={t} onClick={() => toggleType(t)}
                    title={off ? `Show ${t}` : `Hide ${t}`}
                    className={`flex items-center gap-1 rounded-full border border-navy-100 px-2 py-0.5 transition-colors ${off ? "text-navy-300" : "hover:bg-navy-50 text-navy-700"}`}>
                    <span className="inline-block h-2 w-2 rounded-full"
                          style={{ background: off ? "#CBD5E1" : typeColor(i) }} />
                    <span className={off ? "line-through" : ""}>{t}</span>
                  </button>
                );
              })}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {mode !== "overview" && (
            <div className="relative">
              <Search size={12} className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-subtle" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && matches[0]) pick(matches[0].id); }}
                placeholder="Find an entity…"
                className="w-44 rounded-lg border border-navy-100 py-1 pl-6 pr-2 text-[11px] text-navy-800 outline-none focus:border-navy-300"
              />
              {matches.length ? (
                <div className="absolute right-0 top-full z-20 mt-1 max-h-60 w-60 overflow-y-auto rounded-lg border border-navy-100 bg-white py-1 shadow-lg">
                  {matches.map((m) => (
                    <button key={m.id} onClick={() => pick(m.id)}
                      className="flex w-full items-center gap-2 px-2 py-1 text-left hover:bg-navy-50">
                      <span className="inline-block h-2 w-2 shrink-0 rounded-full"
                            style={{ background: typeColor(types.indexOf(m.type)) }} />
                      <span className="truncate text-navy-800">{m.name}</span>
                      <span className="ml-auto shrink-0 text-[10px] text-subtle">{m.type}</span>
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          )}
          <button
            onClick={() => setPathOpen((v) => !v)}
            className={`flex items-center gap-1 rounded-lg border px-2 py-1 font-medium transition-colors ${pathOpen ? "border-navy-800 bg-navy-800 text-white" : "border-navy-100 text-navy-700 hover:bg-navy-50"}`}
            title="Find path between two entities"
          >
            <Route size={13} /> Path
          </button>
          <button
            onClick={() => setFull((v) => !v)}
            className="flex items-center gap-1 rounded-lg border border-navy-100 px-2 py-1 font-medium text-navy-700 transition-colors hover:bg-navy-50"
            title={full ? "Exit fullscreen (Esc)" : "Fullscreen"}
          >
            {full ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
            {full ? "Exit" : "Fullscreen"}
          </button>
        </div>
      </div>

      {pathOpen && (
        <PathFinder
          fromQuery={pathFromQuery} toQuery={pathToQuery}
          onFromQuery={setPathFromQuery} onToQuery={setPathToQuery}
          from={pathFrom} to={pathTo}
          onPickFrom={(e) => { setPathFrom({ id: e.id, name: e.name }); setPathFromQuery(""); }}
          onPickTo={(e) => { setPathTo({ id: e.id, name: e.name }); setPathToQuery(""); }}
          fromMatches={pathCandidates(pathFromQuery)}
          toMatches={pathCandidates(pathToQuery)}
          busy={pathBusy} error={pathErr}
          onFind={runPathFind}
          onClear={() => {
            setPathFrom(null); setPathTo(null); setPathErr(null);
            setHighlightIds(new Set()); setHighlightEdgeKeys(new Set());
          }}
        />
      )}

      {mode === "overview" ? (
        <OverviewFlow
          overview={overview} full={full}
          onPick={(t) => { setMode("focused"); setFocusType(t); }}
        />
      ) : (
        <Flow
          nodes={effNodes} edges={effEdges}
          full={full} sel={sel} onSelect={setSel}
          hiddenTypes={hiddenTypes} focusId={focusId}
          highlightIds={highlightIds} highlightEdgeKeys={highlightEdgeKeys}
        />
      )}

      {sel ? (
        <DetailPanel
          detail={detail} loading={detailLoading}
          typeIndex={(t) => types.indexOf(t)}
          onSelect={(id) => setSel(String(id))}
          onClose={() => setSel(null)}
        />
      ) : null}
    </div>
  );
}

function ModeToggle({ mode, onChange }: { mode: ViewMode; onChange: (m: ViewMode) => void }) {
  const opts: { key: ViewMode; label: string; icon: React.ReactNode }[] = [
    { key: "overview", label: "Overview", icon: <Layers size={11} /> },
    { key: "focused", label: "Focused", icon: <Waypoints size={11} /> },
    { key: "full", label: "Full", icon: <Search size={11} /> },
  ];
  return (
    <span className="flex items-center rounded-full border border-navy-100 p-0.5">
      {opts.map((o) => (
        <button key={o.key} onClick={() => onChange(o.key)}
          className={`flex items-center gap-1 rounded-full px-2 py-0.5 transition-colors ${
            mode === o.key ? "bg-navy-800 text-white" : "text-navy-600 hover:bg-navy-50"
          }`}>
          {o.icon}{o.label}
        </button>
      ))}
    </span>
  );
}

function PathFinder({
  fromQuery, toQuery, onFromQuery, onToQuery, from, to, onPickFrom, onPickTo,
  fromMatches, toMatches, busy, error, onFind, onClear,
}: {
  fromQuery: string; toQuery: string;
  onFromQuery: (v: string) => void; onToQuery: (v: string) => void;
  from: { id: number; name: string } | null; to: { id: number; name: string } | null;
  onPickFrom: (e: GraphEntityNode) => void; onPickTo: (e: GraphEntityNode) => void;
  fromMatches: GraphEntityNode[]; toMatches: GraphEntityNode[];
  busy: boolean; error: string | null;
  onFind: () => void; onClear: () => void;
}) {
  return (
    <div className="mb-2 flex flex-wrap items-center gap-2 rounded-xl border border-navy-100 bg-navy-50/40 px-3 py-2 text-[11px]">
      <PathPicker label="From" value={from} query={fromQuery}
                  onQuery={onFromQuery} onPick={onPickFrom} matches={fromMatches} />
      <ArrowRight size={13} className="text-subtle" />
      <PathPicker label="To" value={to} query={toQuery}
                  onQuery={onToQuery} onPick={onPickTo} matches={toMatches} />
      <button
        onClick={onFind}
        disabled={!from || !to || busy}
        className="flex items-center gap-1 rounded-lg bg-navy-800 px-2.5 py-1 font-medium text-white disabled:opacity-40"
      >
        {busy ? <Loader2 size={12} className="animate-spin" /> : <Route size={12} />}
        Find path
      </button>
      <button onClick={onClear} className="rounded-lg px-2 py-1 text-navy-600 hover:bg-navy-100">
        Clear
      </button>
      {error ? <span className="text-rose-600">{error}</span> : null}
    </div>
  );
}

function PathPicker({ label, value, query, onQuery, onPick, matches }: {
  label: string; value: { id: number; name: string } | null; query: string;
  onQuery: (v: string) => void; onPick: (e: GraphEntityNode) => void;
  matches: GraphEntityNode[];
}) {
  return (
    <div className="relative">
      <input
        value={value ? value.name : query}
        onChange={(e) => onQuery(e.target.value)}
        placeholder={`${label} entity…`}
        className="w-40 rounded-lg border border-navy-100 bg-white px-2 py-1 text-navy-800 outline-none focus:border-navy-300"
      />
      {!value && matches.length ? (
        <div className="absolute left-0 top-full z-20 mt-1 max-h-56 w-56 overflow-y-auto rounded-lg border border-navy-100 bg-white py-1 shadow-lg">
          {matches.map((m) => (
            <button key={m.id} onClick={() => onPick(m)}
              className="flex w-full items-center gap-2 px-2 py-1 text-left hover:bg-navy-50">
              <span className="truncate text-navy-800">{m.name}</span>
              <span className="ml-auto shrink-0 text-[10px] text-subtle">{m.type}</span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/** Overview: one bubble per entity type, sized/labeled by count. */
function OverviewFlow({ overview, full, onPick }: {
  overview: GraphView; full: boolean; onPick: (type: string) => void;
}) {
  const [rf, setRf] = useState<ReactFlowInstance | null>(null);
  const maxCount = Math.max(1, ...overview.type_nodes.map((n) => n.count));

  const initial = useMemo(() => {
    const rfNodes: Node[] = overview.type_nodes.map((n, i) => {
      const scale = 0.6 + 0.6 * (n.count / maxCount);
      const w = NODE_W * (1 + scale * 0.6);
      const h = NODE_H * (1 + scale * 0.6);
      return {
        id: n.type,
        data: { label: `${n.type}\n${n.count}` },
        position: { x: 0, y: 0 },
        style: {
          width: w, height: h,
          background: typeColor(i), color: "#fff", border: "none",
          borderRadius: 14, fontSize: 12.5, fontWeight: 700,
          display: "flex", alignItems: "center", justifyContent: "center",
          flexDirection: "column" as const, whiteSpace: "pre-line" as const,
          textAlign: "center" as const, boxShadow: BASE_SHADOW, cursor: "pointer",
        },
      };
    });
    const rfEdges: Edge[] = overview.type_edges.map((e, i) => ({
      id: `oe${i}`,
      source: e.source, target: e.target,
      label: `${e.name} (${e.count})`,
      labelStyle: { fontSize: 9.5, fontFamily: "JetBrains Mono, monospace", fill: "#2D4B8A" },
      labelBgStyle: { fill: "#fff", stroke: "#E4EAF4" },
      labelBgPadding: [6, 3] as [number, number],
      labelBgBorderRadius: 8,
      markerEnd: { type: MarkerType.ArrowClosed, color: "#94A8CB" },
      style: { stroke: "#C2CFE3", strokeWidth: Math.min(6, 1.4 + Math.log1p(e.count)) },
    }));
    return { nodes: overviewLayout(rfNodes), edges: rfEdges };
  }, [overview, maxCount]);

  const [nodes, , onNodesChange] = useNodesState(initial.nodes);
  const [edges, , onEdgesChange] = useEdgesState(initial.edges);

  useEffect(() => {
    if (!rf) return;
    const t = setTimeout(() => rf.fitView({ padding: 0.2 }), 80);
    return () => clearTimeout(t);
  }, [rf, full, initial]);

  return (
    <div className={full ? "min-h-0 flex-1 rounded-xl bg-[#FAFBFD]" : "rounded-xl bg-[#FAFBFD]"}
         style={full ? undefined : { height: 520 }}>
      <ReactFlow
        nodes={nodes} edges={edges}
        onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
        onInit={setRf}
        onNodeClick={(_, n) => onPick(n.id)}
        fitView fitViewOptions={{ padding: 0.2 }}
        minZoom={0.1} maxZoom={2}
        proOptions={{ hideAttribution: true }}
        nodesConnectable={false}
      >
        <Background color="#E4EAF4" gap={20} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}

function Flow({ nodes: gNodes, edges: gEdges, full, sel, onSelect, hiddenTypes, focusId,
                highlightIds, highlightEdgeKeys }: {
  nodes: GraphEntityNode[]; edges: GraphEntityEdge[];
  full: boolean; sel: string | null; onSelect: (id: string | null) => void;
  hiddenTypes: Set<string>; focusId: string | null;
  highlightIds: Set<string>; highlightEdgeKeys: Set<string>;
}) {
  const [rf, setRf] = useState<ReactFlowInstance | null>(null);

  const typeColorMap = useMemo(() => {
    const types = Array.from(new Set(gNodes.map((n) => n.type)));
    return new Map(types.map((t, i) => [t, typeColor(i)]));
  }, [gNodes]);

  const idType = useMemo(
    () => new Map(gNodes.map((n) => [String(n.id), n.type])),
    [gNodes],
  );

  const neighbours = useMemo(() => {
    const m = new Map<string, Set<string>>();
    gNodes.forEach((n) => m.set(String(n.id), new Set()));
    gEdges.forEach((e) => {
      m.get(String(e.source))?.add(String(e.target));
      m.get(String(e.target))?.add(String(e.source));
    });
    return m;
  }, [gNodes, gEdges]);

  const initial = useMemo(() => {
    const rfNodes: Node[] = gNodes.map((n) => ({
      id: String(n.id),
      data: { label: n.name },
      position: { x: 0, y: 0 },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
      style: {
        width: NODE_W, height: NODE_H,
        background: typeColorMap.get(n.type),
        color: "#fff", border: "none", borderRadius: 10,
        fontSize: 11.5, fontWeight: 600, padding: "0 8px",
        display: "flex", alignItems: "center", justifyContent: "center",
        textAlign: "center" as const, boxShadow: BASE_SHADOW, opacity: 1,
      },
    }));
    const showLabels = gEdges.length <= 120;
    const rfEdges: Edge[] = gEdges.map((e, i) => ({
      id: `e${i}-${e.source}-${e.target}`,
      source: String(e.source),
      target: String(e.target),
      ...(showLabels ? {
        label: e.name,
        labelStyle: { fontSize: 9.5, fontFamily: "JetBrains Mono, monospace", fill: "#2D4B8A" },
        labelBgStyle: { fill: "#fff", stroke: "#E4EAF4" },
        labelBgPadding: [6, 3] as [number, number],
        labelBgBorderRadius: 8,
      } : {}),
      markerEnd: { type: MarkerType.ArrowClosed, color: "#94A8CB" },
      style: { stroke: "#C2CFE3", strokeWidth: 1.4, opacity: 1 },
    }));
    return { nodes: laidOut(rfNodes, rfEdges), edges: rfEdges };
  }, [gNodes, gEdges, typeColorMap]);

  const [nodes, setNodes, onNodesChange] = useNodesState(initial.nodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initial.edges);

  useEffect(() => {
    setNodes(initial.nodes);
    setEdges(initial.edges);
  }, [initial, setNodes, setEdges]);

  // Selection highlight + type filter + path highlight — recomputed
  // absolutely each time so dragging positions still persist.
  useEffect(() => {
    const near = sel ? neighbours.get(sel) : null;
    setNodes((cur) => cur.map((n) => {
      const active = !sel || n.id === sel || (near?.has(n.id) ?? false);
      const onPath = highlightIds.has(n.id);
      return { ...n, hidden: hiddenTypes.has(idType.get(n.id) || ""),
        style: { ...n.style,
          opacity: active ? 1 : 0.15,
          boxShadow: n.id === sel ? RING : onPath ? PATH_RING : BASE_SHADOW } };
    }));
    setEdges((cur) => cur.map((e) => {
      const endHidden = hiddenTypes.has(idType.get(e.source) || "")
        || hiddenTypes.has(idType.get(e.target) || "");
      const inc = !!sel && (e.source === sel || e.target === sel);
      const onPath = highlightEdgeKeys.has(`${e.source}-${e.target}`);
      return { ...e, hidden: endHidden, animated: inc || onPath, style: { ...e.style,
        opacity: !sel || inc ? 1 : 0.06,
        stroke: onPath ? "#D97706" : inc ? "#2D4B8A" : "#C2CFE3",
        strokeWidth: onPath ? 3 : inc ? 2.2 : 1.4 } };
    }));
  }, [sel, neighbours, hiddenTypes, idType, highlightIds, highlightEdgeKeys, setNodes, setEdges]);

  useEffect(() => {
    if (!rf) return;
    const t = setTimeout(() => rf.fitView({ padding: 0.15 }), 80);
    return () => clearTimeout(t);
  }, [rf, full, initial]);

  useEffect(() => {
    if (!rf || !focusId) return;
    const n = rf.getNode(focusId);
    if (n) rf.setCenter(n.position.x + NODE_W / 2, n.position.y + NODE_H / 2,
                        { zoom: 1.3, duration: 500 });
  }, [rf, focusId]);

  return (
    <div className={full ? "min-h-0 flex-1 rounded-xl bg-[#FAFBFD]" : "rounded-xl bg-[#FAFBFD]"}
         style={full ? undefined : { height: 520 }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onInit={setRf}
        onNodeClick={(_, n) => onSelect(n.id)}
        onPaneClick={() => onSelect(null)}
        fitView
        fitViewOptions={{ padding: 0.15 }}
        minZoom={0.05}
        maxZoom={2}
        proOptions={{ hideAttribution: true }}
        nodesConnectable={false}
      >
        <Background color="#E4EAF4" gap={20} />
        <Controls showInteractive={false} />
        <MiniMap
          pannable zoomable
          nodeColor={(n) => (n.style?.background as string) || "#94A8CB"}
          nodeStrokeWidth={0}
          maskColor="rgba(20,40,80,.06)"
          style={{ background: "#fff", border: "1px solid #E4EAF4", borderRadius: 8 }}
        />
      </ReactFlow>
    </div>
  );
}

function DetailPanel({ detail, loading, typeIndex, onSelect, onClose }: {
  detail: EntityDetail | null; loading: boolean;
  typeIndex: (t: string) => number;
  onSelect: (id: number) => void; onClose: () => void;
}) {
  return (
    <div className="absolute right-3 top-14 bottom-3 z-10 flex w-80 flex-col overflow-hidden rounded-xl border border-navy-100 bg-white shadow-lg">
      <div className="flex items-center justify-between border-b border-navy-100 px-3 py-2">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-subtle">Details</span>
        <button onClick={onClose} className="rounded p-1 text-subtle hover:bg-navy-50" title="Close">
          <X size={14} />
        </button>
      </div>
      {loading || !detail ? (
        <div className="flex flex-1 items-center justify-center gap-2 text-[13px] text-subtle">
          <Loader2 size={14} className="animate-spin" /> loading…
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto px-3 py-3 text-[12.5px]">
          <div className="mb-3">
            <div className="flex items-center gap-2">
              <span className="inline-block h-2.5 w-2.5 rounded-full"
                    style={{ background: typeColor(typeIndex(detail.type)) }} />
              <span className="text-[10.5px] font-medium uppercase tracking-wide text-subtle">{detail.type}</span>
            </div>
            <div className="mt-0.5 text-[15px] font-semibold text-navy-900">{detail.name}</div>
          </div>

          <Section title="Attributes">
            <dl className="space-y-1">
              {Object.entries(detail.attributes)
                .filter(([k]) => !k.startsWith("_"))
                .map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-3">
                    <dt className="shrink-0 text-subtle">{k}</dt>
                    <dd className="truncate text-right text-navy-800" title={String(v)}>{String(v)}</dd>
                  </div>
                ))}
            </dl>
          </Section>

          <Section title={`Relationships (${detail.relationships.length})`}>
            {detail.relationships.length === 0 ? (
              <p className="text-subtle">No connections.</p>
            ) : (
              <ul className="space-y-1">
                {detail.relationships.map((r, i) => (
                  <li key={i}>
                    <button
                      onClick={() => onSelect(r.other_id)}
                      className="flex w-full items-center gap-1.5 rounded-md px-1.5 py-1 text-left hover:bg-navy-50"
                    >
                      {r.direction === "out"
                        ? <ArrowRight size={12} className="shrink-0 text-navy-400" />
                        : <ArrowLeft size={12} className="shrink-0 text-navy-400" />}
                      <span className="shrink-0 font-mono text-[9.5px] text-navy-500">{r.name}</span>
                      <span className="truncate text-navy-800">{r.other_name}</span>
                      <span className="ml-auto shrink-0 text-[10px] text-subtle">{r.other_type}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          {detail.sources.length ? (
            <Section title={`Source records (${detail.sources.length})`}>
              <ul className="space-y-1 font-mono text-[10.5px] text-subtle">
                {detail.sources.map((s, i) => (
                  <li key={i} className="truncate" title={`${s.system}.${s.dataset} · ${s.record_id}`}>
                    {s.system}.{s.dataset} · {s.record_id}
                  </li>
                ))}
              </ul>
            </Section>
          ) : null}
        </div>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mb-3">
      <div className="mb-1 text-[10.5px] font-semibold uppercase tracking-wide text-subtle">{title}</div>
      {children}
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
