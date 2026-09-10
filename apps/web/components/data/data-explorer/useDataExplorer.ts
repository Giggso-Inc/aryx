/**
 * State, data loading, and mutation logic for DataExplorer.
 *
 * Split out of DataExplorer.tsx (2026-09; Raven Style Compliance Plan
 * Phase 8b line-count reduction).
 */

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useWorkspace } from "@/lib/workspace";
import type { DataSourceCatalogItem, DataSourceDetail, DataSummary } from "@/lib/types";
import type { SourceFilter } from "../SourcesLens";
import { loadSourcesPage, mergeDetailMetrics, triggerDownload } from "./source-page-loader";
import { useDataExplorerAssetActions } from "./useDataExplorerAssetActions";

export type Lens = "sources" | "tree" | "graph";
export type DeleteRequest =
  | { kind: "source"; sourceKey: string; sourceName: string }
  | { kind: "asset"; sourceKey: string; sourceName: string; assetKey: string; assetName: string };

export function useDataExplorer() {
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
      loadSourcesPage(workspaceId, {
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
      const result = await loadSourcesPage(workspaceId, {
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
      setActiveSourceDetail(mergeDetailMetrics(detail, source));
    } catch (e) {
      if (currentWorkspaceId.current !== requestedWorkspaceId) return;
      setActiveSourceKey(null);
      setActiveSourceDetail(null);
      setSourceErr(e instanceof Error ? e.message : "failed");
    } finally {
      if (currentWorkspaceId.current === requestedWorkspaceId) setDetailLoading(false);
    }
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

  const downloadSource = async (source: DataSourceCatalogItem) => {
    await downloadSourceByKey(source.source_key, source.name);
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
      const result = await api.deleteDataSource(workspaceId, sourceKey);
      setActiveSourceKey(null);
      setActiveSourceDetail(null);
      await refreshSources();
      if (result.graph_sync === "repair_required") {
        setSourceErr(
          "Source data was deleted, but the graph view still needs repair.",
        );
      }
    } catch (e) {
      setSourceErr(e instanceof Error ? e.message : "delete failed");
    } finally {
      setBusyKey(null);
    }
  };

  const assetActions = useDataExplorerAssetActions({
    workspaceId, activeSourceDetail, setActiveSourceKey, setActiveSourceDetail,
    setBusyKey, setSourceErr, setDeleteRequest, refreshSources,
  });
  const { downloadAsset, previewAsset, deleteAsset, deleteAssetByKey } = assetActions;

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

  return {
    workspaceId,
    summary,
    err,
    sources,
    sourceTotal,
    sourcePage,
    setSourcePage,
    sourceQuery,
    setSourceQuery,
    sourceFilter,
    setSourceFilter,
    sourceErr,
    sourcesLoading,
    activeSourceKey,
    setActiveSourceKey,
    activeSourceDetail,
    setActiveSourceDetail,
    detailLoading,
    busyKey,
    deleteRequest,
    setDeleteRequest,
    lens,
    setLens,
    openSource,
    downloadSource,
    downloadSourceByKey,
    deleteSource,
    downloadAsset,
    previewAsset,
    deleteAsset,
    confirmDelete,
  };
}
