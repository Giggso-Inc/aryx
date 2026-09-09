"use client";

import { Database, ListTree, Loader2, Network } from "lucide-react";
import { GraphLens } from "./GraphLens";
import { SourcesLens } from "./SourcesLens";
import { SourceDetailView } from "./SourceDetail";
import { TreeLens } from "./TreeLens";
import { DeleteConfirmModal } from "./data-explorer/DeleteConfirmModal";
import { Tab } from "./data-explorer/Tab";
import { useDataExplorer } from "./data-explorer/useDataExplorer";

/** The Data tab: source registry first, then resolved-entity exploration. */
export function DataExplorer() {
  const s = useDataExplorer();

  return (
    <div className="workspace-section-shell pb-6 pt-6">
      {s.err && (
        <div className="mt-6 rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-[13px] text-rose-700">
          {s.err}
        </div>
      )}

      {!s.summary && !s.err && (
        <div className="mt-8 flex items-center gap-2 text-[13px] text-subtle">
          <Loader2 size={15} className="animate-spin" /> Reading the workspace…
        </div>
      )}

      {(s.summary || s.lens === "sources") && (
        <div className="mt-4 space-y-5">
          <div className="flex items-center gap-1 border-b border-navy-100">
            <Tab icon={<Database size={15} />} label="Sources"
                 active={s.lens === "sources"} onClick={() => s.setLens("sources")} />
            <Tab icon={<ListTree size={15} />} label="Tree"
                 active={s.lens === "tree"} onClick={() => s.setLens("tree")} />
            <Tab icon={<Network size={15} />} label="Graph Map"
                 active={s.lens === "graph"} onClick={() => s.setLens("graph")} />
          </div>

          {s.lens === "sources" ? (
            s.activeSourceKey && s.activeSourceDetail ? (
              <SourceDetailView
                workspaceId={s.workspaceId}
                detail={s.activeSourceDetail}
                busyTarget={s.busyKey}
                onBack={() => {
                  s.setActiveSourceKey(null);
                  s.setActiveSourceDetail(null);
                }}
                onDownloadSource={() => {
                  const detail = s.activeSourceDetail;
                  if (detail) void s.downloadSourceByKey(detail.source_key, detail.name);
                }}
                onDeleteSource={() => {
                  const detail = s.activeSourceDetail;
                  if (!detail) return;
                  s.setDeleteRequest({
                    kind: "source",
                    sourceKey: detail.source_key,
                    sourceName: detail.name,
                  });
                }}
                onDownloadAsset={(asset) => { void s.downloadAsset(asset); }}
                onDeleteAsset={(asset) => { void s.deleteAsset(asset); }}
                onPreviewAsset={(asset) => s.previewAsset(asset)}
              />
            ) : s.detailLoading ? (
              <div className="flex items-center gap-2 rounded-2xl border border-navy-100 bg-white px-5 py-10 text-sm text-subtle shadow-soft">
                <Loader2 size={16} className="animate-spin" />
                Loading source details...
              </div>
            ) : (
              <SourcesLens
                sources={s.sources}
                total={s.sourceTotal}
                page={s.sourcePage}
                pageSize={50}
                query={s.sourceQuery}
                filter={s.sourceFilter}
                loading={s.sourcesLoading}
                error={s.sourceErr}
                busyKey={s.busyKey}
                onQueryChange={(value) => { s.setSourceQuery(value); s.setSourcePage(1); }}
                onFilterChange={(value) => { s.setSourceFilter(value); s.setSourcePage(1); }}
                onPageChange={s.setSourcePage}
                onViewSource={(source) => { void s.openSource(source); }}
                onDownloadSource={(source) => { void s.downloadSource(source); }}
                onDeleteSource={(source) => { void s.deleteSource(source); }}
              />
            )
          ) : null}
          {s.lens === "tree" && s.summary ? <TreeLens types={s.summary.types} /> : null}
          {s.lens === "graph" && s.summary ? <GraphLens types={s.summary.types} /> : null}
        </div>
      )}

      {s.deleteRequest ? (
        <DeleteConfirmModal
          title={s.deleteRequest.kind === "source" ? "Delete Source" : "Delete Asset"}
          message={
            s.deleteRequest.kind === "source"
              ? `Permanently delete ${s.deleteRequest.sourceName}? This removes its records, entity provenance, and affected graph data. This cannot be undone.`
              : `Permanently delete ${s.deleteRequest.assetName} from ${s.deleteRequest.sourceName}? Its records, entity provenance, and affected graph data will be removed. This cannot be undone.`
          }
          onCancel={() => s.setDeleteRequest(null)}
          onConfirm={() => { void s.confirmDelete(); }}
        />
      ) : null}
    </div>
  );
}
