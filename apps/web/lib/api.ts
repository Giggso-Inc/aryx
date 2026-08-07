import type {
  AbResult, AskResponse, Axiom, Brief, DataEntitiesPage, DataSummary,
  Datasource, DiscoverySummary, EntityDetail, EntityGraphView, GraphNeighbor,
  GraphPathStep, GraphView,
  IngestQuestion, LlmConfig, LlmConfigUpdate, OntologyChange, OntologyConfig,
  OntologyDoc, OntologyFormat, OntologyImportResult, OntologyVersion, QuizSpec,
  ReasonerCheck, Rule, RuleEvaluationResult, SupportedFileTypes,
  SurvivorshipPolicy, Workspace, WorkspaceRule,
} from "./types";

// Same-origin relative path. Next.js rewrites /api/* → FastAPI internally
// (see next.config.mjs). Works in dev (proxies to localhost:8088) and in
// production (proxies to api:8000) without any client-side knowledge.
const BASE = "/api";

/** A failed request's HTTP status is attached so callers can tell a
 *  permanent failure (404 — job gone) from a transient one (network blip,
 *  5xx) instead of treating every error the same way. */
export class HttpStatusError extends Error {
  status: number;
  constructor(status: number, statusText: string, detail: string) {
    super(`${status} ${statusText}: ${detail}`);
    this.status = status;
  }
}

export function isHttpStatusError(err: unknown, status: number): boolean {
  return err instanceof HttpStatusError && err.status === status;
}

