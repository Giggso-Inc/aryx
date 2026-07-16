"use client";

import { useEffect, useRef, useState } from "react";
import { Database, ListTree, Loader2, Network } from "lucide-react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/lib/workspace";
import type { DataSourceCatalogItem, DataSourceCatalogPage, DataSourceDetail, DataSummary, XmlGeneratedAsset } from "@/lib/types";
import { GraphLens } from "./GraphLens";
import { SourcesLens, type SourceFilter } from "./SourcesLens";
import { SourceDetailView } from "./SourceDetail";
import { TreeLens } from "./TreeLens";

type Lens = "sources" | "tree" | "graph";
type DeleteRequest =
  | { kind: "source"; sourceKey: string; sourceName: string }
  | { kind: "asset"; sourceKey: string; sourceName: string; assetKey: string; assetName: string };

/** The Data tab: source registry first, then resolved-entity exploration. */
export function DataExplorer() {
  const { workspaceId } = useWorkspace();
  const currentWorkspaceId = useRef(workspaceId);
  currentWorkspaceId.current = workspaceId;
  const [summary, setSummary] = useState<DataSummary | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [sources, setSources] = useState<DataSourceCatalogItem[]>([]);
  const [sourceTotal, setSourceTotal] = useState(0);
  const [sourcePage, setSourcePage] = useState(1);
  const [sourceQuery, setSourceQuery] = useState("");
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");
  const [sourceErr, setSourceErr] = useState<string | null>(null);
  const [sourcesLoading, setSourcesLoading] = useState(true);
  const [activeSourceKey, setActiveSourceKey] = useState<string | null>(null);
  const [activeSourceDetail, setActiveSourceDetail] = useState<DataSourceDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [deleteRequest, setDeleteRequest] = useState<DeleteRequest | null>(null);
  const [lens, setLens] = useState<Lens>("sources");

  useEffect(() => {
    let live = true;
    setSummary(null);
    setErr(null);
    setSources([]);
    setSourceTotal(0);
    setSourcePage(1);
    setSourceQuery("");
    setSourceFilter("all");
    setSourceErr(null);
    setSourcesLoading(true);
    setActiveSourceKey(null);
    setActiveSourceDetail(null);
    setDetailLoading(false);
    setBusyKey(null);
    api.dataSummary(workspaceId)
      .then((d) => { if (live) ("error" in d && d.error) ? setErr(d.error) : setSummary(d); })
      .catch((e) => { if (live) setErr(e instanceof Error ? e.message : "failed"); });
    return () => { live = false; };
  }, [workspaceId]);

  useEffect(() => {
    let live = true;
    const timer = window.setTimeout(() => {
      setSourcesLoading(true);
      setSourceErr(null);
      api.listDataSourcesPage(workspaceId, {
        page: sourcePage, pageSize: 50, query: sourceQuery, category: sourceFilter,
      }).then((result) => {
        if (!live) return;
        setSources(result.items);
        setSourceTotal(result.total);
      }).catch((e) => {
        if (live) setSourceErr(e instanceof Error ? e.message : "failed");
      }).finally(() => { if (live) setSourcesLoading(false); });
    }, 250);
    return () => { live = false; window.clearTimeout(timer); };
  }, [sourceFilter, sourcePage, sourceQuery, workspaceId]);

  const refreshSources = async () => {
    setSourcesLoading(true);
    try {
      const result: DataSourceCatalogPage = await api.listDataSourcesPage(workspaceId, {
        page: sourcePage, pageSize: 50, query: sourceQuery, category: sourceFilter,
      });
      if (result.items.length === 0 && sourcePage > 1) {
        setSourcePage(sourcePage - 1);
      } else {
        setSources(result.items);
        setSourceTotal(result.total);
      }
    } catch (e) {
      setSourceErr(e instanceof Error ? e.message : "failed");
    } finally {
      setSourcesLoading(false);
    }
  };

  const openSource = async (source: DataSourceCatalogItem) => {
    if (!source.actions.view) return;
    const requestedWorkspaceId = workspaceId;
    setActiveSourceKey(source.source_key);
    setDetailLoading(true);
    setSourceErr(null);
    try {
      const detail = await api.getDataSourceDetail(workspaceId, source.source_key);
      if (currentWorkspaceId.current !== requestedWorkspaceId) return;
      setActiveSourceDetail(detail);
    } catch (e) {
      if (currentWorkspaceId.current !== requestedWorkspaceId) return;
      setActiveSourceKey(null);
      setActiveSourceDetail(null);
      setSourceErr(e instanceof Error ? e.message : "failed");
    } finally {
      if (currentWorkspaceId.current === requestedWorkspaceId) setDetailLoading(false);
    }
  };

  const downloadSource = async (source: DataSourceCatalogItem) => {
    await downloadSourceByKey(source.source_key, source.name);
  };

  const downloadSourceByKey = async (sourceKey: string, filename: string) => {
    setBusyKey(`${sourceKey}:download`);
    try {
      const blob = await api.downloadDataSource(workspaceId, sourceKey);
      triggerDownload(blob, filename);
    } catch (e) {
      setSourceErr(e instanceof Error ? e.message : "download failed");
    } finally {
      setBusyKey(null);
    }
  };

  const deleteSource = async (source: DataSourceCatalogItem) => {
    setDeleteRequest({
      kind: "source",
      sourceKey: source.source_key,
      sourceName: source.name,
    });
  };

  const deleteSourceByKey = async (sourceKey: string) => {
    setBusyKey(`${sourceKey}:delete`);
    try {
      await api.deleteDataSource(workspaceId, sourceKey);
      setActiveSourceKey(null);
      setActiveSourceDetail(null);
      await refreshSources();
    } catch (e) {
      setSourceErr(e instanceof Error ? e.message : "delete failed");
    } finally {
      setBusyKey(null);
    }
  };

  const downloadAsset = async (asset: XmlGeneratedAsset) => {
    if (!activeSourceDetail) return;
    const targetKey = `${activeSourceDetail.source_key}:${asset.asset_key}:download`;
    setBusyKey(targetKey);
    try {
      const blob = await api.downloadGeneratedAsset(workspaceId, activeSourceDetail.source_key, asset.asset_key);
      triggerDownload(blob, asset.filename);
    } catch (e) {
      setSourceErr(e instanceof Error ? e.message : "asset download failed");
    } finally {
      setBusyKey(null);
    }
  };

  const previewAsset = async (asset: XmlGeneratedAsset): Promise<Record<string, string>[]> => {
    if (asset.preview_rows.length > 0 || !activeSourceDetail) return asset.preview_rows;
    const targetKey = `${activeSourceDetail.source_key}:${asset.asset_key}:preview`;
    setBusyKey(targetKey);
    try {
      const blob = await api.downloadGeneratedAsset(workspaceId, activeSourceDetail.source_key, asset.asset_key);
      const text = await blob.text();
      return parseCsvPreview(text);
    } catch (e) {
      setSourceErr(e instanceof Error ? e.message : "preview failed");
      return [];
    } finally {
      setBusyKey(null);
    }
  };

  const deleteAsset = async (asset: XmlGeneratedAsset) => {
    if (!activeSourceDetail) return;
    setDeleteRequest({
      kind: "asset",
      sourceKey: activeSourceDetail.source_key,
      sourceName: activeSourceDetail.name,
      assetKey: asset.asset_key,
      assetName: asset.filename,
    });
  };

  const deleteAssetByKey = async (
    sourceKey: string,
    assetKey: string,
  ) => {
    const targetKey = `${sourceKey}:${assetKey}:delete`;
    setBusyKey(targetKey);
    try {
      await api.deleteGeneratedAsset(workspaceId, sourceKey, assetKey);
      const nextDetail = await api.getDataSourceDetail(workspaceId, sourceKey);
      setActiveSourceDetail(nextDetail);
      await refreshSources();
    } catch (e) {
      setSourceErr(e instanceof Error ? e.message : "asset delete failed");
    } finally {
      setBusyKey(null);
    }
  };

  const confirmDelete = async () => {
    if (!deleteRequest) return;
    const request = deleteRequest;
    setDeleteRequest(null);
    if (request.kind === "source") {
      await deleteSourceByKey(request.sourceKey);
      return;
    }
    await deleteAssetByKey(request.sourceKey, request.assetKey);
  };

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

      {(summary || lens === "sources") && (
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
            activeSourceKey && activeSourceDetail ? (
              <SourceDetailView
                workspaceId={workspaceId}
                detail={activeSourceDetail}
                busyTarget={busyKey}
                onBack={() => {
                  setActiveSourceKey(null);
                  setActiveSourceDetail(null);
                }}
                onDownloadSource={() => { void downloadSourceByKey(activeSourceDetail.source_key, activeSourceDetail.name); }}
                onDeleteSource={() => {
                  setDeleteRequest({
                    kind: "source",
                    sourceKey: activeSourceDetail.source_key,
                    sourceName: activeSourceDetail.name,
                  });
                }}
                onDownloadAsset={(asset) => { void downloadAsset(asset); }}
                onDeleteAsset={(asset) => { void deleteAsset(asset); }}
                onPreviewAsset={(asset) => previewAsset(asset)}
              />
            ) : detailLoading ? (
              <div className="flex items-center gap-2 rounded-2xl border border-navy-100 bg-white px-5 py-10 text-sm text-subtle shadow-soft">
                <Loader2 size={16} className="animate-spin" />
                Loading source details...
              </div>
            ) : (
              <SourcesLens
                sources={sources}
                total={sourceTotal}
                page={sourcePage}
                pageSize={50}
                query={sourceQuery}
                filter={sourceFilter}
                loading={sourcesLoading}
                error={sourceErr}
                busyKey={busyKey}
                onQueryChange={(value) => { setSourceQuery(value); setSourcePage(1); }}
                onFilterChange={(value) => { setSourceFilter(value); setSourcePage(1); }}
                onPageChange={setSourcePage}
                onViewSource={(source) => { void openSource(source); }}
                onDownloadSource={(source) => { void downloadSource(source); }}
                onDeleteSource={(source) => { void deleteSource(source); }}
              />
            )
          ) : null}
          {lens === "tree" && summary ? <TreeLens types={summary.types} /> : null}
          {lens === "graph" && summary ? <GraphLens types={summary.types} /> : null}
        </div>
      )}

      {deleteRequest ? (
        <DeleteConfirmModal
          title={deleteRequest.kind === "source" ? "Delete Source" : "Delete Asset"}
          message={
            deleteRequest.kind === "source"
              ? `Delete ${deleteRequest.sourceName} from the source catalog?`
              : `Delete ${deleteRequest.assetName} from ${deleteRequest.sourceName}?`
          }
          onCancel={() => setDeleteRequest(null)}
          onConfirm={() => { void confirmDelete(); }}
        />
      ) : null}
    </div>
  );
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function parseCsvPreview(text: string): Record<string, string>[] {
  const rows = parseCsvRows(text).filter((row) => row.some((cell) => cell.trim() !== ""));
  if (rows.length < 2) return [];
  const headers = rows[0].map((cell) => cell.trim());
  return rows.slice(1, 6).map((row) => {
    const record: Record<string, string> = {};
    headers.forEach((header, index) => {
      record[header || `column_${index + 1}`] = row[index] ?? "";
    });
    return record;
  });
}

