import type {
  AbResult, AskResponse, AskHistoryTurn, Axiom, Brief, DataEntitiesPage,
  DataSourceCatalogItem, DataSourceCatalogPage, DataSourceDetail, DataSummary,
  Datasource, DiscoverySummary, GraphView,
  IngestQuestion, McpToken, McpTokenIssued, ObservabilityData, OntologyChange,
  OntologyDoc, OntologyVersion, QuizSpec, ReasonerCheck, Rule,
  GenericSourcePreview, SourceEntityTypesPage, SourceRecordsPage,
  SurvivorshipPolicy, Workspace,
} from "./types";
import {
  createHttpStatusError,
  fetchWithShayAuth,
  readErrorDetail,
} from "./shay-session";

// Same-origin relative path. Next.js rewrites /api/* → FastAPI internally
// (see next.config.mjs). Works in dev (proxies to localhost:8088) and in
// production (proxies to api:8000) without any client-side knowledge.
const BASE = "/api";

/** Throw on non-2xx; return parsed JSON otherwise. */
async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetchWithShayAuth(`${BASE}${path}`, {
    ...init,
    headers,
  });
  if (!res.ok) {
    const detail = await readErrorDetail(res);
    throw createHttpStatusError(res.status, res.statusText, detail);
  }
  return res.json() as Promise<T>;
}

async function fetchBlob(path: string, init?: RequestInit): Promise<Blob> {
  const res = await fetchWithShayAuth(`${BASE}${path}`, init);
  if (!res.ok) {
    const detail = await readErrorDetail(res);
    throw createHttpStatusError(res.status, res.statusText, detail);
  }
  return res.blob();
}

