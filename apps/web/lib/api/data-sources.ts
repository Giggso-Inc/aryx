import type {
  DataEntitiesPage, DataSourceCatalogItem, DataSourceCatalogPage, DataSourceDetail,
  DataSummary, GenericSourcePreview, GraphView, SourceEntityTypesPage, SourceRecordsPage,
} from "../types";
import { fetchBlob, fetchJSON, type DataSourceDeleteResult } from "./core";

export const dataSourcesApi = {
  dataSummary: (workspaceId: number) =>
    fetchJSON<DataSummary & { error?: string }>(
      `/data/summary?workspace_id=${workspaceId}`,
    ),

  dataEntities: (workspaceId: number, type?: string,
                 limit = 50, offset = 0) =>
    fetchJSON<DataEntitiesPage & { error?: string }>(
      `/data/entities?workspace_id=${workspaceId}` +
        (type ? `&type=${encodeURIComponent(type)}` : "") +
        `&limit=${limit}&offset=${offset}`,
    ),

  dataGraph: (workspaceId: number) =>
    fetchJSON<GraphView & { error?: string }>(
      `/data/graph?workspace_id=${workspaceId}`,
    ),

  listDataSources: (workspaceId: number) =>
    fetchJSON<DataSourceCatalogItem[]>(`/data/sources?workspace_id=${workspaceId}`),

  listDataSourcesPage: (
    workspaceId: number,
    args: { page?: number; pageSize?: number; query?: string; category?: string } = {},
  ) => {
    const params = new URLSearchParams({
      workspace_id: String(workspaceId),
      page: String(args.page ?? 1),
      page_size: String(args.pageSize ?? 50),
      q: args.query ?? "",
      category: args.category ?? "all",
    });
    return fetchJSON<DataSourceCatalogPage>(`/data/sources/page?${params.toString()}`);
  },

  getDataSourceDetail: (workspaceId: number, sourceKey: string) =>
    fetchJSON<DataSourceDetail>(
      `/data/sources/${encodeURIComponent(sourceKey)}?workspace_id=${workspaceId}`,
    ),

  getSourceEntityTypes: (
    workspaceId: number, sourceKey: string, page = 1, query = "",
  ) => fetchJSON<SourceEntityTypesPage>(
    `/data/sources/${encodeURIComponent(sourceKey)}/entity-types` +
    `?workspace_id=${workspaceId}&page=${page}&page_size=50&q=${encodeURIComponent(query)}`,
  ),

  getSourceRecords: (workspaceId: number, sourceKey: string, page = 1) =>
    fetchJSON<SourceRecordsPage>(
      `/data/sources/${encodeURIComponent(sourceKey)}/records` +
      `?workspace_id=${workspaceId}&page=${page}&page_size=25`,
    ),

  getDataSourcePreview: (workspaceId: number, sourceKey: string) =>
    fetchJSON<GenericSourcePreview>(
      `/data/sources/${encodeURIComponent(sourceKey)}/preview?workspace_id=${workspaceId}`,
    ),

  downloadDataSource: (workspaceId: number, sourceKey: string) =>
    fetchBlob(`/data/sources/${encodeURIComponent(sourceKey)}/download?workspace_id=${workspaceId}`),

  deleteDataSource: (workspaceId: number, sourceKey: string) =>
    fetchJSON<DataSourceDeleteResult>(
      `/data/sources/${encodeURIComponent(sourceKey)}?workspace_id=${workspaceId}`,
      { method: "DELETE" },
    ),

  downloadGeneratedAsset: (workspaceId: number, sourceKey: string, assetKey: string) =>
    fetchBlob(
      `/data/sources/${encodeURIComponent(sourceKey)}/assets/${encodeURIComponent(assetKey)}/download?workspace_id=${workspaceId}`,
    ),

  deleteGeneratedAsset: (workspaceId: number, sourceKey: string, assetKey: string) =>
    fetchJSON<DataSourceDeleteResult>(
      `/data/sources/${encodeURIComponent(sourceKey)}/assets/${encodeURIComponent(assetKey)}?workspace_id=${workspaceId}`,
      { method: "DELETE" },
    ),
};
