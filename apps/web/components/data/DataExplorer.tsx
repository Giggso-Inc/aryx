"use client";

import { useEffect, useState } from "react";
import { Database, ListTree, Loader2, Network } from "lucide-react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/lib/workspace";
import type { DataSummary, Datasource } from "@/lib/types";
import { GraphLens } from "./GraphLens";
import { SourcesLens } from "./SourcesLens";
import { TreeLens } from "./TreeLens";

type Lens = "sources" | "tree" | "graph";

/** The Data tab: source registry first, then resolved-entity exploration. */
export function DataExplorer() {
  const { workspaceId } = useWorkspace();
  const [summary, setSummary] = useState<DataSummary | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [datasources, setDatasources] = useState<Datasource[]>([]);
  const [sourceErr, setSourceErr] = useState<string | null>(null);
  const [sourcesLoading, setSourcesLoading] = useState(true);
  const [lens, setLens] = useState<Lens>("sources");

  useEffect(() => {
    let live = true;
    setSummary(null);
    setErr(null);
    setDatasources([]);
    setSourceErr(null);
    setSourcesLoading(true);
    api.dataSummary(workspaceId)
      .then((d) => { if (live) ("error" in d && d.error) ? setErr(d.error) : setSummary(d); })
      .catch((e) => { if (live) setErr(e instanceof Error ? e.message : "failed"); });
    api.listDatasources(workspaceId)
      .then((items) => { if (live) setDatasources(items); })
      .catch((e) => { if (live) setSourceErr(e instanceof Error ? e.message : "failed"); })
      .finally(() => { if (live) setSourcesLoading(false); });
    return () => { live = false; };
  }, [workspaceId]);

  return (
    <div className="workspace-section-shell pb-6 pt-6">
      {err && (
        <div className="mt-6 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-[13px] text-rose-700">
          {err}
        </div>
      )}

      {!summary && !err && (
        <div className="mt-8 flex items-center gap-2 text-[13px] text-subtle">
          <Loader2 size={15} className="animate-spin" /> Reading the workspace…
        </div>
      )}

      {summary && (
        <div className="mt-4 space-y-5">
          <div className="flex items-center gap-1 border-b border-navy-100">
            <Tab icon={<Database size={15} />} label="Sources"
                 active={lens === "sources"} onClick={() => setLens("sources")} />
            <Tab icon={<ListTree size={15} />} label="Tree"
                 active={lens === "tree"} onClick={() => setLens("tree")} />
            <Tab icon={<Network size={15} />} label="Graph Map"
                 active={lens === "graph"} onClick={() => setLens("graph")} />
          </div>

          {lens === "sources" ? (
            <SourcesLens
              summary={summary}
              datasources={datasources}
              loading={sourcesLoading}
              error={sourceErr}
            />
          ) : null}
          {lens === "tree" ? <TreeLens types={summary.types} /> : null}
          {lens === "graph" ? <GraphLens /> : null}
        </div>
      )}
    </div>
  );
}

function Tab({ icon, label, active, onClick }: {
  icon: React.ReactNode; label: string; active: boolean; onClick: () => void;
}) {
  return (
    <button type="button" onClick={onClick}
      className={"flex items-center gap-1.5 border-b-2 px-4 py-2 text-[13px] font-semibold " +
        (active ? "border-steel-500 text-navy-900"
                : "border-transparent text-subtle hover:text-navy-700")}>
      {icon} {label}
    </button>
  );
}
