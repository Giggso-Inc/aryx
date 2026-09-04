"use client";

import { useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/lib/workspace";
import type { DataTypeCount, GraphView } from "@/lib/types";
import { GraphSvg } from "./graph-lens/GraphSvg";
import { buildGraphLayout } from "./graph-lens/layout";

/** Type-level knowledge map: one node per type with a layout that preserves
 *  readable labels and avoids overlap across dense ontologies. */
export function GraphLens({ types }: { types: DataTypeCount[] }) {
  const { workspaceId } = useWorkspace();
  const [g, setG] = useState<GraphView | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const layout = useMemo(
    () => (g ? buildGraphLayout(g.type_nodes, g.type_edges, types) : null),
    [g, types],
  );

  useEffect(() => {
    let live = true;
    setG(null); setErr(null);
    api.dataGraph(workspaceId)
      .then((d) => { if (live) (("error" in d && d.error) ? setErr(d.error!) : setG(d)); })
      .catch((e) => { if (live) setErr(e instanceof Error ? e.message : "failed"); });
    return () => { live = false; };
  }, [workspaceId]);

  if (err) return <Box><span className="text-rose-600">{err}</span></Box>;
  if (!g) return <Box><Loader2 size={16} className="animate-spin" /> building map…</Box>;
  if (!layout) return <Box><Loader2 size={16} className="animate-spin" /> building map…</Box>;

  return (
    <div className="rounded-2xl border border-navy-100 bg-white p-3">
      <div className="mb-1 flex items-center justify-between px-2 pt-1 text-[11px] text-subtle">
        <span>{g.entity_count} entities · {g.relationship_count} relationships</span>
        <span>hover truncated labels to see the full name</span>
      </div>
      {g.relationship_count === 0 ? (
        <p className="px-2 py-6 text-center text-[12.5px] text-subtle">
          Entities exist but no relationships are defined yet — the map shows the
          types; connect them with foreign-key links to see the graph.
        </p>
      ) : null}
      <div className="overflow-auto rounded-xl">
        <GraphSvg layout={layout} />
      </div>
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
