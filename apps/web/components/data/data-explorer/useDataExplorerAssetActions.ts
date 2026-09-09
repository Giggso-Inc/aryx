/**
 * Generated-asset download/preview/delete handlers for DataExplorer's
 * active source detail view.
 *
 * Split out of useDataExplorer.ts (2026-09; Raven Style Compliance
 * Plan Phase 8b line-count reduction).
 */

import { api } from "@/lib/api";
import type { DataSourceDetail, XmlGeneratedAsset } from "@/lib/types";
import { mergeDetailMetrics, triggerDownload } from "./source-page-loader";
import { parseCsvPreview } from "./csv-preview";
import type { DeleteRequest } from "./useDataExplorer";

export function useDataExplorerAssetActions(deps: {
  workspaceId: number;
  activeSourceDetail: DataSourceDetail | null;
  setActiveSourceKey: (key: string | null) => void;
  setActiveSourceDetail: (detail: DataSourceDetail | null) => void;
  setBusyKey: (key: string | null) => void;
  setSourceErr: (message: string | null) => void;
  setDeleteRequest: (request: DeleteRequest | null) => void;
  refreshSources: () => Promise<void>;
}) {
  const {
    workspaceId, activeSourceDetail, setActiveSourceKey, setActiveSourceDetail,
    setBusyKey, setSourceErr, setDeleteRequest, refreshSources,
  } = deps;

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
      const result = await api.deleteGeneratedAsset(workspaceId, sourceKey, assetKey);
      if (result.catalog_rows_deleted > 0) {
        setActiveSourceKey(null);
        setActiveSourceDetail(null);
      } else {
        const nextDetail = await api.getDataSourceDetail(workspaceId, sourceKey);
        setActiveSourceDetail(mergeDetailMetrics(
          nextDetail,
          activeSourceDetail?.entity_summary ?? {},
        ));
      }
      await refreshSources();
      if (result.graph_sync === "repair_required") {
        setSourceErr(
          "Asset data was deleted, but the graph view still needs repair.",
        );
      }
    } catch (e) {
      setSourceErr(e instanceof Error ? e.message : "asset delete failed");
    } finally {
      setBusyKey(null);
    }
  };

  return { downloadAsset, previewAsset, deleteAsset, deleteAssetByKey };
}