function parseCsvRows(text: string): string[][] {
  const rows: string[][] = [];
  let currentRow: string[] = [];
  let currentValue = "";
  let inQuotes = false;

  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    const next = text[index + 1];

    if (char === "\"") {
      if (inQuotes && next === "\"") {
        currentValue += "\"";
        index += 1;
      } else {
        inQuotes = !inQuotes;
      }
      continue;
    }

    if (char === "," && !inQuotes) {
      currentRow.push(currentValue);
      currentValue = "";
      continue;
    }

    if ((char === "\n" || char === "\r") && !inQuotes) {
      if (char === "\r" && next === "\n") {
        index += 1;
      }
      currentRow.push(currentValue);
      rows.push(currentRow);
      currentRow = [];
      currentValue = "";
      continue;
    }

    currentValue += char;
  }

  if (currentValue.length > 0 || currentRow.length > 0) {
    currentRow.push(currentValue);
    rows.push(currentRow);
  }

  return rows;
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

function DeleteConfirmModal({
  title,
  message,
  onCancel,
  onConfirm,
}: {
  title: string;
  message: string;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-navy-950/45 px-4 py-8"
      role="dialog"
      aria-modal="true"
      aria-labelledby="delete-confirm-title"
      onClick={onCancel}
    >
      <div
        className="w-full max-w-lg rounded-[1.5rem] border border-navy-100 bg-white p-6 shadow-soft"
        onClick={(event) => event.stopPropagation()}
      >
        <p
          id="delete-confirm-title"
          className="text-lg font-semibold text-navy-900"
        >
          {title}
        </p>
        <p className="mt-3 text-sm leading-6 text-subtle">
          {message}
        </p>
        <p className="mt-2 text-sm text-rose-600">
          This action cannot be undone.
        </p>
        <div className="mt-6 flex items-center justify-end gap-3">
          <button
            type="button"
            onClick={onCancel}
            className="focus-ring rounded-full border border-navy-100 bg-white px-4 py-2 text-sm font-semibold text-navy-700 transition-colors hover:bg-navy-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className="focus-ring rounded-full bg-rose-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-rose-700"
          >
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}