export const api = {
  listWorkspaces: () =>
    fetchJSON<Workspace[]>("/admin/workspaces"),

  createWorkspace: (name: string, description = "", context = "") =>
    fetchJSON<Workspace>("/admin/workspaces", {
      method: "POST",
      body: JSON.stringify({ name, description, context }),
    }),

  ask: (question: string, workspaceId: number, history: unknown[] = [], sessionData: Record<string, unknown> = {}) =>
    fetchJSON<AskResponse>("/ask", {
      method: "POST",
      body: JSON.stringify({ question, workspace_id: workspaceId, history, session_data: sessionData }),
    }),

  shareConfig: (args: {
    workspaceId: number; conversationId: string; configJson: Record<string, unknown>;
    endpointUrl: string; authHeaderName: string; authHeaderValue: string;
    extraHeaders?: Record<string, string>;
  }) =>
    fetchJSON<{ shared: boolean; partner_response: unknown }>("/share-config", {
      method: "POST",
      body: JSON.stringify({
        workspace_id: args.workspaceId,
        conversation_id: args.conversationId,
        config_json: args.configJson,
        endpoint_url: args.endpointUrl,
        auth_header_name: args.authHeaderName,
        auth_header_value: args.authHeaderValue,
        extra_headers: args.extraHeaders ?? {},
      }),
    }),

  // ── Accuracy Lab (v2) ────────────────────────────────────────────────
  labAb: (question: string, workspaceId: number) =>
    fetchJSON<AbResult & { error?: string }>("/lab/ab", {
      method: "POST",
      body: JSON.stringify({ question, workspace_id: workspaceId }),
    }),

  labReasoner: (workspaceId: number) =>
    fetchJSON<ReasonerCheck & { error?: string }>(
      `/lab/reasoner?workspace_id=${workspaceId}`,
    ),

  // ── Data Explorer (v2) ───────────────────────────────────────────────
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
    fetchJSON<{ status: string; source_key: string }>(
      `/data/sources/${encodeURIComponent(sourceKey)}?workspace_id=${workspaceId}`,
      { method: "DELETE" },
    ),

  downloadGeneratedAsset: (workspaceId: number, sourceKey: string, assetKey: string) =>
    fetchBlob(
      `/data/sources/${encodeURIComponent(sourceKey)}/assets/${encodeURIComponent(assetKey)}/download?workspace_id=${workspaceId}`,
    ),

  deleteGeneratedAsset: (workspaceId: number, sourceKey: string, assetKey: string) =>
    fetchJSON<{ status: string; source_key: string; asset_key: string }>(
      `/data/sources/${encodeURIComponent(sourceKey)}/assets/${encodeURIComponent(assetKey)}?workspace_id=${workspaceId}`,
      { method: "DELETE" },
    ),

  // ── Ontology / modelling ──────────────────────────────────────────────
  getOntology: (workspaceId: number) =>
    fetchJSON<OntologyDoc>(`/ontology/types?workspace_id=${workspaceId}`),

  createType: (workspaceId: number, name: string, attributes: string[]) =>
    fetchJSON<{ status: string }>("/ontology/types", {
      method: "POST",
      body: JSON.stringify({ name, attributes, workspace_id: workspaceId }),
    }),

  approveType: (workspaceId: number, name: string) =>
    fetchJSON<{ status: string }>(
      `/ontology/types/${encodeURIComponent(name)}/approve?workspace_id=${workspaceId}`,
      { method: "POST", body: "{}" },
    ),

  setTypeParent: (workspaceId: number, name: string, parent: string | null) =>
    fetchJSON<{ status: string }>(
      `/ontology/types/${encodeURIComponent(name)}/parent?workspace_id=${workspaceId}`,
      { method: "POST", body: JSON.stringify({ parent }) },
    ),

  deleteType: (workspaceId: number, name: string) =>
    fetchJSON<{ status: string }>(
      `/ontology/types/${encodeURIComponent(name)}?workspace_id=${workspaceId}`,
      { method: "DELETE" },
    ),

  deleteRelationshipType: (relId: number) =>
    fetchJSON<{ status: string }>(
      `/ontology/relationships/${relId}`,
      { method: "DELETE" },
    ),

  getAxioms: (workspaceId: number) =>
    fetchJSON<{ axioms: Axiom[] }>(`/ontology/axioms?workspace_id=${workspaceId}`)
      .then((d) => d.axioms || []),

  getRules: (workspaceId: number) =>
    fetchJSON<Rule[]>(`/rules?workspace_id=${workspaceId}`),

  getSurvivorship: (workspaceId: number) =>
    fetchJSON<{ workspace_id: number; survivorship: SurvivorshipPolicy }>(
      `/admin/workspaces/${workspaceId}/survivorship`,
    ).then((d) => d.survivorship || {}),

  setSurvivorship: (workspaceId: number, policy: SurvivorshipPolicy) =>
    fetchJSON<{ id: number; survivorship: SurvivorshipPolicy }>(
      `/admin/workspaces/${workspaceId}/survivorship`,
      { method: "PUT", body: JSON.stringify(policy) },
    ),

  updateTypeAttrs: (workspaceId: number, name: string,
                    attributes: string[]) =>
    fetchJSON<{ status: string }>("/ontology/types", {
      method: "POST",
      body: JSON.stringify({ name, attributes, workspace_id: workspaceId }),
    }),

  getJob: (jobId: string) =>
    fetchJSON<{
      job_id: string; status: string; stage: string | null;
      pct: number | null; detail: string | null; error: string | null;
    }>(`/admin/jobs/${jobId}`),

  listJobs: (workspaceId: number) =>
    fetchJSON<Array<{
      job_id: string; source_system: string; source_dataset: string;
      status: string; stage: string | null; pct: number | null;
      detail: string | null; error: string | null;
      started_at?: string; finished_at?: string | null;
    }>>(`/admin/jobs?workspace_id=${workspaceId}`),

  getJobEvents: (jobId: string) =>
    fetchJSON<Array<{
      stage: string; pct: number; detail: string; ts: string;
    }>>(`/admin/jobs/${jobId}/events`),

  cancelJob: (jobId: string) =>
    fetchJSON<{ status: string; job_id: string }>(
      `/admin/jobs/${jobId}/cancel`, { method: "POST", body: "{}" },
    ),

  getIngestQuestions: (workspaceId: number, status = "pending") =>
    fetchJSON<IngestQuestion[]>(
      `/admin/ingest-questions?workspace_id=${workspaceId}&status=${status}&limit=50`,
    ),

  answerIngestQuestion: (questionId: number, answer: string,
                         answeredBy = "ui") =>
    fetchJSON<{ id: number; status: string; answer: string }>(
      `/admin/ingest-questions/${questionId}/answer`,
      { method: "POST", body: JSON.stringify({ answer, answered_by: answeredBy }) },
    ),

  getIngestQuestionStats: (workspaceId: number) =>
    fetchJSON<Record<string, number>>(
      `/admin/ingest-questions/stats?workspace_id=${workspaceId}`,
    ),

  // ── Declared relationship types (option g) ───────────────────────────
  listRelationshipTypes: (workspaceId: number) =>
    fetchJSON<Array<{
      id: number; name: string; source_type: string; target_type: string;
    }>>(`/ontology/relationships?workspace_id=${workspaceId}`),

  createRelationshipType: (workspaceId: number, name: string,
                            sourceType: string, targetType: string) =>
    fetchJSON<{ id: number; name: string }>("/ontology/relationships", {
      method: "POST",
      body: JSON.stringify({
        workspace_id: workspaceId, name,
        source_type: sourceType, target_type: targetType,
      }),
    }),

  // ── Wizard / guided setup (Slice W3) ─────────────────────────────────
  // draft-brief runs as a background job to avoid ECONNRESET on long LLM
  // calls through the Next.js proxy (Docker WSL2 drops idle connections).
  draftBrief: async (workspaceId: number, seed: string, docText = "", signal?: AbortSignal) => {
    // 1. Start the background job — returns immediately.
    const { job_id } = await fetchJSON<{ job_id: string }>(
      `/admin/workspaces/${workspaceId}/draft-brief`,
      {
        method: "POST",
        body: JSON.stringify({ seed, doc_text: docText, workspace_id: workspaceId }),
        signal,
      },
    );
    // 2. Poll until done (up to ~3 minutes, 1.5 s interval).
    const delay = (ms: number) => new Promise<void>((r) => {
      const t = setTimeout(r, ms);
      signal?.addEventListener("abort", () => clearTimeout(t), { once: true });
    });
    for (let i = 0; i < 120; i++) {
      await delay(1500);
      if (signal?.aborted) throw new DOMException("Brief drafting cancelled", "AbortError");
      const j = await fetchJSON<{
        status: string; error: string | null;
      }>(`/admin/jobs/${job_id}`, { signal });
      if (j.status === "failed") {
        throw new Error(`Brief drafting failed: ${j.error ?? "unknown"}`);
      }
      if (j.status === "complete") {
        // 3. Retrieve the brief from the in-process result store.
        return fetchJSON<{ workspace_id: number; brief: Brief }>(
          `/admin/workspaces/${workspaceId}/brief-result/${job_id}`,
          { signal },
        );
      }
    }
    throw new Error("Brief drafting timed out — please retry.");
  },

  saveBrief: (workspaceId: number, brief: Brief) =>
    fetchJSON<{ id: number; brief: Brief }>(
      `/admin/workspaces/${workspaceId}/brief`,
      { method: "PATCH", body: JSON.stringify(brief) },
    ),

  listDatasourceKinds: () =>
    fetchJSON<{ kinds: Array<{ kind: string; label?: string }>;
                secret_key_configured: boolean }>("/admin/datasources/kinds"),

  getDatasourceQuiz: (kind: string) =>
    fetchJSON<QuizSpec>(`/admin/datasources/quiz?kind=${encodeURIComponent(kind)}`),

  listDatasources: (workspaceId: number) =>
    fetchJSON<Datasource[]>(`/admin/datasources?workspace_id=${workspaceId}`),

  addDatasource: (workspaceId: number, name: string, kind: string,
                  config: Record<string, unknown>, secret = "") =>
    fetchJSON<Datasource>("/admin/datasources", {
      method: "POST",
      body: JSON.stringify({ workspace_id: workspaceId, name, kind,
                              config, secret }),
    }),

  testDatasource: (datasourceId: number) =>
    fetchJSON<{ ok: boolean; error?: string; tables?: string[];
                 files?: string[] }>(
      `/admin/datasources/${datasourceId}/test`, { method: "POST", body: "{}" },
    ),

  /** Multipart file upload → kicks the file ingest pipeline server-side. */
  uploadFiles: async (workspaceId: number, files: File[],
                       ontologyType = "Document",
                       matchKeys = "name") => {
    const form = new FormData();
    for (const f of files) form.append("files", f);
    form.append("ontology_type", ontologyType);
    form.append("match_keys", matchKeys);
    form.append("workspace_id", String(workspaceId));
    const res = await fetchWithShayAuth(`${BASE}/admin/ingest/file`, {
      method: "POST",
      body: form,
    });
    if (!res.ok) {
      const detail = await readErrorDetail(res);
      throw createHttpStatusError(res.status, res.statusText, detail);
    }
    return res.json() as Promise<{ status: string; job_id: string }>;
  },

  // ── AI ontology assist (option f) ────────────────────────────────────
  suggestAttrs: (workspaceId: number, typeName: string, existing: string[]) =>
    fetchJSON<{ attributes: string[]; rationale: string }>(
      "/ontology/assist/suggest-attrs",
      {
        method: "POST",
        body: JSON.stringify({
          workspace_id: workspaceId, type_name: typeName, existing,
        }),
      },
    ),

  // ── Entity graph (FalkorDB) ───────────────────────────────────────────
  getEntity: (entityId: number, workspaceId: number) =>
    fetchJSON<{
      id: number;
      type: string;
      name: string;
      attributes?: Record<string, unknown>;
    }>(`/entities/${entityId}?workspace_id=${workspaceId}`),

  getEntityGraph: (workspaceId: number) =>
    fetchJSON<{
      entities: Array<{ id: number; type: string; name: string; attributes?: Record<string, unknown> }>;
      relationships: Array<{ source: number; target: number; name: string }>;
    }>(`/graph?workspace_id=${workspaceId}`),

  getEntityGraphOverview: (workspaceId: number) =>
    fetchJSON<{
      domain: string;
      overview_nodes: Array<{ id: string; type: string; count: number; entity_ids: number[] }>;
      overview_edges: Array<{ source: string; target: string; name: string; count: number }>;
      matched_entity_ids: number[];
      matched_edge_pairs: Array<{ source: number; target: number }>;
      matched_types: string[];
      fallback_used: boolean;
      entity_count: number;
      relationship_count: number;
    }>(`/graph/overview?workspace_id=${workspaceId}`),

  getEntityNeighbors: (entityId: number, workspaceId: number) =>
    fetchJSON<Array<{
      id: number;
      type: string;
      name: string;
      attributes?: Record<string, unknown>;
      relationship: string;
      direction: "in" | "out";
    }>>(
      `/entities/${entityId}/neighbors?workspace_id=${workspaceId}`,
    ),

  getEntityPath: (srcId: number, dstId: number, workspaceId: number) =>
    fetchJSON<Array<{ id: number; type: string; name: string }>>(
      `/entities/${srcId}/path/${dstId}?workspace_id=${workspaceId}`,
    ),

  // ── Observability ─────────────────────────────────────────────────────
  getObservability: (workspaceId: number) =>
    fetchJSON<ObservabilityData>(
      `/admin/observability?workspace_id=${workspaceId}`,
    ),

  // ── Ask history ───────────────────────────────────────────────────────
  getAskHistory: (workspaceId: number, limit = 50) =>
    fetchJSON<AskHistoryTurn[]>(
      `/ask/history?workspace_id=${workspaceId}&limit=${limit}`,
    ),

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

  getDiscoverySummary: (discoveryId: string) =>
    fetchJSON<DiscoverySummary>(`/admin/docs/summary/${discoveryId}`),

  confirmDiscovery: (discoveryId: string, approvedTypes: string[], approvedFiles: string[] = []) =>
    fetchJSON<{ status: string; job_id: string }>("/admin/docs/confirm", {
      method: "POST",
      body: JSON.stringify({
        discovery_id: discoveryId,
        approved_types: approvedTypes,
        approved_files: approvedFiles,
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

  // ── MCP tokens ────────────────────────────────────────────────────────
  listMcpTokens: () =>
    fetchJSON<McpToken[]>("/admin/mcp/tokens"),

  issueMcpToken: (label: string) =>
    fetchJSON<McpTokenIssued>("/admin/mcp/tokens", {
      method: "POST",
      body: JSON.stringify({ label }),
    }),

  revokeMcpToken: (tokenId: number) =>
    fetchJSON<{ status: string }>(`/admin/mcp/tokens/${tokenId}`, {
      method: "DELETE",
    }),

  // ── Workspace management ──────────────────────────────────────────────
  updateWorkspaceContext: (workspaceId: number, context: string) =>
    fetchJSON<Workspace>(`/admin/workspaces/${workspaceId}/context`, {
      method: "PATCH",
      body: JSON.stringify({ context }),
    }),

  purgeWorkspace: (workspaceId: number) =>
    fetchJSON<{ status: string }>(`/admin/workspaces/${workspaceId}/purge`, {
      method: "POST", body: "{}",
    }),

  deleteWorkspace: (workspaceId: number) =>
    fetchJSON<{ status: string }>(`/admin/workspaces/${workspaceId}`, {
      method: "DELETE",
    }),

  nukeAllWorkspaces: () =>
    fetchJSON<{ status: string }>("/admin/workspaces/nuke", {
      method: "POST", body: "{}",
    }),

  autoLinkWorkspace: (workspaceId: number) =>
    fetchJSON<{ links_created: number; specs: Array<Record<string, unknown>> }>(
      `/admin/workspaces/${workspaceId}/auto-link`,
      { method: "POST", body: "{}" },
    ),

  // ── Ontology rules ────────────────────────────────────────────────────
  createRule: (workspaceId: number, rule: Omit<Rule, "enabled">) =>
    fetchJSON<{ status: string }>("/rules", {
      method: "POST",
      body: JSON.stringify({ ...rule, workspace_id: workspaceId }),
    }),

  toggleRule: (name: string, workspaceId: number, enabled: boolean) =>
    fetchJSON<{ status: string }>(`/rules/${encodeURIComponent(name)}/enabled?workspace_id=${workspaceId}`, {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    }),

  deleteRule: (name: string, workspaceId: number) =>
    fetchJSON<{ status: string }>(
      `/rules/${encodeURIComponent(name)}?workspace_id=${workspaceId}`,
      { method: "DELETE" },
    ),

  evaluateRules: (workspaceId: number) =>
    fetchJSON<{ violations: number; applied: number }>(
      `/rules/evaluate?workspace_id=${workspaceId}`,
      { method: "POST", body: "{}" },
    ),

  // ── Ontology versions ─────────────────────────────────────────────────
  listOntologyVersions: (workspaceId: number) =>
    fetchJSON<OntologyVersion[]>(`/ontology-versions?workspace_id=${workspaceId}`),

  createOntologySnapshot: (workspaceId: number, label = "") =>
    fetchJSON<OntologyVersion>("/ontology-versions", {
      method: "POST",
      body: JSON.stringify({ workspace_id: workspaceId, label }),
    }),

  getOntologyChanges: (workspaceId: number) =>
    fetchJSON<OntologyChange[]>(`/ontology-versions/changes?workspace_id=${workspaceId}`),

  // ── Ontology interchange (publish / import) ───────────────────────────
  getOntologyConfig: () =>
    fetchJSON<{ enabled: boolean; formats: string[]; base_uri?: string }>(
      "/ontology/config",
    ),

  getOntologyFormats: () =>
    fetchJSON<Array<{ name: string; extension: string }>>(
      "/ontology/formats",
    ),

  setOntologyConfig: (config: { enabled: boolean; formats: string[]; base_uri?: string; include_provenance?: boolean }) =>
    fetchJSON<{ enabled: boolean; formats: string[] }>(
      "/ontology/config",
      { method: "POST", body: JSON.stringify(config) },
    ),

  exportOntology: async (workspaceId: number, format: string): Promise<Blob> => {
    const res = await fetchWithShayAuth(
      `${BASE}/ontology/export?workspace_id=${workspaceId}&format=${encodeURIComponent(format)}`,
      undefined,
    );
    if (!res.ok) {
      const detail = await readErrorDetail(res);
      throw createHttpStatusError(res.status, res.statusText, detail);
    }
    return res.blob();
  },

  importOntology: (workspaceId: number, content: string, format: string, filename: string) =>
    fetchJSON<{ imported: number; types: string[]; message?: string }>(
      "/ontology/import",
      {
        method: "POST",
        body: JSON.stringify({ workspace_id: workspaceId, content, format, filename }),
      },
    ),
};
