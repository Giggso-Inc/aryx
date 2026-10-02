import type { DiscoveryHistoryItem, DiscoverySummary } from "../types";
import { fetchWithShayAuth, createHttpStatusError, readErrorDetail } from "../shay-session";
import { fetchJSON } from "./core";

export const ingestFlowsApi = {
  // ── Database connect → discover → ingest ─────────────────────────────
  dbConnect: (cfg: {
    dialect?: string; host?: string; port?: string;
    database?: string; user?: string; password?: string; url?: string;
  }) =>
    fetchJSON<{ connection_id: string; tables: string[]; schema: Array<{ table: string; columns: string[] }> }>(
      "/admin/connect",
      { method: "POST", body: JSON.stringify(cfg) },
    ),

  dbDiscover: (connectionId: string, context: string) =>
    fetchJSON<{
      tables: Array<{ table: string; ontology_type: string; match_keys: string[] }>;
      edges: Array<{ source_type: string; target_type: string; name: string }>;
    }>(
      "/admin/discover",
      { method: "POST", body: JSON.stringify({ connection_id: connectionId, context }) },
    ),

  dbIngestMulti: (connectionId: string, tables: Array<{ table: string; ontology_type: string; match_keys: string[] }>, edges: Array<{ source_type: string; target_type: string; name: string }>, workspaceId: number) =>
    fetchJSON<{ job_id: string; tables: string[] }>(
      "/admin/ingest/multi",
      { method: "POST", body: JSON.stringify({ connection_id: connectionId, tables, edges, workspace_id: workspaceId }) },
    ),

  // ── Document discovery (read → summary → confirm) ─────────────────────
  readDocs: async (workspaceId: number, files: File[], context = "") => {
    const form = new FormData();
    for (const f of files) form.append("files", f);
    form.append("context", context);
    form.append("workspace_id", String(workspaceId));
    const res = await fetchWithShayAuth("/api/admin/docs/read", {
      method: "POST",
      body: form,
    });
    if (!res.ok) {
      const detail = await readErrorDetail(res);
      throw createHttpStatusError(res.status, res.statusText, detail);
    }
    return res.json() as Promise<{ discovery_id: string }>;
  },

  getDiscoverySummary: (discoveryId: string, workspaceId = 1) =>
    fetchJSON<DiscoverySummary>(`/admin/docs/summary/${discoveryId}?workspace_id=${workspaceId}`),

  listDiscoveries: (workspaceId = 1) =>
    fetchJSON<DiscoveryHistoryItem[]>(`/admin/docs/history?workspace_id=${workspaceId}`),

  dismissDiscovery: (discoveryId: string, workspaceId = 1) =>
    fetchJSON<{ status: string }>(
      `/admin/docs/${discoveryId}/dismiss?workspace_id=${workspaceId}`,
      { method: "POST" },
    ),

  confirmDiscovery: (
    discoveryId: string,
    approvedTypes: string[],
    approvedFiles: string[] = [],
    workspaceId = 1,
    resumeJobId?: string,
    restart = false,
  ) =>
    fetchJSON<{ status: string; job_id: string }>("/admin/docs/confirm", {
      method: "POST",
      body: JSON.stringify({
        discovery_id: discoveryId,
        approved_types: approvedTypes,
        approved_files: approvedFiles,
        workspace_id: workspaceId,
        restart,
        ...(resumeJobId ? { resume_job_id: resumeJobId } : {}),
      }),
    }),

  // ── REST API ingest ───────────────────────────────────────────────────
  previewRestIngest: (req: {
    workspace_id: number; url: string; headers?: Record<string, string>;
    record_path?: string; page_param?: string; next_page_path?: string; context?: string;
  }) => fetchJSON<{ sample: unknown[]; count: number; inferred_type: string }>(
    "/ingest/rest/preview",
    { method: "POST", body: JSON.stringify(req) },
  ),

  startRestIngest: (req: {
    workspace_id: number; url: string; headers?: Record<string, string>;
    record_path?: string; page_param?: string; next_page_path?: string;
    max_pages?: number; ontology_type?: string; match_keys?: string[]; context?: string;
  }) => fetchJSON<{ status: string; job_id: string }>(
    "/ingest/rest/ingest",
    { method: "POST", body: JSON.stringify(req) },
  ),
};
