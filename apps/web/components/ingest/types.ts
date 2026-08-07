// UI-local types for the Documents ingest tab. Wire shapes that the API
// client also needs (DiscoverySummary, SupportedFileTypes) live in
// lib/types.ts and are re-exported here for convenience.
export type { DiscoverySummary, DiscoveryFileSummary, DiscoveryTypeSummary,
              SupportedFileTypes } from "@/lib/types";

/** State machine for the Documents tab.
 *  idle        — nothing uploaded yet
 *  uploading   — POST /admin/docs/read in flight
 *  reading     — discovery_id issued, polling its job status
 *  summary     — read finished, showing discovered types/files for approval
 *  confirming  — POST /admin/docs/confirm in flight
 *  done        — confirm job completed
 *  error       — read or confirm job failed */
export type DocPhase =
  | "idle" | "uploading" | "reading" | "summary" | "confirming"
  | "done" | "error";

/** Shape persisted to localStorage so a long-running read/ingest survives
 *  a reload or navigating away and back. */
export interface DocsSessionState {
  phase: DocPhase;
  discoveryId: string | null;
  jobId: string | null;
  approved: string[];
}
