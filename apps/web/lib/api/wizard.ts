import type { Brief, Datasource, QuizSpec } from "../types";
import { fetchWithShayAuth, createHttpStatusError, readErrorDetail } from "../shay-session";
import { BASE, fetchJSON } from "./core";

export const wizardApi = {
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
};
