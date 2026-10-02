import { fetchBlob, fetchJSON } from "./core";

/** A stored CSV ingestion that was skipped, failed, or loaded with rejected rows. */
export type CsvRun = {
  run_id: string;
  job_id: string | null;
  source_file: string;
  table_name: string | null;
  status: "loaded" | "skipped" | "failed" | string;
  error_code: string | null;
  message: string | null;
  rows_loaded: number;
  rows_bad: number;
  rows_rejected: number;
  rows_truncated: number;
  reject_total: number;
  reject_stored: number;
  file_size: number | null;
  /** True when the original file was kept, so the whole file can be re-run. */
  file_kept: boolean;
  rerun_of: string | null;
  state: "open" | "resolved" | "superseded" | string;
  created_at: string;
  open_rejects: number;
};

/** One rejected row: `{cells}` = malformed as read, `{columns}` = parsed but a value did not fit. */
export type CsvReject = {
  reject_id: number;
  line_no: number | null;
  reason_code: string;
  reason: string | null;
  row: { cells?: string[]; columns?: Record<string, unknown> } | null;
  state: "open" | "resolved" | "retrying" | string;
  attempts: number;
  resolved_at: string | null;
};

export type CsvRerunRowsResult = {
  run_id: string;
  table: string;
  attempted: number;
  inserted: number;
  truncated: number;
  still_rejected: number;
  not_rerunnable: number;
  run_state: string;
};

export type RerunPolicy = "reject" | "truncate";

const ws = (workspaceId: number) => `workspace_id=${workspaceId}`;

export const csvBmlApi = {
  listCsvRuns: (workspaceId: number, jobId?: string, limit = 200) =>
    fetchJSON<CsvRun[]>(
      `/admin/csv-bml/runs?${ws(workspaceId)}&limit=${limit}${jobId ? `&job_id=${encodeURIComponent(jobId)}` : ""}`,
    ),

  getCsvRejects: (runId: string, workspaceId: number, state?: string, offset = 0, limit = 100) =>
    fetchJSON<CsvReject[]>(
      `/admin/csv-bml/runs/${runId}/rejects?${ws(workspaceId)}&offset=${offset}&limit=${limit}`
        + (state ? `&state=${state}` : ""),
    ),

  /** Re-insert the run's open rejected rows (e.g. after widening a column). */
  rerunCsvRejects: (runId: string, workspaceId: number, policy: RerunPolicy = "reject") =>
    fetchJSON<CsvRerunRowsResult>(
      `/admin/csv-bml/runs/${runId}/rerun-rows?${ws(workspaceId)}&policy=${policy}`,
      { method: "POST", body: "{}" },
    ),

  /** Re-run a skipped/failed file as a new upload job. */
  rerunCsvFile: (runId: string, workspaceId: number) =>
    fetchJSON<{ status: string; job_id: string; file: string }>(
      `/admin/csv-bml/runs/${runId}/rerun-file?${ws(workspaceId)}`,
      { method: "POST", body: "{}" },
    ),

  downloadCsvRejects: (runId: string, workspaceId: number) =>
    fetchBlob(`/admin/csv-bml/runs/${runId}/rejects.csv?${ws(workspaceId)}`),
};
