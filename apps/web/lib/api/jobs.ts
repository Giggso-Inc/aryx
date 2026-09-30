import type { IngestQuestion, ObservabilityData } from "../types";
import { fetchJSON } from "./core";

export const jobsApi = {
  // workspaceId: the backend's GET /admin/jobs/{job_id} (and the two
  // siblings below) look the job up scoped to a workspace and 404 if it
  // doesn't match -- omitting it defaults to workspace 1 server-side
  // (see aryx.api.workspace_scope.resolve_workspace_id_warn), which 404s
  // for any job in another workspace even while it's still running
  // successfully. Optional only so an old caller that genuinely doesn't
  // know its workspace yet doesn't break; every caller that has one in
  // scope should pass it.
  getJob: (jobId: string, workspaceId?: number) =>
    fetchJSON<{
      job_id: string; status: string; stage: string | null;
      pct: number | null; detail: string | null; error: string | null;
    }>(`/admin/jobs/${jobId}${workspaceId != null ? `?workspace_id=${workspaceId}` : ""}`),

  listJobs: (workspaceId: number) =>
    fetchJSON<Array<{
      job_id: string; source_system: string; source_dataset: string;
      status: string; stage: string | null; pct: number | null;
      detail: string | null; error: string | null;
      started_at?: string; finished_at?: string | null;
    }>>(`/admin/jobs?workspace_id=${workspaceId}`),

  getJobEvents: (jobId: string, workspaceId?: number) =>
    fetchJSON<Array<{
      stage: string; pct: number; detail: string; ts: string;
    }>>(`/admin/jobs/${jobId}/events${workspaceId != null ? `?workspace_id=${workspaceId}` : ""}`),

  cancelJob: (jobId: string, workspaceId?: number) =>
    fetchJSON<{ status: string; job_id: string }>(
      `/admin/jobs/${jobId}/cancel${workspaceId != null ? `?workspace_id=${workspaceId}` : ""}`,
      { method: "POST", body: "{}" },
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

  getObservability: (workspaceId: number) =>
    fetchJSON<ObservabilityData>(
      `/admin/observability?workspace_id=${workspaceId}`,
    ),
};