/** Throw on non-2xx; return parsed JSON otherwise. */
async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
    ...init,
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new HttpStatusError(res.status, res.statusText, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  listWorkspaces: () =>
    fetchJSON<Workspace[]>("/admin/workspaces?workspace_id=1"),

  createWorkspace: (name: string, description = "") =>
    fetchJSON<Workspace>("/admin/workspaces", {
      method: "POST",
      body: JSON.stringify({ name, description, context: "" }),
    }),

  ask: (question: string, workspaceId: number, history: unknown[] = []) =>
    fetchJSON<AskResponse>("/ask", {
      method: "POST",
      body: JSON.stringify({ question, workspace_id: workspaceId, history }),
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

  dataGraphEntity: (workspaceId: number) =>
    fetchJSON<EntityGraphView & { error?: string }>(
      `/data/graph?workspace_id=${workspaceId}&level=entity`,
    ),

  dataEntityDetail: (workspaceId: number, entityId: number) =>
    fetchJSON<EntityDetail & { error?: string }>(
      `/data/entity/${entityId}?workspace_id=${workspaceId}`,
    ),

  // ── Graph explorer (/graph) ──────────────────────────────────────────
  // Overview reuses the existing type-level `/data/graph` shape (no
  // separate aggregation endpoint needed — same store query as dataGraph).
  getGraphOverview: (workspaceId: number) =>
    fetchJSON<GraphView & { error?: string }>(
      `/data/graph?workspace_id=${workspaceId}&level=type`,
    ),

  // Neighbors/path are served by the FalkorDB-backed graph_api.py, which
  // shares the exact same entity-id space as the Postgres EntityStore
  // (project_graph mints Falkor node ids straight from EntityStore ids).
  getEntityNeighbors: (workspaceId: number, entityId: number) =>
    fetchJSON<GraphNeighbor[]>(
      `/entities/${entityId}/neighbors?workspace_id=${workspaceId}`,
    ),

  getEntityPath: (workspaceId: number, sourceId: number, targetId: number,
                  maxHops = 6) =>
    fetchJSON<GraphPathStep[]>(
      `/entities/${sourceId}/path/${targetId}` +
        `?workspace_id=${workspaceId}&max_hops=${maxHops}`,
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
    fetchJSON<{ rules: Rule[] }>(`/ontology/rules?workspace_id=${workspaceId}`)
      .then((d) => d.rules || []),

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
  draftBrief: (workspaceId: number, seed: string, docText = "") =>
    fetchJSON<{ workspace_id: number; brief: Brief }>(
      `/admin/workspaces/${workspaceId}/draft-brief`,
      {
        method: "POST",
        body: JSON.stringify({ seed, doc_text: docText, workspace_id: workspaceId }),
      },
    ),

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
    const res = await fetch(`${BASE}/admin/ingest/file`,
                            { method: "POST", body: form });
    if (!res.ok) {
      const detail = await res.text().catch(() => "");
      throw new Error(`${res.status} ${res.statusText}: ${detail}`);
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

  // ── LLM provider (runtime; process memory — not persisted to disk) ──
  getLlmConfig: () => fetchJSON<LlmConfig>("/llm/config"),

  setLlmConfig: (cfg: LlmConfigUpdate) =>
    fetchJSON<LlmConfig>("/admin/llm/config", {
      method: "POST",
      body: JSON.stringify(cfg),
    }),

  // ── Document self-discovery (read → summary → confirm) ───────────────
  getSupportedFileTypes: () =>
    fetchJSON<SupportedFileTypes>("/admin/ingest/supported"),

  /** Multipart upload → kicks the read/discovery job. The returned
   *  discovery_id doubles as a job id (see JobStore.create in
   *  doc_discover_api.py), so callers can track "reading" progress via
   *  api.getJob(discoveryId) exactly like any other job. */
  readDocs: async (files: File[], context: string, workspaceId: number) => {
    const form = new FormData();
    for (const f of files) form.append("files", f);
    form.append("context", context);
    form.append("workspace_id", String(workspaceId));
    const res = await fetch(`${BASE}/admin/docs/read`,
                            { method: "POST", body: form });
    if (!res.ok) {
      const detail = await res.text().catch(() => "");
      throw new HttpStatusError(res.status, res.statusText, detail);
    }
    return res.json() as Promise<{ discovery_id: string }>;
  },

  /** Returns `{}` while the read job is still running. */
  getDiscoverySummary: (discoveryId: string) =>
    fetchJSON<DiscoverySummary>(`/admin/docs/summary/${discoveryId}`),

  confirmDiscovery: (discoveryId: string, approvedTypes: string[] = [],
                     approvedFiles: string[] = []) =>
    fetchJSON<{ status: string; job_id: string }>("/admin/docs/confirm", {
      method: "POST",
      body: JSON.stringify({
        discovery_id: discoveryId,
        approved_types: approvedTypes,
        approved_files: approvedFiles,
      }),
    }),

  // ── Ontology interchange (import / export / config) — Model tabs ─────
  getOntologyConfig: () => fetchJSON<OntologyConfig>("/ontology/config"),

  setOntologyConfig: (cfg: { enabled?: boolean; formats?: string[];
                             base_uri?: string; include_provenance?: boolean }) =>
    fetchJSON<OntologyConfig>("/ontology/config", {
      method: "POST",
      body: JSON.stringify(cfg),
    }),

  getOntologyFormats: () => fetchJSON<OntologyFormat[]>("/ontology/formats"),

  /** format="" lets the backend guess from the filename extension. */
  importOntology: (workspaceId: number, content: string, format: string,
                    filename: string) =>
    fetchJSON<OntologyImportResult>("/ontology/import", {
      method: "POST",
      body: JSON.stringify({ content, format, filename, workspace_id: workspaceId }),
    }),

  /** Returns the raw exported document as text (caller triggers download). */
  exportOntology: async (workspaceId: number, format: string) => {
    const res = await fetch(
      `${BASE}/ontology/export?workspace_id=${workspaceId}&format=${encodeURIComponent(format)}`,
      { cache: "no-store" },
    );
    if (!res.ok) {
      const detail = await res.text().catch(() => "");
      throw new HttpStatusError(res.status, res.statusText, detail);
    }
    const disposition = res.headers.get("content-disposition") || "";
    const match = /filename="?([^"]+)"?/.exec(disposition);
    const filename = match?.[1] || `aryx_ws${workspaceId}.${format}`;
    const blob = await res.blob();
    return { blob, filename };
  },

  // ── Inference rules (workspace-level, /rules) — Rules tab ────────────
  listWorkspaceRules: (workspaceId: number) =>
    fetchJSON<WorkspaceRule[]>(`/rules?workspace_id=${workspaceId}`),

  upsertWorkspaceRule: (workspaceId: number, name: string,
                        when: Record<string, unknown>,
                        then: Record<string, unknown>, enabled = true) =>
    fetchJSON<WorkspaceRule>("/rules", {
      method: "POST",
      body: JSON.stringify({ workspace_id: workspaceId, name, when, then, enabled }),
    }),

  setWorkspaceRuleEnabled: (workspaceId: number, name: string, enabled: boolean) =>
    fetchJSON<WorkspaceRule>(
      `/rules/${encodeURIComponent(name)}/enabled?workspace_id=${workspaceId}&enabled=${enabled}`,
      { method: "PATCH", body: "{}" },
    ),

  deleteWorkspaceRule: (workspaceId: number, name: string) =>
    fetchJSON<{ status: string; id: number }>(
      `/rules/${encodeURIComponent(name)}?workspace_id=${workspaceId}`,
      { method: "DELETE" },
    ),

  evaluateWorkspaceRules: (workspaceId: number) =>
    fetchJSON<RuleEvaluationResult>(
      `/rules/evaluate?workspace_id=${workspaceId}`,
      { method: "POST", body: "{}" },
    ),

  // ── Ontology versions + change log — Versions tab ─────────────────────
  createOntologySnapshot: (workspaceId: number, label: string, actor = "user") =>
    fetchJSON<OntologyVersion>("/ontology-versions", {
      method: "POST",
      body: JSON.stringify({ workspace_id: workspaceId, label, actor }),
    }),

  listOntologyVersions: (workspaceId: number, limit = 25) =>
    fetchJSON<OntologyVersion[]>(
      `/ontology-versions?workspace_id=${workspaceId}&limit=${limit}`,
    ),

  getOntologyChanges: (workspaceId: number, limit = 50) =>
    fetchJSON<OntologyChange[]>(
      `/ontology-versions/changes?workspace_id=${workspaceId}&limit=${limit}`,
    ),
};
