import type { ShayDatasource, ShayDatasourceList } from "../shay-types";
import { requestJSON, cachedRequestJSON, invalidateShayCache, normalizeDatasourceList, query } from "./http";
import { SHAY_BASE } from "./constants";

export const datasourcesApi = {
  listDatasources: (workspaceId: string, token: string) =>
    cachedRequestJSON<ShayDatasourceList>(
      `datasources:${workspaceId}`,
      10_000,
      SHAY_BASE,
      `/gg-datasources/${query({ level: "workspace", workspace_id: workspaceId, page_size: 100 })}`,
      token,
    ).then(normalizeDatasourceList),

  createDatasource: (
    payload: {
      workspace_id: string;
      name: string;
      storage_type: string;
      provider?: string;
      app_type?: string;
      file_url?: string;
      filename?: string;
      config?: Record<string, unknown>;
      datasource_metadata?: Record<string, unknown>;
    },
    token: string,
  ) =>
    requestJSON<ShayDatasource>(
      SHAY_BASE,
      "/gg-datasources/",
      {
        method: "POST",
        body: JSON.stringify({
          level: "workspace",
          workspace_id: payload.workspace_id,
          name: payload.name,
          storage_type: payload.storage_type,
          provider: payload.provider,
          app_type: payload.app_type,
          filename: payload.filename,
          file_url: payload.file_url,
          config: payload.config ?? {},
          datasource_metadata: payload.datasource_metadata ?? {},
          is_embedding_required: false,
        }),
      },
      token,
    ).then((result) => {
      invalidateShayCache(`datasources:${payload.workspace_id}`);
      return result;
    }),
};
