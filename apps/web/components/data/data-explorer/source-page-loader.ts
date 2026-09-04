import { api } from "@/lib/api";
import type { DataSourceCatalogPage, DataSourceDetail } from "@/lib/types";
import type { SourceFilter } from "../SourcesLens";

export async function loadSourcesPage(
  workspaceId: number,
  options: { page: number; pageSize: number; query: string; category: SourceFilter },
): Promise<DataSourceCatalogPage> {
  const result = await api.listDataSourcesPage(workspaceId, options);
  const isUnfilteredSingleSource = options.query.trim() === ""
    && options.category === "all"
    && result.total === 1
    && result.items.length === 1;
  if (!isUnfilteredSingleSource || result.items[0].edge_count != null) return result;

  try {
    const overview = await api.getEntityGraphOverview(workspaceId);
    return {
      ...result,
      items: [{ ...result.items[0], edge_count: overview.relationship_count }],
    };
  } catch {
    return result;
  }
}

export function mergeDetailMetrics(
  detail: DataSourceDetail,
  fallback: { total_entities?: number; node_count?: number; edge_count?: number },
): DataSourceDetail {
  return {
    ...detail,
    entity_summary: {
      ...detail.entity_summary,
      node_count: detail.entity_summary.node_count
        ?? fallback.node_count
        ?? fallback.total_entities
        ?? detail.entity_summary.total_entities,
      edge_count: detail.entity_summary.edge_count ?? fallback.edge_count,
    },
  };
}

export function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
